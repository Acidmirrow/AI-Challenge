from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import Settings, get_settings
from .models_catalog import Catalog, ModelInfo, build_catalog
from .providers import Provider, ProviderError, ProviderRequest, StreamEvent, build_provider
from .schemas import ChatRequest, HealthOut, ModelOut

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-chat.api")

def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)

    app = FastAPI(
        title="AI Chat API",
        version="1.0.0",
        description="Streaming chat backend with model / temperature / reasoning controls.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.catalog = catalog

    # -- provider: built lazily so a missing API key yields a clean 503 --------
    holder: dict[str, Provider] = {}

    def provider() -> Provider:
        cached = holder.get("provider")
        if cached is None:
            cached = build_provider(app.state.settings)
            holder["provider"] = cached
        return cached

    @app.exception_handler(ProviderError)
    async def _provider_error(_request, exc: ProviderError) -> JSONResponse:
        logger.warning("provider error (%s): %s", exc.kind, exc)
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=exc.status)

    # -- routes ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index() -> dict:
        return {"service": "ai-chat-api", "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        try:
            provider()
        except ProviderError as exc:
            return HealthOut(status="degraded", provider=settings.provider_label, detail=str(exc))
        return HealthOut(status="ok", provider=settings.provider_label)

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        await _maybe_extend_catalog(app.state.catalog, app.state.settings, provider)
        return [ModelOut(**m.as_dict()) for m in app.state.catalog.all()]

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> StreamingResponse:
        model: ModelInfo | None = app.state.catalog.get(payload.model)
        if model is None:
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестная модель {payload.model!r}. Доступные: "
                + ", ".join(m.id for m in app.state.catalog.all()),
            )

        reasoning = payload.reasoning if model.supports_reasoning else "off"
        request = ProviderRequest(
            messages=[m.model_dump() for m in payload.messages],
            model=model.id,
            temperature=payload.temperature if model.supports_temperature else None,
            reasoning=reasoning,
            max_tokens=payload.max_tokens,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
        )
        active = provider()  # raises ProviderError → 503 before streaming starts
        logger.info(
            "chat model=%s temperature=%s reasoning=%s messages=%d",
            model.id,
            request.temperature,
            reasoning,
            len(request.messages),
        )
        return StreamingResponse(
            _sse_stream(active, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_stream(provider_obj: Provider, request: ProviderRequest) -> AsyncIterator[str]:
    done_sent = False
    started = time.perf_counter()
    try:
        async for event in provider_obj.stream(request):
            if event.type == "done":
                done_sent = True
                yield _sse("done", event.data)
            else:
                yield _sse(event.type, {"text": event.text})
        if not done_sent:
            yield _sse("done", {"model": request.model, "elapsed_ms": int((time.perf_counter() - started) * 1000)})
    except ProviderError as exc:
        logger.warning("stream error (%s): %s", exc.kind, exc)
        yield _sse("error", {"message": str(exc), "kind": exc.kind})
    except asyncio.CancelledError:  # client disconnected
        raise
    except Exception:  # noqa: BLE001 - never leak a traceback into the UI
        logger.exception("unhandled error while streaming")
        yield _sse("error", {"message": "Внутренняя ошибка сервера при генерации ответа.", "kind": "internal"})


async def _maybe_extend_catalog(catalog: Catalog, settings: Settings, provider_getter) -> None:
    """Optionally merge models advertised by the upstream /models endpoint."""
    if not settings.dynamic_models or settings.provider != "openai":
        return
    try:
        provider_obj = provider_getter()
    except ProviderError:
        return
    lister = getattr(provider_obj, "list_remote_models", None)
    if lister is None:
        return
    try:
        ids: list[str] = await lister()
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        logger.info("model discovery failed: %s", exc)
        return
    catalog.extend([ModelInfo(id=i, label=i) for i in ids])


app = create_app()
