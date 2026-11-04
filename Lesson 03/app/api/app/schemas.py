from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(default="", max_length=20_000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[Message] = Field(min_length=1, max_length=50)
    strategy: str = Field(default="direct", min_length=1, max_length=32)

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    reasoning: str = Field(default="none", max_length=16)
    max_tokens: int | None = Field(default=1_024, ge=16, le=10_000)

    @field_validator("messages")
    @classmethod
    def _has_user_message(cls, value: list[Message]) -> list[Message]:
        if not any(item.role == "user" for item in value):
            raise ValueError("нужно хотя бы одно сообщение пользователя")
        return value


class CompareRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    strategies: list[str] | None = Field(default=None, max_length=10)

    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="none", max_length=16)
    max_tokens: int | None = Field(default=1_024, ge=16, le=10_000)


class StrategyOut(BaseModel):
    id: str
    label: str
    description: str
    system_prompt: str
    shows_reasoning: bool
    reasoning_hint: str
    notes: list[str] = []


class ModelOut(BaseModel):
    id: str
    label: str
    supports_reasoning: bool
    supports_temperature: bool
    supports_json_schema: bool = True
    reasoning_levels: list[str] = []
    description: str = ""
    provider: str = "mock"


class HealthOut(BaseModel):
    status: str
    provider: str
    detail: str = ""
    strategies: int = 0
    config_files: list[str] = []


class SolverOut(BaseModel):
    id: str
    label: str
    role: str
    strategy: str
    reasoning: str
    temperature: float


class ReviewerOut(BaseModel):
    id: str
    label: str
    role: str
    reasoning: str
    temperature: float


class CouncilOut(BaseModel):
    solvers: list[SolverOut]
    reviewers: list[ReviewerOut]


class AnswerRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    expert: str = Field(min_length=1, max_length=32)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)


class AnswerOut(BaseModel):
    expert: str
    label: str
    strategy: str
    answer: str = ""
    reasoning: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False


class ReviewRequest(BaseModel):
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    reviewer: str = Field(min_length=1, max_length=32)
    answers: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)


class ReviewOut(BaseModel):
    reviewer: str
    label: str
    verdicts: list[dict[str, Any]] = []
    final_answer: str = ""
    parsed: bool = False
    raw_text: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0


class CompareItem(BaseModel):
    strategy: str
    answer: str = ""
    reasoning: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False
    error: str | None = None
