from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

# Levels accepted by OpenAI-style `reasoning_effort`. DeepSeek/Anthropic-compatible
# gateways may advertise more (none … max), so the catalog is the source of truth.
DEFAULT_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class ModelInfo:
    """One selectable model and what it actually supports."""

    id: str
    label: str
    reasoning_levels: tuple[str, ...] = ()
    supports_temperature: bool = True
    description: str = ""

    @property
    def supports_reasoning(self) -> bool:
        return bool(self.reasoning_levels)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "supports_reasoning": self.supports_reasoning,
            "supports_temperature": self.supports_temperature,
            "reasoning_levels": list(self.reasoning_levels),
            "description": self.description,
        }


# --- built-in catalogs -------------------------------------------------------
# supports_temperature=False: GPT-5 / o-series style models reject any
# temperature other than 1, so the API silently omits the parameter.

MOCK_MODELS = [
    ModelInfo("mock-fast", "Mock · fast", description="Офлайн-эхо без рассуждений"),
    ModelInfo("mock-reasoner", "Mock · reasoner", DEFAULT_LEVELS, description="Офлайн-модель с имитацией рассуждений"),
]

OPENAI_MODELS = [
    ModelInfo("gpt-5", "GPT-5", DEFAULT_LEVELS, supports_temperature=False,
              description="Reasoning-модель, effort low/medium/high"),
    ModelInfo("gpt-5-mini", "GPT-5 mini", DEFAULT_LEVELS, supports_temperature=False,
              description="Удешевлённая reasoning-модель"),
    ModelInfo("o4-mini", "o4-mini", DEFAULT_LEVELS, supports_temperature=False,
              description="Быстрая reasoning-модель"),
    ModelInfo("gpt-4.1", "GPT-4.1", description="Универсальная модель, temperature доступна"),
    ModelInfo("gpt-4.1-mini", "GPT-4.1 mini", description="Небольшая универсальная модель"),
]

# DeepSeek V4 accepts reasoning_effort: none | minimal | low | medium | high |
# xhigh | ultra | max (default high) and temperature 0…2; reasoning text comes
# back in `reasoning_content`, which the provider forwards as SSE `reasoning`.
DEEPSEEK_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max")

DEEPSEEK_MODELS = [
    ModelInfo("deepseek-flash", "DeepSeek V4.1 Flash", DEEPSEEK_LEVELS,
              description="Быстрая модель DeepSeek: контекст 1M, текст и изображения"),
    ModelInfo("deepseek-v4-pro", "DeepSeek V4 Pro", DEEPSEEK_LEVELS,
              description="Старшая модель DeepSeek: контекст 1M, только текст"),
]

CATALOGS = {
    "mock": MOCK_MODELS,
    "openai": OPENAI_MODELS,
    "deepseek": DEEPSEEK_MODELS,
}


def _from_file(path: str) -> list[ModelInfo]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("models json must be a list of objects")
    models = []
    for item in raw:
        levels = item.get("reasoning_levels")
        if levels is None:
            levels = DEFAULT_LEVELS if item.get("supports_reasoning") else ()
        models.append(
            ModelInfo(
                id=item["id"],
                label=item.get("label", item["id"]),
                reasoning_levels=tuple(levels),
                supports_temperature=bool(item.get("supports_temperature", True)),
                description=item.get("description", ""),
            )
        )
    return models


class Catalog:
    def __init__(self, models: list[ModelInfo]):
        self._models = {m.id: m for m in models}
        self._order = [m.id for m in models]

    def all(self) -> list[ModelInfo]:
        return [self._models[i] for i in self._order]

    def get(self, model_id: str) -> ModelInfo | None:
        return self._models.get(model_id)

    def extend(self, models: list[ModelInfo]) -> None:
        for model in models:
            if model.id not in self._models:
                self._models[model.id] = model
                self._order.append(model.id)


def build_catalog(settings: Settings) -> Catalog:
    if settings.models_json:
        return Catalog(_from_file(settings.models_json))
    return Catalog(CATALOGS.get(settings.provider, OPENAI_MODELS))
