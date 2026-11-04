from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import time
from dataclasses import dataclass, replace
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import Settings, get_settings
from .properties import loaded_files
from .models_catalog import Catalog, ModelInfo, build_catalog, FREE_PROVIDERS, free_models_from
from .providers import Provider, ProviderError, ProviderRequest, StreamEvent, build_provider
from .schemas import ChatRequest, HealthOut, ModelOut, SearchBackendOut
from .search import (
    SearchBackend,
    SearchError,
    add_page_content,
    backend_infos,
    build_search,
    format_context,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-chat.api")
#: Подписи провайдеров для индикаторов доступности
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "mock": "Демо",
}


async def _load_free_models(settings, catalog) -> None:
    """Список бесплатных моделей берём из /models провайдера при старте.

    Имена моделей у Gemini/Groq/OpenRouter меняются, поэтому каталог не
    хардкодим: подключаем те, что реально доступны с этим ключом.
    """
    for name in FREE_PROVIDERS:
        api_key, _ = settings.credentials(name)
        if not api_key:
            continue
        try:
            remote = await build_provider(settings, name).list_remote_models()
        except Exception as exc:  # noqa: BLE001 - провайдер просто не подключаем
            logger.warning("free provider %s недоступен: %s", name, exc)
            continue
        models = free_models_from(name, remote)
        if models:
            catalog.extend(models)
            logger.info("free provider %s: %d моделей", name, len(models))


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _load_free_models(settings, catalog)
        yield

    app = FastAPI(
        lifespan=lifespan,
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
    search_holder: dict[str, SearchBackend | None] = {}

    def search_backend(name: str | None = None) -> SearchBackend | None:
        """Cache one instance per backend name so the UI can switch at runtime."""
        key = (name or app.state.settings.web_search_backend or "off").strip().lower()
        if key not in search_holder:
            search_holder[key] = build_search(app.state.settings, key)
        return search_holder[key]

    def provider(name: str | None = None) -> Provider:
        """One instance per provider profile, built on first use."""
        key = name or app.state.settings.provider
        cached = holder.get(key)
        if cached is None:
            cached = build_provider(app.state.settings, key)
            holder[key] = cached
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
            try:
                search_label = _search_label(search_backend())
            except SearchError:
                search_label = "off"
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                web_search=search_label,
                config_files=loaded_files(),
            )
        try:
            search_label = _search_label(search_backend())
        except SearchError:
            search_label = "off"
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            web_search=search_label,
            config_files=loaded_files(),
        )

    @app.post("/api/models/refresh")
    async def refresh_models() -> dict:
        """Перечитать список бесплатных моделей без перезапуска контейнера."""
        await _load_free_models(settings, catalog)
        return {"models": len(catalog.all())}

    @app.get("/api/providers/status")
    async def providers_status() -> list[dict]:
        """Живая проверка доступности провайдеров — с кешем на минуту."""
        now = time.time()
        cached = getattr(app.state, "provider_status", None)
        if cached and now - cached["at"] < 60:
            return cached["data"]

        names = [settings.provider] if settings.provider != "mock" else []
        names += [name for name in FREE_PROVIDERS if name not in names]
        rows: list[dict] = []
        for name in names:
            api_key, _ = settings.credentials(name)
            row = {
                "provider": name,
                "label": PROVIDER_LABELS.get(name, name.title()),
                "configured": bool(api_key),
                "available": False,
                "models": sum(1 for model in catalog.all() if model.provider == name),
                "latency_ms": 0,
                "error": "",
            }
            if api_key and name != "mock":
                started = time.perf_counter()
                try:
                    await build_provider(settings, name).list_remote_models()
                    row["available"] = True
                except Exception as exc:  # noqa: BLE001 - статус и есть ответ
                    row["error"] = str(exc)[:200]
                row["latency_ms"] = int((time.perf_counter() - started) * 1000)
            rows.append(row)

        app.state.provider_status = {"at": now, "data": rows}
        return rows

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        await _maybe_extend_catalog(app.state.catalog, app.state.settings, provider)
        return [ModelOut(**m.as_dict()) for m in app.state.catalog.all()]

    @app.get("/api/search/backends", response_model=list[SearchBackendOut])
    async def search_backends() -> list[SearchBackendOut]:
        return [SearchBackendOut(**item) for item in backend_infos(app.state.settings)]

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> StreamingResponse:
        model: ModelInfo | None = app.state.catalog.get(payload.model)
        if model is None:
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестная модель {payload.model!r}. Доступные: "
                + ", ".join(m.id for m in app.state.catalog.all()),
            )

        reasoning = _resolve_reasoning(model, payload.reasoning)
        request = ProviderRequest(
            messages=[m.model_dump() for m in payload.messages],
            model=model.id,
            temperature=payload.temperature if model.supports_temperature else None,
            reasoning=reasoning,
            max_tokens=payload.max_tokens,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
        )
        # a model carries its own provider: mock models hit MockProvider,
        # real ones hit the configured API profile
        active = provider(model.provider)  # raises ProviderError → 503 before streaming starts
        logger.info(
            "chat model=%s temperature=%s reasoning=%s messages=%d",
            model.id,
            request.temperature,
            reasoning,
            len(request.messages),
        )
        task = None
        if payload.web_search:
            requested_backend = payload.search_backend or app.state.settings.web_search_backend
            try:
                backend = search_backend(payload.search_backend)
            except SearchError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if backend is None:
                logger.info("web_search requested but backend %r is off", requested_backend)
            else:
                task = _SearchTask(
                    backend=backend,
                    query=payload.messages[-1].content.strip()[:400],
                    limit=app.state.settings.web_search_results,
                    pages=app.state.settings.web_search_pages,
                    page_chars=app.state.settings.web_search_page_chars,
                )
        return StreamingResponse(
            _sse_stream(active, request, task),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def _resolve_reasoning(model: ModelInfo, requested: str) -> str:
    """Model catalog wins: unknown levels are rejected, unsupported → "off"."""
    if not model.reasoning_levels:
        return "off"
    if requested == "off":
        return "off"
    if requested not in model.reasoning_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Модель {model.id} не поддерживает reasoning={requested!r}. "
            f"Доступно: {', '.join(model.reasoning_levels)}",
        )
    return requested


