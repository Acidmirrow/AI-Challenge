from __future__ import annotations

from ..config import Settings
from .base import Provider, ProviderError, ProviderRequest, StreamEvent
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

__all__ = [
    "Provider",
    "ProviderError",
    "ProviderRequest",
    "StreamEvent",
    "build_provider",
]


def build_provider(settings: Settings, name: str | None = None) -> Provider:
    """Build the provider for ``name`` (defaults to the configured one).

    ``mock`` is always available — that is what lets the UI switch between the
    offline demo and the real API from a single deployment.
    """
    name = name or settings.provider
    if name == "mock":
        return MockProvider()
    if name in ("openai", "deepseek"):
        if name != settings.provider:
            raise ProviderError(
                f"Профиль {name!r} не настроен: в .env указан PROVIDER={settings.provider}.",
                kind="config",
                status=503,
            )
        return OpenAIProvider(settings)
    raise ProviderError(
        f"Неизвестный провайдер {name!r}. Допустимо: mock, openai, deepseek.",
        kind="config",
        status=500,
    )
