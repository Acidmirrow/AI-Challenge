"""Запасной список бесплатных моделей: UI не должен оставаться без них."""

from __future__ import annotations

from app.models_catalog import free_models_from


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


def test_nous_free_models_and_fallback() -> None:
    from app.models_catalog import NOUS_FALLBACK_MODELS

    # /models недоступен — остаётся запасной список бесплатных моделей
    assert [model.id for model in free_models_from("nous", [])] == list(NOUS_FALLBACK_MODELS)

    # живой список важнее: только :free и не больше четырёх моделей
    remote = [
        "stepfun/step-3.7-flash:free",
        "openai/gpt-5",
        "upstage/solar-mini4:free",
        "meituan/longcat-2.5:free",
        "reflection/beam-1.0-501b-a23b:free",
        "stepfun/step-4:free",
    ]
    picked = [model.id for model in free_models_from("nous", remote)]
    assert "openai/gpt-5" not in picked
    assert len(picked) == 4
    assert set(picked) <= {model_id for model_id in remote if model_id.endswith(":free")}
