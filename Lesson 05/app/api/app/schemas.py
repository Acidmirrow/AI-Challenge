"""Схемы запросов и ответов урока 05: чат, сравнение моделей, анализ сравнения."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field, model_validator

#: температура в пределах, которые принимает OpenAI-совместимый API
Temperature = Annotated[float, Field(ge=0.0, le=2.0)]

#: размеры моделей, между которыми сравниваем
Tier = Annotated[str, Field(pattern="^(small|medium|large)$")]


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
    #: small | medium | large — группа размера для выбора трёх моделей
    tier: str = "medium"


class TaskOut(BaseModel):
    id: str
    title: str
    complexity: str
    text: str
    reference: str = ""


class CompareRequest(BaseModel):
    """Один промпт на несколько моделей: они отвечают параллельно."""

    prompt: str = Field(min_length=1, max_length=8_000)
    models: list[str] = Field(min_length=2, max_length=3)
    task: str = Field(default="", max_length=32)
    complexity: str = Field(default="", max_length=32)
    reference: str = Field(default="", max_length=500)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_000, ge=16, le=10_000)

    @model_validator(mode="after")
    def _distinct_models(self) -> "CompareRequest":
        if len(set(self.models)) != len(self.models):
            raise ValueError("Модели для сравнения должны быть разными")
        return self


class CompareRun(BaseModel):
    model: str
    label: str = ""
    provider: str = "mock"
    tier: str = "medium"
    answer: str = ""
    reasoning: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False
    #: прайс за 1 млн токенов и посчитанная стоимость прогона
    price_in: float = 0.0
    price_out: float = 0.0
    cost_usd: float = 0.0
    cost_note: str = ""
    error: str | None = None


class CompareOut(BaseModel):
    prompt: str
    task: str = ""
    complexity: str = ""
    reference: str = ""
    runs: list[CompareRun] = []
    #: суммарные метрики по всем моделям
    totals: dict[str, Any] = {}


class AnalyzeRequest(BaseModel):
    """Анализ сравнения продвинутой моделью."""

    model: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=8_000)
    task: str = Field(default="", max_length=32)
    complexity: str = Field(default="", max_length=32)
    reference: str = Field(default="", max_length=500)
    #: по одному элементу на модель: model/label/answer/elapsed_ms/usage/cost_usd
    runs: list[dict[str, Any]] = Field(min_length=1, max_length=3)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)


class AnalyzeOut(BaseModel):
    model: str
    text: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False


class BenchmarkRequest(BaseModel):
    """Один набор задач на несколько моделей: считаем верные ответы и цену."""

    models: list[str] = Field(min_length=2, max_length=3)
    #: пусто — все пять задач
    tasks: list[str] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=800, ge=16, le=10_000)
    #: модель-судья: сверяет ответы с эталоном (пусто — только числа эталона)
    judge: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _distinct_models(self) -> "BenchmarkRequest":
        if len(set(self.models)) != len(self.models):
            raise ValueError("Модели для сравнения должны быть разными")
        return self


class BenchmarkRun(BaseModel):
    """Один прогон: задача × модель."""

    task: str
    task_title: str = ""
    complexity: str = ""
    reference: str = ""
    model: str
    label: str = ""
    provider: str = "mock"
    tier: str = "medium"
    answer: str = ""
    correct: bool = False
    elapsed_ms: int = 0
    usage: dict[str, Any] = {}
    finish_reason: str | None = None
    truncated: bool = False
    cost_usd: float = 0.0
    error: str | None = None


class BenchmarkModel(BaseModel):
    """Сводка по одной модели: верные ответы, время, токены, стоимость."""

    model: str
    label: str = ""
    provider: str = "mock"
    tier: str = "medium"
    correct: int = 0
    total: int = 0
    accuracy: float = 0.0
    elapsed_ms: int = 0
    avg_elapsed_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    errors: int = 0


class BenchmarkOut(BaseModel):
    task_ids: list[str] = []
    runs: list[BenchmarkRun] = []
    models: list[BenchmarkModel] = []
    #: маленькая vs большая модель: разница в точности и во сколько раз дороже
    comparison: dict[str, Any] = {}
    totals: dict[str, Any] = {}


class BenchmarkAnalyzeRequest(BaseModel):
    """Вывод по бенчмарку: где маленькой модели достаточно."""

    model: str = Field(min_length=1, max_length=128)
    summary: list[dict[str, Any]] = Field(min_length=1, max_length=3)
    #: по задаче: task/title/reference и ответы моделей с флагом correct
    tasks: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    comparison: dict[str, Any] = {}
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)


class BenchmarkAnalyzeOut(BaseModel):
    model: str
    text: str = ""
    usage: dict[str, Any] = {}
    elapsed_ms: int = 0
    finish_reason: str | None = None
    truncated: bool = False
