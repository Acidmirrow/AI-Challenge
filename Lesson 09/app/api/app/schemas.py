from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str = "ok"
    demo_messages: int = 0
    demo_summaries: int = 0


class DemoMessage(BaseModel):
    id: int
    role: str
    content: str
    tokens: int


class SummaryItem(BaseModel):
    id: int
    from_id: int
    to_id: int
    content: str
    tokens: int


class DemoOut(BaseModel):
    title: str
    description: str = ""
    messages: list[DemoMessage]
    summaries: list[SummaryItem] = Field(default_factory=list)


class ContextRequest(BaseModel):
    messages: list[DemoMessage] = Field(default_factory=list, max_length=200)
    summaries: list[SummaryItem] = Field(default_factory=list, max_length=200)
    use_summaries: bool = False
    strategy: Literal["budget", "last", "full"] = "budget"
    max_messages: int = Field(default=12, ge=1, le=100)
    max_tokens: int = Field(default=4_000, ge=256, le=100_000)
    reserve_tokens: int = Field(default=500, ge=0, le=50_000)
    system_tokens: int = Field(default=20, ge=0, le=10_000)


class AskRequest(ContextRequest):
    question: str = Field(min_length=1, max_length=1_000)


class ContextOut(BaseModel):
    strategy: str
    strategy_label: str
    available: int
    message_budget: int
    system_tokens: int
    included_ids: list[int] = Field(default_factory=list)
    dropped_ids: list[int] = Field(default_factory=list)
    included_tokens: int = 0
    context_tokens: int = 0
    dropped_tokens: int = 0
    overflow: int = 0
    fits: bool = True
    compressed: bool = False
    summary_count: int = 0
    message_tokens: dict[int, int] = Field(default_factory=dict)


class AskOut(ContextOut):
    question: str
    answer: str
    found: bool = False
    source_ids: list[int] = Field(default_factory=list)
    mode: str = "history-retrieval"


class CompressBucket(BaseModel):
    kind: str
    messages: int = 0
    summaries: int = 0
    tokens: int = 0
    fits: bool = True
    overflow: int = 0


class CompressRequest(BaseModel):
    messages: list[DemoMessage] = Field(default_factory=list, max_length=200)
    summaries: list[SummaryItem] = Field(default_factory=list, max_length=200)
    max_tokens: int = Field(default=4_000, ge=256, le=100_000)
    reserve_tokens: int = Field(default=500, ge=0, le=50_000)
    system_tokens: int = Field(default=20, ge=0, le=10_000)


class CompressOut(BaseModel):
    before: CompressBucket
    after: CompressBucket
    saved_tokens: int
    saved_percent: float
