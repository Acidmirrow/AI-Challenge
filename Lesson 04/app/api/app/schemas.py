"""Схемы запросов и ответов урока 04: чат и сравнение температур."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

#: температура в пределах, которые принимает OpenAI-совместимый API
Temperature = Annotated[float, Field(ge=0.0, le=2.0)]


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(max_length=20_000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[Message] = Field(min_length=1, max_length=60)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_000, ge=16, le=10_000)


class HealthOut(BaseModel):
    status: str
    provider: str
    detail: str = ""
    tasks: int = 0
    config_files: list[str] = []


class ModelOut(BaseModel):
    id: str
    label: str
    supports_reasoning: bool = False
    supports_temperature: bool = True
    reasoning_levels: list[str] = []
    description: str = ""
    provider: str = "mock"


class VariantOut(BaseModel):
    id: str
    complexity: str
    text: str
    reference: str = ""
    note: str = ""


class TaskOut(BaseModel):
    id: str
    label: str
    kind: str
    variants: list[VariantOut] = []


class TemperatureRun(BaseModel):
    temperature: float
    #: номер повторения при той же температуре: 0 — первый прогон
    repeat: int = 0
    answer: str = ""
    reasoning: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False
    error: str | None = None


class CompareTemperaturesRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    task: str = Field(default="", max_length=32)
    temperatures: list[Temperature] = Field(
        default_factory=lambda: [0.0, 0.7, 1.2], min_length=1, max_length=5
    )
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_000, ge=16, le=10_000)
    #: сколько раз повторить каждый запрос сверх первого (0…10)
    repeats: int = Field(default=0, ge=0, le=10)


class AnalyzeRequest(BaseModel):
    """Анализ ответов, полученных при разных температурах."""

    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    task: str = Field(default="", max_length=32)
    variant: str = Field(default="", max_length=64)
    reference: str = Field(default="", max_length=500)
    #: до 5 температур × (1 + 10 повторов)
    runs: list[dict[str, Any]] = Field(min_length=1, max_length=60)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)


class AnalyzeOut(BaseModel):
    model: str
    text: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False


class CompareTemperaturesOut(BaseModel):
    model: str
    prompt: str
    task: str = ""
    runs: list[TemperatureRun] = []
    #: насколько ответы разошлись: уникальные ответы, разброс длины
    spread: dict[str, Any] = {}
