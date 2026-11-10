"""API урока 07: агент с сохранённым контекстом и историей инструментов.

История каждого диалога лежит в SQLite. В неё входят не только реплики,
но и tool calls с наблюдениями инструментов. На новом запросе агент
восстанавливает окно контекста, продолжает диалог и дописывает новые ходы.
"""

from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import Agent, AgentConfig
from .agent_tools import DEFAULT_REGISTRY
from .config import get_settings
from .context import build_context, merge_histories
from .models_catalog import FREE_PROVIDERS, ModelInfo, build_catalog, free_models_from
from .properties import loaded_files
from .providers import Provider, ProviderError, build_provider
from .schemas import (
    ChatOut,
    ChatRequest,
    ContextOut,
    HealthOut,
    MessageOut,
    ModelOut,
    SessionDetailOut,
    SessionOut,
)
from .storage import ContextStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("context-lab.api")

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "nous": "Nous Portal",
    "mock": "Демо",
}


async def _load_free_models(settings, catalog) -> None:
    for name in FREE_PROVIDERS:
        api_key, _ = settings.credentials(name)
        if not api_key:
            continue
        try:
            remote = await build_provider(settings, name).list_remote_models()
        except Exception as exc:  # noqa: BLE001 - провайдер может не отвечать
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


def _mentioned_session_ids(store: ContextStore, prompt: str, current: str) -> list[str]:
    """Найти сессии, на которые пользователь явно ссылается в тексте."""
    found: list[str] = []
    for raw in re.findall(r"(?i)диалог\w*\s*#?(\d+)", prompt):
        row = store.get_session_by_number(int(raw))
        if row and row["id"] != current:
            found.append(row["id"])

    # «все прошлые сессии», «из разных сессий», «в прошлой беседе» — весь архив
    if re.search(
        r"(?i)(все|разн\w*|прошл\w*)\s+(?:\w+\s+)?(сесси|диалог|бесед)",
        prompt,
    ):
        found.extend(
            item["id"] for item in store.list_sessions() if item["id"] != current
        )
    return list(dict.fromkeys(found))


