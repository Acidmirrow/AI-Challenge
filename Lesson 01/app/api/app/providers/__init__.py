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


def build_provider(settings: Settings) -> Provider:
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider in ("openai", "deepseek"):
        return OpenAIProvider(settings)
    raise ProviderError(
        f"Неизвестный PROVIDER={settings.provider!r}. Допустимо: mock, openai, deepseek.",
        kind="config",
        status=500,
    )
