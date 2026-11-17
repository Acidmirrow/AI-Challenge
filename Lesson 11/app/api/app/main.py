"""API урока 11: трёхслойная модель памяти ассистента."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .context import build_context
from .llm import chat_with_usage as model_chat
from .memory import (
    DEFAULT_OWNER,
    DEFAULT_SESSION_ID,
    DEFAULT_DB_PATH,
    LONG_SECTIONS,
    LONG_TERM_CONTEXT_TOKENS,
    LONG_TERM_RETRIEVE_LIMIT,
    MemoryStore,
    SHORT_TERM_LIMIT,
    SHORT_TERM_PROMPT_WINDOW,
    SHORT_TERM_TTL_HOURS,
    WORKING_TTL_HOURS,
)

TITLE = "Модель памяти ассистента"
DB_PATH = os.getenv("MEMORY_DB_PATH", DEFAULT_DB_PATH)
store = MemoryStore(DB_PATH)

app = FastAPI(
    title="Assistant Memory Lab",
    version="1.1.0",
    description="Урок 11: краткосрочная, рабочая и долговременная память ассистента.",
)


@app.middleware("http")
async def no_store(request: Request, call_next):
    """Память читается из SQLite при каждом запросе, без HTTP-кеша."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


class SessionRequest(BaseModel):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)
    owner_id: str = Field(default=DEFAULT_OWNER, min_length=1, max_length=80)


class MessageRequest(SessionRequest):
    role: Literal["user", "assistant"] = "user"
    content: str = Field(min_length=1, max_length=4_000)


class ChatRequest(SessionRequest):
    message: str = Field(min_length=1, max_length=4_000)


class WorkingRequest(SessionRequest):
    title: str = Field(default="", max_length=4_000)
    goal: str = Field(default="", max_length=4_000)
    status: str = Field(default="", max_length=4_000)
    next_step: str = Field(default="", max_length=4_000)
    constraints: str = Field(default="", max_length=4_000)


class LongTermRequest(BaseModel):
    owner_id: str = Field(default=DEFAULT_OWNER, min_length=1, max_length=80)
    section: Literal["profile", "decisions", "knowledge"]
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=4_000)
    source: str = Field(default="пользователь", max_length=200)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    ttl_hours: float | None = Field(default=None, ge=0.0, le=24 * 365 * 10)


def _session(session_id: str | None) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip()[:80] or DEFAULT_SESSION_ID


def _owner(owner_id: str | None) -> str:
    return (owner_id or DEFAULT_OWNER).strip()[:80] or DEFAULT_OWNER


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "lesson": 11,
        "title": TITLE,
        "layers": ["short_term", "working", "long_term"],
        "short_term_limit": SHORT_TERM_LIMIT,
        "short_term_ttl_hours": SHORT_TERM_TTL_HOURS,
        "working_ttl_hours": WORKING_TTL_HOURS,
        "retrieval_limit": LONG_TERM_RETRIEVE_LIMIT,
    }


@app.get("/api/model")
async def memory_model() -> dict:
    return {
        "title": TITLE,
        "description": (
            "Память ассистента разделена на три слоя. Каждый слой отвечает на свой "
            "вопрос, имеет собственное время жизни и правила записи."
        ),
        "layers": [
            {
                "id": "short_term",
                "label": "Краткосрочная",
                "subtitle": "Текущий диалог",
                "storage": "SQLite, owner + session",
                "lifetime": f"TTL {SHORT_TERM_TTL_HOURS} ч · последние {SHORT_TERM_LIMIT} сообщений",
                "prompt_window": SHORT_TERM_PROMPT_WINDOW,
                "description": (
                    "Последние реплики пользователя и ассистента. Нужна для связности "
                    "разговора; старые сообщения вытесняются, срок жизни ограничен."
                ),
                "examples": ["приветствие", "уточнение", "последний вопрос"],
            },
            {
                "id": "working",
                "label": "Рабочая",
                "subtitle": "Данные текущей задачи",
                "storage": "SQLite, owner + session",
                "lifetime": f"TTL {WORKING_TTL_HOURS} ч или до очистки",
                "description": (
                    "Цель, статус, следующий шаг и ограничения текущей задачи. "
                    "Помогает не терять контекст работы между сообщениями."
                ),
                "examples": ["цель задачи", "статус", "следующий шаг", "ограничения"],
            },
            {
                "id": "long_term",
                "label": "Долговременная",
                "subtitle": "Профиль, решения, знания",
                "storage": "SQLite + FTS5, owner",
                "lifetime": "профиль/решения — долго; знания — до TTL",
                "description": (
                    "Профиль, решения и знания с provenance и confidence. В контекст "
                    "попадает только релевантная выборка, а не вся память."
                ),
                "examples": ["профиль", "решения", "знания"],
            },
        ],
        "context_order": [
            "system prompt",
            "долговременная память (релевантная выборка)",
            "рабочая память",
            "краткосрочная память",
            "сообщения диалога",
        ],
        "retrieval": {
            "limit": LONG_TERM_RETRIEVE_LIMIT,
            "token_budget": LONG_TERM_CONTEXT_TOKENS,
            "method": "FTS5 + профиль + confidence/recency/importance",
        },
    }


