from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModelOut(BaseModel):
    id: str
    label: str
    context_window: int
    output_max: int
    description: str = ""
    tier: str = "medium"
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0


class HealthOut(BaseModel):
    status: str = "ok"
    tokenizer: str = "regex-estimate"
    models: int = 0


class TokenPreview(BaseModel):
    index: int
    text: str


class AnalyzeRequest(BaseModel):
    text: str = Field(default="", max_length=200_000)
    model: str = Field(default="deepseek-flash", min_length=1, max_length=64)
    output_reserve: int = Field(default=1_000, ge=0, le=100_000)


class AnalyzeOut(BaseModel):
    model: str
    label: str
    context_window: int
    output_max: int
    output_reserve: int
    available: int
    chars: int
    words: int
    tokens: int
    tokens_per_word: float
    chars_per_token: float
    fits: bool
    copies: int
    overflow: int
    kept_tokens: int = 0
    dropped_tokens: int = 0
    full_input_cost: float = 0.0
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    currency: str = "USD"
    preview: list[TokenPreview] = Field(default_factory=list)
    preview_truncated: bool = False
    truncated_text: str = ""
    truncated_tokens: int = 0


class CompareRequest(BaseModel):
    base_text: str = Field(default="", max_length=20_000)
    model: str = Field(default="deepseek-flash", min_length=1, max_length=64)
    output_reserve: int = Field(default=1_000, ge=0, le=100_000)
    #: демонстрационное окно, чтобы не генерировать мегабайты текста
    demo_window: int = Field(default=8_000, ge=512, le=100_000)


class ContextMetrics(BaseModel):
    kind: str
    label: str
    chars: int
    words: int
    tokens: int
    tokens_per_word: float
    input_cost: float
    output_cost: float
    total_cost: float
    fits: bool
    copies: int
    overflow: int
    kept_tokens: int = 0
    dropped_tokens: int = 0
    truncated_tokens: int


class CompareOut(BaseModel):
    model: str
    label: str
    context_window: int
    demo_window: int
    output_reserve: int
    available: int
    contexts: list[ContextMetrics]
    dependencies: list[str]


class DialogueRequest(BaseModel):
    model: str = Field(default="deepseek-flash", min_length=1, max_length=64)
    turns: int = Field(default=8, ge=1, le=50)
    user_tokens: int = Field(default=20, ge=1, le=10_000)
    assistant_tokens: int = Field(default=80, ge=1, le=10_000)
    system_tokens: int = Field(default=20, ge=0, le=10_000)
    demo_window: int = Field(default=8_000, ge=512, le=100_000)


class DialogueTurn(BaseModel):
    turn: int
    history_tokens: int
    prompt_tokens: int
    completion_tokens: int
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_cost: float = 0.0
    cumulative_cost: float = 0.0
    fits: bool
    overflow: int = 0


class DialogueOut(BaseModel):
    model: str
    label: str
    context_window: int
    demo_window: int
    turns: list[DialogueTurn]
    total_cost: float = 0.0
    total_tokens: int = 0
    first_overflow_turn: int | None = None
    first_overflow_tokens: int = 0
    risks: list[str] = Field(default_factory=list)


class TruncateRequest(BaseModel):
    text: str = Field(default="", max_length=200_000)
    max_tokens: int = Field(default=1_000, ge=1, le=200_000)


class TruncateOut(BaseModel):
    text: str
    tokens: int
    chars: int
    original_tokens: int
    dropped_tokens: int


class PresetOut(BaseModel):
    id: str
    label: str
    text: str


class PresetsOut(BaseModel):
    presets: list[PresetOut]


class AnyOut(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
