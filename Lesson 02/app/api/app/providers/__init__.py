from __future__ import annotations

from ..config import Settings
from .base import Provider, ProviderError, ProviderRequest, StreamEvent
from .mock_provider import MockProvider
from .openai_provider import OpenAIProvider

__all__ = ["Provider", "ProviderError", "ProviderRequest", "StreamEvent", "build_provider"]


#: Провайдеры с OpenAI-совместимым API (gemini/openrouter — бесплатные тарифы)
OPENAI_COMPATIBLE = ("openai", "deepseek", "gemini", "openrouter", "nous")


def build_provider(settings: Settings, name: str | None = None) -> Provider:
    """Провайдер по имени модели: нужен только его ключ, основной профиль не помеха."""
    provider = name or settings.provider
    if provider == "mock":
        return MockProvider()
    if provider in OPENAI_COMPATIBLE:
        api_key, _ = settings.credentials(provider)
        if not api_key:
            raise ProviderError(
                f"Провайдер {provider!r} не настроен: нет ключа `{provider}.api.key` "
                "в config/secrets.properties.",
                kind="not_configured",
                status=503,
            )
        return OpenAIProvider(settings, provider)
    raise ProviderError(f"Неизвестный провайдер {provider!r}.", kind="config", status=500)
