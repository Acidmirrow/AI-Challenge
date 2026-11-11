from __future__ import annotations

from dataclasses import dataclass

from .schemas import ModelOut


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    context_window: int
    output_max: int
    description: str
    tier: str = "medium"
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    def as_out(self) -> ModelOut:
        return ModelOut(
            id=self.id,
            label=self.label,
            context_window=self.context_window,
            output_max=self.output_max,
            description=self.description,
            tier=self.tier,
            input_price_per_1m=self.input_price_per_1m,
            output_price_per_1m=self.output_price_per_1m,
        )


MODELS: tuple[ModelInfo, ...] = (
    ModelInfo(
        id="deepseek-flash",
        label="DeepSeek V4.1 Flash",
        context_window=1_000_000,
        output_max=10_000,
        description="Быстрая модель DeepSeek, контекст 1M токенов",
        tier="small",
        input_price_per_1m=0.28,
        output_price_per_1m=0.42,
    ),
    ModelInfo(
        id="deepseek-v4-pro",
        label="DeepSeek V4 Pro",
        context_window=1_000_000,
        output_max=10_000,
        description="Старшая модель DeepSeek, контекст 1M токенов",
        tier="large",
        input_price_per_1m=0.28,
        output_price_per_1m=1.10,
    ),
    ModelInfo(
        id="mock-fast",
        label="Демо (mock)",
        context_window=32_000,
        output_max=4_000,
        description="Офлайн-модель для примеров без ключа",
        tier="small",
        input_price_per_1m=0.0,
        output_price_per_1m=0.0,
    ),
)

BY_ID = {model.id: model for model in MODELS}
DEFAULT_MODEL = "deepseek-flash"
