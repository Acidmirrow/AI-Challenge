"""API урока 12: персонализация ассистента."""

from __future__ import annotations

import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .check import answer_all, answer_batch, analyze_results, generate_question
from .context import build_context
from .llm import chat_with_usage as model_chat
from .profile import (
    DEFAULT_OWNER,
    DEFAULT_SESSION_ID,
    DEFAULT_DB_PATH,
    PREFERENCE_KEYS,
    PROFILE_FIELDS,
    ProfileStore,
)

TITLE = "Персонализация ассистента"
DB_PATH = os.getenv("PROFILE_DB_PATH", DEFAULT_DB_PATH)
store = ProfileStore(DB_PATH)
store.ensure_test_profiles()

app = FastAPI(
    title="Assistant Personalization Lab",
    version="1.0.0",
    description="Урок 12: профиль, предпочтения и автообогащение из диалога.",
)


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


class OwnerRequest(BaseModel):
    owner_id: str = Field(default=DEFAULT_OWNER, min_length=1, max_length=80)


class ProfileRequest(OwnerRequest):
    name: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=200)
    language: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=200)


class PreferenceRequest(OwnerRequest):
    key: Literal["style", "format", "code_examples", "emoji", "constraints"]
    value: str = Field(min_length=1, max_length=500)
    source: str = Field(default="пользователь", max_length=80)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ChatRequest(OwnerRequest):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4_000)


class SessionRequest(OwnerRequest):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)


class ProfileCheckQuestionRequest(BaseModel):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)


class ProfileCheckAllRequest(BaseModel):
    question: str = Field(min_length=5, max_length=2_000)
    question_id: str = Field(default="", max_length=80)
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)


class ProfileCheckBatchRequest(BaseModel):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)
    count: int = Field(default=10, ge=1, le=10)


class ProfileCheckAnalyzeRequest(BaseModel):
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=80)
    items: list[dict] = Field(default_factory=list)


def _owner(owner_id: str | None) -> str:
    return (owner_id or DEFAULT_OWNER).strip()[:80] or DEFAULT_OWNER


def _session(session_id: str | None) -> str:
    return (session_id or DEFAULT_SESSION_ID).strip()[:80] or DEFAULT_SESSION_ID


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "lesson": 12,
        "title": TITLE,
        "profile_fields": list(PROFILE_FIELDS),
        "preference_keys": list(PREFERENCE_KEYS),
        "auto_enrichment": True,
    }


@app.get("/api/profile")
async def profile(owner_id: str = Query(default=DEFAULT_OWNER, max_length=80)):
    return store.get(_owner(owner_id))


@app.get("/api/profiles")
async def profiles() -> dict:
    return {"profiles": store.list_profiles()}


@app.delete("/api/profile")
async def delete_profile(owner_id: str = Query(default=DEFAULT_OWNER, max_length=80)) -> dict:
    return store.delete_profile(_owner(owner_id))


@app.post("/api/profile")
async def save_profile(payload: ProfileRequest) -> dict:
    try:
        state = store.save_profile(
            payload.owner_id,
            {
                "name": payload.name,
                "role": payload.role,
                "city": payload.city,
                "language": payload.language,
                "timezone": payload.timezone,
            },
            source="пользователь",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return state


@app.post("/api/preferences")
async def save_preference(payload: PreferenceRequest) -> dict:
    try:
        state = store.set_preference(
            payload.owner_id,
            payload.key,
            payload.value,
            source=payload.source,
            confidence=payload.confidence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return state


@app.delete("/api/preferences/{key}")
async def delete_preference(
    key: str,
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
) -> dict:
    if key not in PREFERENCE_KEYS:
        raise HTTPException(status_code=404, detail="Неизвестное предпочтение")
    return store.delete_preference(_owner(owner_id), key)


@app.get("/api/context")
async def context(
    owner_id: str = Query(default=DEFAULT_OWNER, max_length=80),
    session_id: str = Query(default=DEFAULT_SESSION_ID, max_length=80),
) -> dict:
    owner = _owner(owner_id)
    state = store.get(owner)
    messages = store.messages(owner, _session(session_id))
    return {
        **build_context(state, messages),
        "owner_id": owner,
        "session_id": _session(session_id),
    }


@app.post("/api/profile-check/question")
async def profile_check_question(payload: ProfileCheckQuestionRequest) -> dict:
    return generate_question(payload.session_id)


@app.post("/api/profile-check/all")
async def profile_check_all(payload: ProfileCheckAllRequest) -> dict:
    try:
        result = await run_in_threadpool(answer_all, store, payload.question, model_chat)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        **result,
        "question_id": payload.question_id,
        "session_id": payload.session_id,
    }


@app.post("/api/profile-check/batch")
async def profile_check_batch(payload: ProfileCheckBatchRequest) -> dict:
    try:
        result = await run_in_threadpool(
            answer_batch, store, payload.count, model_chat
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "session_id": payload.session_id}


@app.post("/api/profile-check/analyze")
async def profile_check_analyze(payload: ProfileCheckAnalyzeRequest) -> dict:
    if len(payload.items) > 10:
        raise HTTPException(status_code=422, detail="Для анализа передайте не более 10 ответов")
    try:
        result = await run_in_threadpool(analyze_results, payload.items, model_chat)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "session_id": payload.session_id}


@app.post("/api/chat/reset")
async def reset_chat(payload: SessionRequest) -> dict:
    removed = store.reset_messages(payload.owner_id, payload.session_id)
    return {
        "removed": removed,
        "state": store.get(payload.owner_id),
        "messages": store.messages(payload.owner_id, payload.session_id),
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    owner = _owner(payload.owner_id)
    session = _session(payload.session_id)

    # Сначала обновляем профиль из реплики, затем собираем контекст с новыми данными.
    updates = store.extract_updates(owner, payload.message)
    store.append_message(owner, session, "user", payload.message)
    state = store.get(owner)
    messages = store.messages(owner, session)
    built = build_context(state, messages)
    answer, model, usage = await run_in_threadpool(model_chat, built["messages"])
    store.append_message(owner, session, "assistant", answer)
    return {
        "answer": answer,
        "model": model,
        "usage": usage,
        "request_tokens": int(usage.get("prompt_tokens") or built["total_tokens"]),
        "response_tokens": int(usage.get("completion_tokens") or 0),
        "updates": updates,
        "profile": state,
        "context": built,
        "messages": store.messages(owner, session),
    }