@app.get("/api/state")
async def state(
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
    session_id: str = Query(default=DEFAULT_SESSION_ID, max_length=80),
) -> dict:
    return store.state(_owner(owner_id), _session(session_id))


@app.get("/api/context")
async def context(
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
    session_id: str = Query(default=DEFAULT_SESSION_ID, max_length=80),
    q: str = Query(default="", max_length=4_000),
) -> dict:
    current = store.state(_owner(owner_id), _session(session_id))
    retrieved = store.retrieve(_owner(owner_id), q)
    return {
        **build_context(current, retrieved=retrieved),
        "session_id": current["session_id"],
        "owner_id": current["owner_id"],
        "query": q,
    }


@app.post("/api/message")
async def append_message(payload: MessageRequest) -> dict:
    try:
        item = store.append_short(
            payload.owner_id, payload.session_id, payload.role, payload.content
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "message": item,
        "state": store.state(payload.owner_id, payload.session_id),
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    owner_id = _owner(payload.owner_id)
    session_id = _session(payload.session_id)
    store.append_short(owner_id, session_id, "user", payload.message)
    current = store.state(owner_id, session_id)
    retrieved = store.retrieve(owner_id, payload.message)
    built = build_context(current, retrieved=retrieved)
    answer, model, usage = await run_in_threadpool(model_chat, built["messages"])
    prompt_tokens = int(usage.get("prompt_tokens") or built["total_tokens"])
    response_tokens = int(usage.get("completion_tokens") or 0)
    store.append_short(
        owner_id,
        session_id,
        "assistant",
        answer,
        prompt_tokens=prompt_tokens,
        completion_tokens=response_tokens,
    )
    return {
        "question": payload.message,
        "answer": answer,
        "model": model,
        "usage": usage,
        "request_tokens": prompt_tokens,
        "response_tokens": response_tokens,
        "context": {
            **{
                key: built[key]
                for key in (
                    "layers",
                    "short_window",
                    "total_tokens",
                    "retrieved",
                    "system_prompt",
                    "messages",
                )
            },
            "request_tokens": prompt_tokens,
            "response_tokens": response_tokens,
            "usage": usage,
        },
        "state": store.state(owner_id, session_id),
    }


@app.post("/api/chat/reset")
async def reset_chat(payload: SessionRequest) -> dict:
    removed = store.reset_session(payload.owner_id, payload.session_id)
    return {
        "removed": removed,
        "state": store.state(payload.owner_id, payload.session_id),
    }


@app.delete("/api/short-term")
async def clear_short(
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
    session_id: str = Query(default=DEFAULT_SESSION_ID, max_length=80),
) -> dict:
    owner_id = _owner(owner_id)
    session_id = _session(session_id)
    removed = store.clear_short(owner_id, session_id)
    return {"removed": removed, "state": store.state(owner_id, session_id)}


@app.post("/api/working")
async def save_working(payload: WorkingRequest) -> dict:
    working = store.set_working(
        payload.owner_id,
        payload.session_id,
        payload.model_dump(include=set(("title", "goal", "status", "next_step", "constraints"))),
    )
    return {
        "working": working,
        "state": store.state(payload.owner_id, payload.session_id),
    }


@app.delete("/api/working")
async def clear_working(
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
    session_id: str = Query(default=DEFAULT_SESSION_ID, max_length=80),
) -> dict:
    owner_id = _owner(owner_id)
    session_id = _session(session_id)
    removed = store.clear_working(owner_id, session_id)
    return {"removed": removed, "state": store.state(owner_id, session_id)}


@app.post("/api/long-term")
async def remember(payload: LongTermRequest) -> dict:
    try:
        item = store.upsert_long(
            payload.owner_id,
            payload.section,
            payload.key,
            payload.value,
            payload.source,
            confidence=payload.confidence,
            importance=payload.importance,
            ttl_hours=payload.ttl_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"item": item, "state": store.state(payload.owner_id)}


@app.delete("/api/long-term/{item_id}")
async def forget(
    item_id: int,
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
) -> dict:
    owner_id = _owner(owner_id)
    if not store.delete_long(owner_id, item_id):
        raise HTTPException(status_code=404, detail="Запись памяти не найдена")
    return {"deleted": item_id, "state": store.state(owner_id)}


@app.get("/api/sections")
async def sections() -> dict:
    return {
        "sections": [
            {"id": section, "label": label}
            for section, label in (
                ("profile", "Профиль"),
                ("decisions", "Решения"),
                ("knowledge", "Знания"),
            )
            if section in LONG_SECTIONS
        ]
    }
