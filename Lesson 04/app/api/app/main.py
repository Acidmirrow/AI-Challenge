"""API урока 04: сравнение ответов модели при разных температурах.

Температура — единственная ручка, которую здесь крутим. Один и тот же промпт
прогоняется при нескольких значениях (по умолчанию 0, 0.7 и 1.2), рядом с
ответом едут токены, время и признак обрыва по лимиту.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .models_catalog import FREE_PROVIDERS, ModelInfo, build_catalog, free_models_from
from .properties import loaded_files
from .providers import Provider, ProviderError, ProviderRequest, build_provider
from .schemas import (
    AnalyzeOut,
    AnalyzeRequest,
    ChatRequest,
    CompareTemperaturesOut,
    CompareTemperaturesRequest,
    HealthOut,
    ModelOut,
    TaskOut,
    TemperatureRun,
)
from .tasks import TASKS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("temperature-lab.api")


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
    """Список бесплатных моделей берём из /models провайдера при старте."""
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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _model(app: FastAPI, model_id: str) -> ModelInfo:
    model = app.state.catalog.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Неизвестная модель: {model_id}")
    return model


def _soft_reasoning(model: ModelInfo, wanted: str) -> str:
    """Уровень reasoning, который модель реально понимает (иначе off)."""
    levels = list(model.reasoning_levels or ())
    if not levels:
        return "off"
    if wanted in levels:
        return wanted
    return "none" if "none" in levels else levels[0]


def _text_of(messages: list[dict]) -> list[dict]:
    return [{"role": item["role"], "content": item["content"]} for item in messages]


async def _collect(active: Provider, request: ProviderRequest) -> tuple[str, str, str | None, dict]:
    """Слить поток провайдера в текст: (ответ, reasoning, finish_reason, usage)."""
    raw, native, finish_reason, usage = "", "", None, {}
    async for event in active.stream(request):
        if event.type == "reasoning":
            native += event.text
        elif event.type == "delta":
            raw += event.text
        elif event.type == "done":
            finish_reason = event.data.get("finish_reason")
            usage = {
                key: event.data[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if key in event.data
            }
    return raw, native, finish_reason, usage


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _load_free_models(settings, catalog)
        yield

    app = FastAPI(
        title="AI Temperature Lab",
        version="1.0.0",
        description="Урок 04: один промпт при разных температурах — чат и сравнительная таблица.",
        lifespan=lifespan,
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
        return JSONResponse(
            status_code=exc.status,
            content={"detail": str(exc), "kind": exc.kind},
        )

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        try:
            provider().name  # провайдер строится без сети: проверяем только наличие ключа
        except ProviderError as exc:
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                tasks=len(TASKS),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            tasks=len(TASKS),
            config_files=loaded_files(),
        )

    @app.get("/api/tasks", response_model=list[TaskOut])
    async def tasks() -> list[TaskOut]:
        return [TaskOut(**task.as_dict()) for task in TASKS]

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

    @app.post("/api/models/refresh")
    async def refresh_models() -> dict:
        """Перечитать список бесплатных моделей без перезапуска контейнера."""
        await _load_free_models(settings, catalog)
        return {"models": len(catalog.all())}

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        return [ModelOut(**model.as_dict()) for model in app.state.catalog.all()]

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> StreamingResponse:
        model = _model(app, payload.model)
        active = provider(model.provider)
        request = ProviderRequest(
            messages=_text_of([item.model_dump() for item in payload.messages]),
            model=model.id,
            temperature=payload.temperature if model.supports_temperature else None,
            reasoning=_soft_reasoning(model, payload.reasoning),
            max_tokens=payload.max_tokens,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
        )

        async def stream():
            started = time.perf_counter()
            done_sent = False
            yield _sse("start", {"model": model.id, "temperature": payload.temperature})
            try:
                async for event in active.stream(request):
                    if event.type == "done":
                        done_sent = True
                        yield _sse("done", {**event.data, "temperature": payload.temperature})
                    else:
                        yield _sse(event.type, {"text": event.text})
                if not done_sent:
                    yield _sse(
                        "done",
                        {
                            "model": model.id,
                            "elapsed_ms": int((time.perf_counter() - started) * 1000),
                            "temperature": payload.temperature,
                        },
                    )
            except ProviderError as exc:
                logger.warning("stream error (%s): %s", exc.kind, exc)
                yield _sse("error", {"message": str(exc), "kind": exc.kind})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("unhandled error while streaming")
                yield _sse("error", {"message": "Внутренняя ошибка сервера.", "kind": "internal"})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/temperature/compare", response_model=CompareTemperaturesOut)
    async def compare_temperatures(payload: CompareTemperaturesRequest) -> CompareTemperaturesOut:
        """Один промпт при разных температурах, с повторами на каждое значение."""
        model = _model(app, payload.model)
        active = provider(model.provider)
        reasoning = _soft_reasoning(model, payload.reasoning)

        async def run_one(temperature: float, repeat: int) -> TemperatureRun:
            request = ProviderRequest(
                messages=[{"role": "user", "content": payload.prompt}],
                model=model.id,
                temperature=temperature if model.supports_temperature else None,
                reasoning=reasoning,
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            )
            started = time.perf_counter()
            async with semaphore:
                try:
                    raw, native, finish_reason, usage = await _collect(active, request)
                except ProviderError as exc:
                    return TemperatureRun(
                        temperature=temperature,
                        repeat=repeat,
                        error=str(exc),
                        elapsed_ms=int((time.perf_counter() - started) * 1000),
                    )
            return TemperatureRun(
                temperature=temperature,
                repeat=repeat,
                answer=raw.strip(),
                reasoning=native.strip(),
                usage=usage,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                finish_reason=finish_reason,
                truncated=finish_reason == "length",
            )

        # одинаковые значения не гоняем дважды: сравнение должно быть по разным температурам
        wanted = sorted({round(float(value), 2) for value in payload.temperatures})
        # 0 повторов — один запрос на температуру, N — ещё N независимых запросов
        attempts = payload.repeats + 1
        semaphore = asyncio.Semaphore(3)
        runs = list(
            await asyncio.gather(
                *(run_one(value, repeat) for value in wanted for repeat in range(attempts))
            )
        )
        runs.sort(key=lambda item: (item.temperature, item.repeat))

        grouped: dict[float, list[TemperatureRun]] = {}
        for run in runs:
            grouped.setdefault(run.temperature, []).append(run)

        answers = [run.answer for run in runs if run.answer]
        lengths = [len(answer) for answer in answers]
        per_temperature = {
            f"{temperature:.1f}": {
                "runs": len(items),
                "unique": len({_normalize(item.answer) for item in items if item.answer}),
                "errors": sum(1 for item in items if item.error),
                "truncated": sum(1 for item in items if item.truncated),
            }
            for temperature, items in sorted(grouped.items())
        }
        spread = {
            "unique_answers": len({_normalize(answer) for answer in answers}),
            "answers": len(answers),
            "min_length": min(lengths) if lengths else 0,
            "max_length": max(lengths) if lengths else 0,
            "errors": sum(1 for run in runs if run.error),
            "truncated": sum(1 for run in runs if run.truncated),
            "repeats": payload.repeats,
            "per_temperature": per_temperature,
        }
        return CompareTemperaturesOut(
            model=model.id,
            prompt=payload.prompt,
            task=payload.task,
            runs=runs,
            spread=spread,
        )

    @app.post("/api/analyze", response_model=AnalyzeOut)
    async def analyze(payload: AnalyzeRequest) -> AnalyzeOut:
        """Модель-аналитик сравнивает ответы, полученные при разных температурах."""
        model = _model(app, payload.model)
        active = provider(model.provider)

        lines = [f"Промпт:\n{payload.prompt}", ""]
        if payload.reference:
            lines.append(f"Эталонный ответ: {payload.reference}")
            lines.append("")
        lines.append("Ответы модели при разных температурах:")
        for run in payload.runs:
            temperature = run.get("temperature")
            repeat = int(run.get("repeat") or 0)
            answer = str(run.get("answer") or "").strip() or "(пустой ответ)"
            lines.append(f"--- temperature={temperature}, повтор {repeat + 1} ---")
            lines.append(answer[:4000])
            lines.append("")

        system = (
            "Ты — аналитик ответов языковой модели. Тебе дают один промпт и ответы этой "
            "модели при разных температурах, а внутри одной температуры — несколько повторов "
            "одного и того же запроса. Сравни их по существу и ответь по-русски, кратко:\n"
            "1) что изменилось между температурами (факты, формулировки, структура, длина);\n"
            "2) насколько устойчива каждая температура: совпадают ли повторы между собой, "
            "что именно меняется от повтора к повтору (это и есть разброс модели);\n"
            "3) какой ответ лучше и почему;\n"
            "4) есть ли ошибки, выдумки или потерянные условия (если дан эталон — сверь с ним);\n"
            "5) какую температуру рекомендовать для такой задачи и почему.\n"
            "Не пересказывай ответы целиком, не выдумывай того, чего в них нет."
        )

        started = time.perf_counter()
        raw, _, finish_reason, usage = await _collect(
            active,
            ProviderRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                model=model.id,
                temperature=0.2 if model.supports_temperature else None,
                reasoning=_soft_reasoning(model, "off"),
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            ),
        )
        return AnalyzeOut(
            model=model.id,
            text=raw.strip(),
            usage=usage,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
        )

    return app


def _normalize(text: str) -> str:
    """Грубая нормализация для подсчёта разных ответов."""
    return " ".join(text.lower().split())


app = create_app()