def _soft_reasoning(model: ModelInfo, wanted: str) -> str:
    levels = list(model.reasoning_levels or ())
    if not levels:
        return "off"
    if wanted in levels:
        return wanted
    return "none" if "none" in levels else levels[0]


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)
    store = ContextStore(settings.context_db_path)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _load_free_models(settings, catalog)
        yield

    app = FastAPI(
        title="Context Lab",
        version="1.0.0",
        description="Урок 07: сохранение контекста диалога в SQLite.",
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
    app.state.store = store

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
            provider().name
        except ProviderError as exc:
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                storage=settings.context_db_path,
                sessions=store.count_sessions(),
                max_context_messages=settings.context_max_messages,
                max_context_chars=settings.context_max_chars,
                tools=len(DEFAULT_REGISTRY),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            storage=settings.context_db_path,
            sessions=store.count_sessions(),
            max_context_messages=settings.context_max_messages,
            max_context_chars=settings.context_max_chars,
            tools=len(DEFAULT_REGISTRY),
            config_files=loaded_files(),
        )

    @app.get("/api/providers/status")
    async def providers_status() -> list[dict]:
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

    @app.get("/api/tools")
    async def tools() -> list[dict]:
        return DEFAULT_REGISTRY.catalog()

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        return [ModelOut(**model.as_dict()) for model in app.state.catalog.all()]

    @app.post("/api/models/refresh")
    async def refresh_models() -> dict:
        await _load_free_models(settings, catalog)
        return {"models": len(catalog.all())}

    @app.get("/api/sessions", response_model=list[SessionOut])
    async def sessions() -> list[SessionOut]:
        return [SessionOut(**row) for row in store.list_sessions()]

    @app.get("/api/sessions/{session_id}", response_model=SessionDetailOut)
    async def session_detail(session_id: str) -> SessionDetailOut:
        row = store.get_session(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        messages = store.history(session_id)
        return SessionDetailOut(**row, messages=[MessageOut(**item) for item in messages])

    @app.delete("/api/sessions")
    async def delete_all_sessions() -> dict:
        """Удалить все сохранённые диалоги и их историю."""
        sessions, messages = store.delete_all()
        return {"deleted_sessions": sessions, "deleted_messages": messages}

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict:
        if not store.delete(session_id):
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        return {"deleted": session_id}

    @app.post("/api/sessions/{session_id}/clear")
    async def clear_session(session_id: str) -> SessionOut:
        if store.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="Сессия не найдена")
        store.clear(session_id)
        row = store.get_session(session_id) or {}
        return SessionOut(**row)

    @app.post("/api/chat", response_model=ChatOut)
    async def chat(payload: ChatRequest) -> ChatOut:
        """Один ход агента: сохранённый контекст → инструменты → ответ."""
        model = _model(app, payload.model)
        available = DEFAULT_REGISTRY.names
        selected = available if payload.tools is None else list(dict.fromkeys(payload.tools))
        unknown = [name for name in selected if name not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Неизвестный инструмент: {unknown[0]}")

        store.create_session(payload.session_id)
        history = store.history(payload.session_id)

        requested = [
            sid for sid in dict.fromkeys(
                [
                    *_mentioned_session_ids(store, payload.prompt, payload.session_id),
                    *payload.context_sessions,
                ]
            )
            if sid != payload.session_id
        ]
        past: list[tuple[str, list[dict]]] = []
        past_labels: dict[str, str] = {}
        selected_past: list[str] = []
        for sid in requested:
            row = store.get_session(sid)
            if row is None:
                raise HTTPException(status_code=400, detail=f"Неизвестная сессия контекста: {sid}")
            past_history = store.history(sid)
            if past_history:
                past.append((sid, past_history))
                selected_past.append(sid)
                past_labels[sid] = (
                    f"Диалог {row.get('number')} · {row.get('title') or 'без темы'}"
                )

        combined = merge_histories(history, past, labels=past_labels)
        max_messages = min(payload.max_messages, 500)
        window = build_context(
            combined,
            payload.prompt,
            max_messages=max_messages,
            max_chars=settings.context_max_chars,
        )

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
        result = await agent.run(payload.prompt, history=window.history)

        store.append(payload.session_id, "user", payload.prompt)
        if result.new_messages:
            for message in result.new_messages:
                # служебная подсказка при исчерпании шагов не является репликой
                if (
                    message.get("role") == "user"
                    and str(message.get("content") or "").startswith("Лимит шагов исчерпан")
                ):
                    continue
                store.append(
                    payload.session_id,
                    message["role"],
                    message.get("content") or "",
                    tool_calls=message.get("tool_calls") or [],
                    tool_call_id=message.get("tool_call_id") or "",
                    name=message.get("name") or "",
                )
        else:
            store.append(payload.session_id, "assistant", result.answer)

        messages = store.history(payload.session_id)
        usage = dict(result.usage)
        usage["total_tokens"] = max(
            int(usage.get("total_tokens") or 0),
            int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0),
        )

        return ChatOut(
            answer=result.answer,
            session_id=payload.session_id,
            model=model.id,
            label=model.label,
            provider=model.provider,
            messages=[MessageOut(**item) for item in messages],
            context=ContextOut(
                included_messages=window.included,
                dropped_messages=window.dropped,
                chars=window.chars,
                max_messages=max_messages,
                max_chars=settings.context_max_chars,
                past_sessions=len(selected_past),
            ),
            steps=result.steps,
            tools=result.tools,
            missing_tools=result.missing_tools,
            context_sessions=selected_past,
            usage=usage,
            elapsed_ms=result.elapsed_ms,
            finish_reason=result.finish_reason,
            stopped_reason=result.stopped_reason,
            total_messages=len(messages),
        )

    return app


app = create_app()
