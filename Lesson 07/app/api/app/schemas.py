"""Схемы API урока 07: сессии, сообщения и окно контекста."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    provider: str
    detail: str = ""
    storage: str = ""
    sessions: int = 0
    max_context_messages: int = 20
    max_context_chars: int = 20_000
    tools: int = 0
    config_files: list[str] = Field(default_factory=list)


class ModelOut(BaseModel):
    id: str
    label: str
    supports_reasoning: bool = False
    supports_temperature: bool = True
    reasoning_levels: list[str] = Field(default_factory=list)
    description: str = ""
    provider: str = "mock"
    tier: str = "medium"


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tokens: int = 0
    created_at: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""


class SessionOut(BaseModel):
    id: str
    number: int = 0
    title: str = ""
    created_at: str
    updated_at: str
    message_count: int = 0


class SessionDetailOut(SessionOut):
    messages: list[MessageOut] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Один ход диалога; session_id связывает его с сохранённой историей."""

    session_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$",
    )
    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=800, ge=16, le=10_000)
    #: сколько последних сообщений истории максимум отправить в модель
    max_messages: int = Field(default=20, ge=2, le=500)
    #: какие инструменты разрешены; None — все, [] — ни одного
    tools: list[str] | None = Field(default=None, max_length=20)
    max_steps: int = Field(default=10, ge=1, le=10)
    #: сохранённые диалоги, которые нужно подмешать в контекст
    context_sessions: list[str] = Field(default_factory=list, max_length=20)


class ContextOut(BaseModel):
    included_messages: int
    dropped_messages: int
    chars: int
    max_messages: int
    max_chars: int
    past_sessions: int = 0


class AgentStep(BaseModel):
    index: int
    tool: str
    label: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0


class ChatOut(BaseModel):
    answer: str = ""
    session_id: str
    model: str
    label: str = ""
    provider: str = "mock"
    messages: list[MessageOut] = Field(default_factory=list)
    context: ContextOut
    steps: list[AgentStep] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    context_sessions: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int = 0
    finish_reason: str | None = None
    stopped_reason: str = "final"
    total_messages: int = 0
