"""Request-shaping tests for the OpenAI-compatible provider (no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from app.providers import ProviderError, build_provider
from app.providers.base import ProviderRequest
from app.providers.openai_provider import OpenAIProvider


def settings(**overrides) -> Settings:
    base = {
        "provider": "openai",
        "openai_api_key": "sk-test",
        "openai_base_url": "https://example.test/v1",
        # изолируемся от config/app.properties: там max.tokens.param=max_tokens
        "max_tokens_param": "",
    }
    return Settings(**{**base, **overrides})


def request(**overrides) -> ProviderRequest:
    base = dict(
        messages=[{"role": "user", "content": "hi"}],
        model="gpt-5",
        temperature=0.7,
        reasoning="high",
        max_tokens=512,
        supports_reasoning=True,
        supports_temperature=False,
    )
    return ProviderRequest(**{**base, **overrides})


def test_reasoning_model_omits_temperature_and_sets_effort() -> None:
    kwargs = OpenAIProvider(settings())._kwargs(request())
    assert kwargs["reasoning_effort"] == "high"
    assert "temperature" not in kwargs  # gpt-5 / o-series reject temperature != 1
    assert kwargs["max_completion_tokens"] == 512
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}


def test_chat_model_keeps_temperature_and_has_no_effort() -> None:
    kwargs = OpenAIProvider(settings())._kwargs(
        request(model="gpt-4.1", reasoning="off", supports_reasoning=False, supports_temperature=True)
    )
    assert kwargs["temperature"] == pytest.approx(0.7)
    assert kwargs["max_tokens"] == 512
    assert "reasoning_effort" not in kwargs


def test_reasoning_param_can_be_disabled_for_strict_gateways() -> None:
    kwargs = OpenAIProvider(settings(reasoning_param=""))._kwargs(request())
    assert "reasoning_effort" not in kwargs


def test_explicit_max_tokens_param_wins() -> None:
    kwargs = OpenAIProvider(settings(max_tokens_param="max_tokens"))._kwargs(request())
    assert kwargs["max_tokens"] == 512
    assert "max_completion_tokens" not in kwargs


def test_missing_api_key_is_a_configuration_error() -> None:
    with pytest.raises(ProviderError) as exc:
        build_provider(settings(openai_api_key=""))
    assert exc.value.kind == "not_configured"
    assert exc.value.status == 503


def test_unknown_provider_rejected() -> None:
    with pytest.raises(ProviderError):
        build_provider(settings(provider="nope"))


def test_degraded_health_and_503_when_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        assert client.get("/api/health").json()["status"] == "degraded"
        response = client.post(
            "/api/chat",
            json={"model": "gpt-5", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert response.status_code == 503
        assert "openai.api.key" in response.json()["detail"]
    finally:
        get_settings.cache_clear()
