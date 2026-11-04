from __future__ import annotations

from ..config import Settings
from .base import Provider, ProviderError, ProviderRequest, StreamEvent
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

__all__ = ["Provider", "ProviderError", "ProviderRequest", "StreamEvent", "build_provider"]


def build_provider(settings: Settings, name: str | None = None) -> Provider:
    """Провайдер по имени: mock всегда, openai/deepseek — только настроенный профиль."""
    provider = name or settings.provider
    if provider == "mock":
        return MockProvider()
    if provider in ("openai", "deepseek"):
        if provider != settings.provider:
            raise ProviderError(
                f"Профиль {provider!r} не настроен: в app.properties указан provider={settings.provider}.",
                kind="config",
                status=503,
            )
        return OpenAIProvider(settings)
    raise ProviderError(f"Неизвестный провайдер {provider!r}.", kind="config", status=500)