@dataclass
class _SearchTask:
    """A pending web lookup, executed inside the stream so the UI sees progress."""

    backend: SearchBackend
    query: str
    limit: int
    pages: int = 2
    page_chars: int = 1500


def _search_label(backend: SearchBackend | None) -> str:
    return backend.name if backend is not None else "off"


def _augment(messages: list[dict], context: str) -> list[dict]:
    """Insert the search digest as a system message, keeping an existing one first."""
    block = {"role": "system", "content": context}
    if messages and messages[0].get("role") == "system":
        return [messages[0], block, *messages[1:]]
    return [block, *messages]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_stream(
    provider_obj: Provider, request: ProviderRequest, task: _SearchTask | None = None
) -> AsyncIterator[str]:
    done_sent = False
    started = time.perf_counter()
    try:
        if task is not None:
            yield _sse("search_start", {"query": task.query, "backend": task.backend.name})
            try:
                results = await task.backend.search(task.query, task.limit)
                results = await add_page_content(results, top=task.pages, max_chars=task.page_chars)
            except SearchError as exc:
                logger.warning("web search failed: %s", exc)
                yield _sse(
                    "search",
                    {"query": task.query, "backend": task.backend.name, "results": [], "error": str(exc)},
                )
            except Exception as exc:  # noqa: BLE001 - search must never break the chat
                logger.exception("unexpected web search error")
                yield _sse(
                    "search",
                    {"query": task.query, "backend": task.backend.name, "results": [], "error": str(exc)},
                )
            else:
                yield _sse(
                    "search",
                    {
                        "query": task.query,
                        "backend": task.backend.name,
                        # page_text stays server-side: the UI only needs title/url/snippet
                        "results": [
                            {"title": r.title, "url": r.url, "snippet": r.snippet} for r in results
                        ],
                        "error": None,
                    },
                )
                request = replace(
                    request, messages=_augment(request.messages, format_context(task.query, results))
                )

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
    if not settings.dynamic_models or settings.provider == "mock":
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
