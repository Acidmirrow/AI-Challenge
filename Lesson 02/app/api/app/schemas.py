from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class FormatRunRequest(BaseModel):
    format: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)

    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    schema_name: str = Field(default="response", max_length=64)
    tool_name: str = Field(default="save_result", max_length=64)

    temperature: float | None = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1024, ge=16, le=10_000)

    # Явное описание формата ответа: заменяет встроенную подсказку формата.
    system_prompt: str | None = Field(default=None, max_length=4_000)
    # Stop sequences: генерация обрывается на первой из них.
    stop: list[str] | None = Field(default=None, max_length=4)

    @field_validator("stop")
    @classmethod
    def _check_stop(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        # strip only spaces/tabs: "\n\n" is a meaningful stop sequence
        cleaned = [item for item in (s.strip(" \t") for s in value) if item]
        if any(len(item) > 32 for item in cleaned):
            raise ValueError("stop-последовательность длиннее 32 символов")
        return cleaned or None

    model_config = {"populate_by_name": True}

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        from .formats import FORMATS_BY_ID

        if value not in FORMATS_BY_ID:
            raise ValueError(f"Неизвестный формат {value!r}")
        return value


class FormatOut(BaseModel):
    id: str
    label: str
    description: str
    needs_schema: bool
    uses_tools: bool
    default_instruction: str = ""


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
    formats: int = 0
    config_files: list[str] = []
