"""API урока 06: ИИ-агент с инструментами и трассой шагов.

Модель получает задачу и набор функций, сама выбирает вызов, сервер выполняет
его и возвращает наблюдение. Цикл повторяется до финального ответа или лимита
шагов; наружу уходит ответ плюс все вызовы инструментов.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import Agent, AgentConfig
from .agent_tools import DEFAULT_REGISTRY, tool_catalog
from .config import get_settings
from .models_catalog import FREE_PROVIDERS, ModelInfo, build_catalog, free_models_from
from .pricing import cost_of, load_prices
from .properties import loaded_files
from .providers import Provider, ProviderError, build_provider
from .schemas import AgentOut, AgentRequest, HealthOut, ModelOut, ToolOut

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("agent-lab.api")

#: Подписи провайдеров для индикаторов доступности
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "nous": "Nous Portal",
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
            remote = []
        models = free_models_from(name, remote)
        if models:
            catalog.extend(models)
            logger.info("free provider %s: %d моделей", name, len(models))


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


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)
    prices = load_prices(settings.pricing_file)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _load_free_models(settings, catalog)
        yield

    app = FastAPI(
        title="AI Agent Lab",
        version="1.0.0",
        description=(
            "Урок 06: ИИ-агент с инструментами — калькулятор, время, статистика "
            "текста и курсы валют."
        ),
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
    app.state.prices = prices

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
                tools=len(DEFAULT_REGISTRY),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            tools=len(DEFAULT_REGISTRY),
            config_files=loaded_files(),
        )

    @app.get("/api/tools", response_model=list[ToolOut])
    async def tools() -> list[ToolOut]:
        return [ToolOut(**item) for item in tool_catalog()]

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

    @app.post("/api/agent", response_model=AgentOut)
    async def agent(payload: AgentRequest) -> AgentOut:
        """Запустить агентский цикл: инструменты, наблюдения и итоговый ответ."""
        model = _model(app, payload.model)
        available = DEFAULT_REGISTRY.names
        selected = available if payload.tools is None else list(dict.fromkeys(payload.tools))
        unknown = [name for name in selected if name not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Неизвестный инструмент: {unknown[0]}")
        agent = Agent(
            provider(model.provider),
            DEFAULT_REGISTRY.select(selected),
            AgentConfig(
                model=model.id,
                temperature=payload.temperature,
                reasoning=_soft_reasoning(model, payload.reasoning),
                max_tokens=payload.max_tokens,
                max_steps=payload.max_steps,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            ),
        )
        result = await agent.run(payload.prompt)
        _, _, cost, note = cost_of(app.state.prices, model.id, model.provider, result.usage)
        return AgentOut(
            model=model.id,
            label=model.label,
            provider=model.provider,
            answer=result.answer,
            steps=result.steps,
            usage=result.usage,
            elapsed_ms=result.elapsed_ms,
            finish_reason=result.finish_reason,
            truncated=result.truncated,
            stopped_reason=result.stopped_reason,
            tools=result.tools,
            missing_tools=result.missing_tools,
            cost_usd=cost,
            cost_note=note,
        )

    return app


app = create_app()
