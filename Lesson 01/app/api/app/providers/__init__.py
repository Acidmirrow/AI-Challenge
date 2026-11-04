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


#: OpenAI-совместимые провайдеры; gemini/groq/openrouter — бесплатные тарифы
OPENAI_COMPATIBLE = ("openai", "deepseek", "gemini", "groq", "openrouter")


def build_provider(settings: Settings, name: str | None = None) -> Provider:
    """Провайдер по имени модели: нужен только его ключ, основной профиль не помеха."""
    name = name or settings.provider
    if name == "mock":
        return MockProvider()
    if name in OPENAI_COMPATIBLE:
        api_key, _ = settings.credentials(name)
        if not api_key:
            raise ProviderError(
                f"Провайдер {name!r} не настроен: нет ключа `{name}.api.key` "
                "в config/secrets.properties.",
                kind="not_configured",
                status=503,
            )
        return OpenAIProvider(settings, name)
    raise ProviderError(
        f"Неизвестный провайдер {name!r}. Допустимо: mock, openai, deepseek, gemini, groq, openrouter.",
        kind="config",
        status=500,
    )
