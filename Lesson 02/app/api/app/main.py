from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .formats import (
    FORMATS,
    FORMATS_BY_ID,
    PRESETS,
    FormatSpec,
    build_format_request,
    parse_check,
    parse_payload,
)
from .models_catalog import ModelInfo, build_catalog, FREE_PROVIDERS, free_models_from
from .properties import loaded_files
from .providers import Provider, ProviderError, ProviderRequest, build_provider
from .schemas import FormatOut, FormatRunRequest, HealthOut, ModelOut
from .validation import InvalidSchema, check_schema, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("format-lab.api")
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
        except Exception as exc:  # noqa: BLE001 - провайдер не отвечает
            logger.warning("free provider %s недоступен: %s", name, exc)
            # не выходим: для Groq есть запасной список, остальные просто пропускаем
            remote = []
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
        title="AI Format Lab",
        version="1.0.0",
        description="Урок 02: форматы ответа модели — текст, Markdown, JSON, schema, tool call.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.catalog = catalog

    holder: dict[str, Provider] = {}

    def provider(name: str | None = None) -> Provider:
        key = name or app.state.settings.provider
        if key not in holder:
            holder[key] = build_provider(app.state.settings, key)
        return holder[key]

    @app.exception_handler(ProviderError)
    async def _provider_error(_request, exc: ProviderError) -> JSONResponse:
        logger.warning("provider error (%s): %s", exc.kind, exc)
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=exc.status)

    # -- routes ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index() -> dict:
        return {"service": "ai-format-lab", "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        try:
            provider()
        except ProviderError as exc:
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                formats=len(FORMATS),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            formats=len(FORMATS),
            config_files=loaded_files(),
        )

    @app.get("/api/formats", response_model=list[FormatOut])
    async def formats() -> list[FormatOut]:
        return [
            FormatOut(
                id=spec.id,
                label=spec.label,
                description=spec.description,
                needs_schema=spec.needs_schema,
                uses_tools=spec.uses_tools,
                default_instruction=spec.system_hint,
            )
            for spec in FORMATS
        ]

    @app.get("/api/presets")
    async def presets() -> list[dict]:
        return PRESETS

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
        return [ModelOut(**model.as_dict()) for model in app.state.catalog.all()]

    @app.post("/api/format/run")
    async def run(payload: FormatRunRequest) -> StreamingResponse:
        spec = FORMATS_BY_ID[payload.format]
        model: ModelInfo | None = app.state.catalog.get(payload.model)
        if model is None:
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестная модель {payload.model!r}. Доступные: "
                + ", ".join(m.id for m in app.state.catalog.all()),
            )
        if spec.needs_schema and not payload.schema_:
            raise HTTPException(status_code=400, detail=f"Формат {spec.id} требует JSON Schema")
        if payload.schema_:
            try:
                check_schema(payload.schema_)
            except InvalidSchema as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        reasoning = _resolve_reasoning(model, payload.reasoning)
        active = provider(model.provider)
        logger.info(
            "run format=%s model=%s reasoning=%s schema=%s max_tokens=%s",
            spec.id,
            model.id,
            reasoning,
            bool(payload.schema_),
            payload.max_tokens,
        )
        return StreamingResponse(
            _run_format(active, spec, model, payload, reasoning),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def _resolve_reasoning(model: ModelInfo, requested: str) -> str:
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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_format(
    provider_obj: Provider,
    spec: FormatSpec,
    model: ModelInfo,
    payload: FormatRunRequest,
    reasoning: str,
) -> AsyncIterator[str]:
    built = build_format_request(
        spec,
        payload.prompt,
        payload.schema_,
        schema_name=payload.schema_name,
        tool_name=payload.tool_name,
        reasoning=reasoning,
        system_prompt=payload.system_prompt,
        supports_json_schema=model.supports_json_schema,
    )
    results: list[dict] = []

    try:
        yield _sse(
            "start",
            {
                "format": spec.id,
                "model": model.id,
                "tool_choice": built.tool_choice if spec.uses_tools else None,
                "notes": built.notes,
            },
        )
        started = time.perf_counter()
        raw_text, tool_args, tool_name, finish_reason, usage = "", "", None, None, {}

        request = ProviderRequest(
            messages=built.messages,
            model=model.id,
            temperature=payload.temperature if model.supports_temperature else None,
            reasoning=reasoning,
            max_tokens=payload.max_tokens,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
            response_format=built.response_format,
            stop=payload.stop,
            tools=built.tools,
            tool_choice=built.tool_choice,
            schema=payload.schema_,
            schema_name=payload.schema_name,
            tool_name=payload.tool_name,
        )
        async for event in provider_obj.stream(request):
            if event.type == "delta":
                raw_text += event.text
                yield _sse("delta", {"kind": "text", "text": event.text})
            elif event.type == "tool_delta":
                tool_args += event.text
                yield _sse("delta", {"kind": "tool_args", "text": event.text})
            elif event.type == "done":
                finish_reason = event.data.get("finish_reason")
                tool_name = event.data.get("tool_name")
                usage = {
                    key: event.data[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in event.data
                }

        parsed, tool_call, parse_error = parse_payload(spec, raw_text, tool_args, tool_name)
        errors = (
            [{"path": "(root)", "message": parse_error, "validator": "json"}]
            if parse_error
            else validate(parsed, payload.schema_ or {}) if spec.needs_schema else []
        )

        check = parse_check(spec, raw_text, tool_call)
        results.append(
            {
                "finish_reason": finish_reason,
                # length = модель упёрлась в max_tokens, ответ неполный
                "truncated": finish_reason == "length",
                "raw_text": raw_text,
                "tool_call": tool_call,
                "parsed": parsed,
                "validation": {
                    "valid": not errors,
                    "errors": errors,
                    "applicable": bool(spec.needs_schema),
                },
                "parse_check": check,
                "usage": usage,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
        )
        yield _sse(
            "run_result",
            {
                "parse_check": check,
                "validation": {"valid": not errors},
                "truncated": finish_reason == "length",
            },
        )

        summary = _summarize(results)
        first = results[0] if results else {}
        yield _sse(
            "result",
            {
                "format": spec.id,
                "model": model.id,
                "runs": len(results),
                "results": results,
                "summary": summary,
                "notes": built.notes,
                "limit": {
                    "truncated": finish_reason == "length",
                    "max_tokens": payload.max_tokens,
                },
                "sent": {
                    "messages": built.messages,
                    "response_format": built.response_format,
                    "stop": payload.stop,
                    "tools": built.tools,
                    "tool_choice": built.tool_choice,
                    "temperature": payload.temperature,
                    "reasoning": reasoning,
                    "max_tokens": payload.max_tokens,
                },
                **first,
            },
        )
    except ProviderError as exc:
        logger.warning("format run error (%s): %s", exc.kind, exc)
        hint = ""
        if "response_format" in str(exc):
            hint = " Попробуй формат json_object или tool_call."
        yield _sse("error", {"message": str(exc) + hint, "kind": exc.kind})
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - не светим трейсбек в UI
        logger.exception("unhandled error in format run")
        yield _sse("error", {"message": "Внутренняя ошибка при обработке ответа.", "kind": "internal"})


def _summarize(results: list[dict]) -> dict:
    """Агрегаты по прогонам: токены, причины остановки, доли парсинга и валидности."""
    if not results:
        return {}
    tokens = [item["usage"].get("completion_tokens") or 0 for item in results]
    finishes: dict[str, int] = {}
    for item in results:
        key = item.get("finish_reason") or "none"
        finishes[key] = finishes.get(key, 0) + 1
    parseable = sum(1 for item in results if item["parse_check"]["ok"])
    valid = sum(1 for item in results if item["validation"]["valid"])
    return {
        "runs": len(results),
        "avg_completion_tokens": round(sum(tokens) / len(tokens), 1) if tokens else 0,
        "finish_reasons": finishes,
        "parseable": parseable,
        "valid": valid,
    }


app = create_app()
