from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings


@dataclass(frozen=True)
class ModelInfo:
    """One selectable model and what it actually supports."""

    id: str
    label: str
    supports_reasoning: bool = False
    supports_temperature: bool = True
    description: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --- built-in catalogs -------------------------------------------------------
# supports_temperature=False: GPT-5 / o-series style models reject any
# temperature other than 1, so the API silently omits the parameter.

MOCK_MODELS = [
    ModelInfo("mock-fast", "Mock · fast", supports_reasoning=False, description="Offline echo model"),
    ModelInfo("mock-reasoner", "Mock · reasoner", supports_reasoning=True, description="Offline model with fake reasoning"),
]

OPENAI_MODELS = [
    ModelInfo("gpt-5", "GPT-5", supports_reasoning=True, supports_temperature=False,
              description="Reasoning model, effort low/medium/high"),
    ModelInfo("gpt-5-mini", "GPT-5 mini", supports_reasoning=True, supports_temperature=False,
              description="Cheaper reasoning model"),
    ModelInfo("o4-mini", "o4-mini", supports_reasoning=True, supports_temperature=False,
              description="Fast reasoning model"),
    ModelInfo("gpt-4.1", "GPT-4.1", supports_reasoning=False,
              description="General purpose, temperature available"),
    ModelInfo("gpt-4.1-mini", "GPT-4.1 mini", supports_reasoning=False,
              description="Small general purpose model"),
]


def _builtin(provider: str) -> list[ModelInfo]:
    return MOCK_MODELS if provider == "mock" else OPENAI_MODELS


def _from_file(path: str) -> list[ModelInfo]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("models json must be a list of objects")
    return [
        ModelInfo(
            id=item["id"],
            label=item.get("label", item["id"]),
            supports_reasoning=bool(item.get("supports_reasoning", False)),
            supports_temperature=bool(item.get("supports_temperature", True)),
            description=item.get("description", ""),
        )
        for item in raw
    ]


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
    return Catalog(_builtin(settings.provider))
