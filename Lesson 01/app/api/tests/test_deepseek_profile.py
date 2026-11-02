"""DeepSeek profile: catalog, key/base-url resolution, reasoning-level rules."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.main import _resolve_reasoning
from app.models_catalog import ModelInfo, build_catalog


def test_deepseek_catalog_exposes_v4_models() -> None:
    catalog = build_catalog(Settings(provider="deepseek"))
    ids = [m.id for m in catalog.all()]
    assert ids == ["deepseek-flash", "deepseek-v4-pro"]

    flash = catalog.get("deepseek-flash")
    assert flash is not None
    assert flash.supports_reasoning is True
    assert flash.supports_temperature is True
    assert "none" in flash.reasoning_levels and "max" in flash.reasoning_levels


def test_deepseek_profile_resolves_its_own_key_and_host() -> None:
    settings = Settings(
        provider="deepseek",
        deepseek_api_key="sk-deepseek",
        deepseek_base_url="https://api.deepseek.com/v1",
        openai_api_key="sk-openai",
        openai_base_url="https://api.openai.com/v1",
    )
    assert settings.api_key == "sk-deepseek"
    assert settings.base_url == "https://api.deepseek.com/v1"
    assert "deepseek" in settings.provider_label


def test_openai_profile_still_uses_openai_settings() -> None:
    settings = Settings(
        provider="openai",
        deepseek_api_key="sk-deepseek",
        openai_api_key="sk-openai",
        openai_base_url="https://api.openai.com/v1",
    )
    assert settings.api_key == "sk-openai"
    assert settings.base_url == "https://api.openai.com/v1"


DEEPSEEK_LEVELS = ["none", "minimal", "low", "medium", "high", "xhigh", "ultra", "max"]


@pytest.mark.parametrize("level", DEEPSEEK_LEVELS)
def test_deepseek_accepts_every_advertised_level(level: str) -> None:
    model = build_catalog(Settings(provider="deepseek")).get("deepseek-flash")
    assert model is not None
    assert _resolve_reasoning(model, level) == level


def test_unadvertised_level_is_rejected() -> None:
    model = ModelInfo("gpt-5", "GPT-5", ("low", "medium", "high"))
    with pytest.raises(HTTPException) as exc:
        _resolve_reasoning(model, "max")
    assert exc.value.status_code == 400
    assert "low, medium, high" in exc.value.detail


def test_model_without_reasoning_is_downgraded_to_off() -> None:
    model = ModelInfo("gpt-4.1", "GPT-4.1")
    assert _resolve_reasoning(model, "high") == "off"
    assert _resolve_reasoning(model, "off") == "off"
