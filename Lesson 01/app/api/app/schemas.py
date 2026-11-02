from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MessageRole = Literal["system", "user", "assistant"]

# "off" = don`t send the parameter at all. Concrete levels are validated per model
# against the catalog (DeepSeek exposes none…max, OpenAI low/medium/high).
ReasoningLevel = str


class Message(BaseModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=32_000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=0.7, ge=0.0, le=2.0)
    reasoning: ReasoningLevel = Field(default="off", max_length=16)
    web_search: bool = False
    max_tokens: int | None = Field(default=1024, ge=16, le=32_768)

    @field_validator("messages")
    @classmethod
    def _last_is_user(cls, value: list[Message]) -> list[Message]:
        if value[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return value


class ModelOut(BaseModel):
    id: str
    label: str
    supports_reasoning: bool
    supports_temperature: bool
    reasoning_levels: list[str] = []
    description: str = ""


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    provider: str
    detail: str = ""
    web_search: str = "off"
