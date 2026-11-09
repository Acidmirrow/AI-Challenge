"""Схемы API урока 06: запуск агента, трасса шагов и каталог инструментов."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    provider: str
    detail: str = ""
    tools: int = 0
    config_files: list[str] = []


class ModelOut(BaseModel):
    id: str
    label: str
    supports_reasoning: bool = False
    supports_temperature: bool = True
    reasoning_levels: list[str] = []
    description: str = ""
    provider: str = "mock"
    tier: str = "medium"


class ToolOut(BaseModel):
    name: str
    label: str
    description: str
    parameters: dict[str, Any] = {}


class AgentRequest(BaseModel):
    """Задача агенту: промпт, модель и лимит шагов."""

    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)
    max_steps: int = Field(default=10, ge=1, le=10)
    #: какие инструменты разрешены; None — все, [] — ни одного
    tools: list[str] | None = Field(default=None, max_length=10)


class AgentStep(BaseModel):
    """Один вызов инструмента: что вызвали, с чем и что получили."""

    index: int
    tool: str
    label: str = ""
    arguments: dict[str, Any] = {}
    result: dict[str, Any] = {}
    elapsed_ms: int = 0


class AgentOut(BaseModel):
    model: str
    label: str = ""
    provider: str = "mock"
    answer: str = ""
    steps: list[AgentStep] = []
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False
    #: final — модель ответила сама, max_steps — сработал лимит, empty — пустой ответ
    stopped_reason: str = "final"
    #: инструменты, которые были выбраны для этого запуска
    tools: list[str] = []
    #: каких инструментов не хватило (при stopped_reason=missing_tool)
    missing_tools: list[str] = []
    cost_usd: float = 0.0
    cost_note: str = ""
