"""Запасной список бесплатных моделей Groq: UI не должен оставаться без них."""

from __future__ import annotations

from app.models_catalog import GROQ_FALLBACK_MODELS, free_models_from


def test_groq_fallback_used_when_models_endpoint_is_empty() -> None:
    models = free_models_from("groq", [])
    assert [model.id for model in models] == list(GROQ_FALLBACK_MODELS)
    assert all(model.provider == "groq" for model in models)


def test_groq_live_models_take_precedence_over_fallback() -> None:
    models = free_models_from("groq", ["llama-3.3-70b-versatile"])
    assert [model.id for model in models] == ["llama-3.3-70b-versatile"]


def test_gemini_has_no_fallback() -> None:
    # у Gemini запасного списка нет: без /models подключать нечего
    assert free_models_from("gemini", []) == []

def test_openrouter_prefers_known_chat_families() -> None:
    remote = [
        "liquid/lfm-2.5-2.6b:free",
        "google/gemma-4-31b-it:free",
        "nvidia/nemotron-3.5-lightning:free",
    ]
    models = free_models_from("openrouter", remote)
    assert [model.id for model in models] == [
        "nvidia/nemotron-3.5-lightning:free",
        "google/gemma-4-31b-it:free",
        "liquid/lfm-2.5-2.6b:free",
    ]


def test_openrouter_skips_service_models() -> None:
    remote = [
        "nvidia/nemotron-3.5-content-safety:free",
        "cohere/north-mini-code:free",
        "openai/gpt-oss-20b:free",
    ]
    models = free_models_from("openrouter", remote)
    assert [model.id for model in models] == ["openai/gpt-oss-20b:free"]

def test_openrouter_fallback_when_models_endpoint_is_blocked() -> None:
    from app.models_catalog import OPENROUTER_FALLBACK_MODELS

    models = free_models_from("openrouter", [])
    assert [model.id for model in models] == list(OPENROUTER_FALLBACK_MODELS)
