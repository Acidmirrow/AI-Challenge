"""Тесты API урока 05: задачи, каталог с размером моделей, сравнение и анализ.

Всё на mock-провайдере: сеть не нужна, но структура ответов — та же, что у
настоящих моделей (usage, finish_reason, стоимость).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import _usage_total, create_app
from app.models_catalog import NOUS_FALLBACK_MODELS, free_models_from, tier_from_name
from app.pricing import cost_of, load_prices

SMALL = "mock-fast"
MEDIUM = "mock-reasoner"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("PROVIDER", "mock")
    from app.config import get_settings

    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _compare_payload(**overrides) -> dict:
    payload = {
        "prompt": "Сколько будет 17 × 4?",
        "models": [SMALL, MEDIUM],
        "task": "arithmetic",
        "complexity": "low",
        "reference": "68",
        "temperature": 0.2,
        "reasoning": "off",
        "max_tokens": 400,
    }
    payload.update(overrides)
    return payload


# --- задачи и каталог --------------------------------------------------------


def test_health_reports_five_tasks(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["tasks"] == 5


def test_tasks_go_from_low_to_expert(client: TestClient) -> None:
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 5
    assert [task["complexity"] for task in tasks] == [
        "low", "medium", "high", "very high", "expert",
    ]
    assert [task["id"] for task in tasks] == [
        "arithmetic", "fruits", "train", "warehouse", "bridge",
    ]
    for task in tasks:
        assert task["text"].strip()
        assert task["reference"].strip()


def test_models_carry_size_tier(client: TestClient) -> None:
    models = {item["id"]: item for item in client.get("/api/models").json()}
    assert models[SMALL]["tier"] == "small"
    assert models[MEDIUM]["tier"] == "medium"
    assert all(item["tier"] in {"small", "medium", "large"} for item in models.values())


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("google/gemma-4-2b-it:free", "small"),
        ("google/gemma-4-31b-it:free", "medium"),
        ("qwen/qwen3.8-27b:free", "medium"),
        ("nvidia/nemotron-3-ultra-550b-a55b:free", "large"),
        ("openai/gpt-oss-120b:free", "large"),
        ("deepseek-flash", "small"),
        ("deepseek-v4-pro", "large"),
        ("some-unknown-model", "medium"),
    ],
)
def test_tier_from_name(model_id: str, expected: str) -> None:
    assert tier_from_name(model_id) == expected


def test_nous_free_models_cover_all_size_tiers() -> None:
    """Запасной список Nous Portal даёт все три размера моделей для трёх слотов."""
    models = free_models_from("nous", [])
    assert [model.id for model in models] == list(NOUS_FALLBACK_MODELS)
    assert {model.tier for model in models} == {"small", "medium", "large"}


# --- сравнение моделей -------------------------------------------------------


def test_compare_runs_every_model(client: TestClient) -> None:
    response = client.post("/api/compare", json=_compare_payload())
    assert response.status_code == 200
    body = response.json()
    assert [run["model"] for run in body["runs"]] == [SMALL, MEDIUM]
    for run in body["runs"]:
        assert run["answer"].strip()
        assert run["usage"]["completion_tokens"] > 0
        assert run["elapsed_ms"] >= 0
        assert run["error"] is None
        # mock — бесплатный провайдер: стоимость нулевая и это объяснено
        assert run["cost_usd"] == 0.0
        assert run["cost_note"] == "бесплатный провайдер"
    totals = body["totals"]
    assert totals["models"] == 2
    assert totals["completion_tokens"] > 0
    assert totals["failed"] == 0
    # mock не присылает total_tokens: итог всё равно считается как сумма частей
    assert totals["prompt_tokens"] > 0
    assert totals["total_tokens"] == totals["prompt_tokens"] + totals["completion_tokens"]


def test_compare_rejects_duplicate_models(client: TestClient) -> None:
    response = client.post("/api/compare", json=_compare_payload(models=[SMALL, SMALL]))
    assert response.status_code == 422


def test_compare_rejects_unknown_model(client: TestClient) -> None:
    response = client.post("/api/compare", json=_compare_payload(models=[SMALL, "nope"]))
    assert response.status_code == 400


def test_compare_requires_at_least_two_models(client: TestClient) -> None:
    response = client.post("/api/compare", json=_compare_payload(models=[SMALL]))
    assert response.status_code == 422


# --- анализ сравнения --------------------------------------------------------


def test_analyze_returns_text(client: TestClient) -> None:
    compare = client.post("/api/compare", json=_compare_payload()).json()
    runs = [
        {
            "model": run["model"],
            "label": run["label"],
            "answer": run["answer"],
            "elapsed_ms": run["elapsed_ms"],
            "usage": run["usage"],
            "cost_usd": run["cost_usd"],
        }
        for run in compare["runs"]
    ]
    response = client.post(
        "/api/analyze",
        json={
            "model": MEDIUM,
            "prompt": compare["prompt"],
            "task": "arithmetic",
            "complexity": "low",
            "reference": "68",
            "runs": runs,
            "max_tokens": 600,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == MEDIUM
    assert body["text"].strip()
    assert body["usage"]["completion_tokens"] > 0


def test_analyze_rejects_unknown_model(client: TestClient) -> None:
    response = client.post(
        "/api/analyze",
        json={
            "model": "nope",
            "prompt": "2 + 2?",
            "runs": [{"model": SMALL, "answer": "4"}],
        },
    )
    assert response.status_code == 400


# --- чат ---------------------------------------------------------------------


def test_chat_streams_answer(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/chat",
        json={
            "model": SMALL,
            "messages": [{"role": "user", "content": "Привет"}],
            "temperature": 0.3,
            "max_tokens": 200,
        },
    ) as response:
        assert response.status_code == 200
        text = "".join(response.iter_text())
    assert "event: done" in text
    assert "event: start" in text


# --- стоимость ---------------------------------------------------------------


def test_usage_total_prefers_reported_total() -> None:
    """Если провайдер прислал total_tokens — берём его, иначе сумму частей."""
    assert _usage_total({"prompt_tokens": 10, "completion_tokens": 5}) == 15
    assert _usage_total({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 20}) == 20


def test_pricing_counts_prompt_and_completion() -> None:
    prices = load_prices("/nonexistent/pricing.properties")
    price_in, price_out, cost, note = cost_of(
        prices,
        "deepseek-flash",
        "deepseek",
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000},
    )
    assert (price_in, price_out) == (0.28, 0.42)
    assert cost == pytest.approx(0.70)
    assert note == "по прайсу провайдера"


def test_pricing_free_provider_is_zero() -> None:
    prices = load_prices("/nonexistent/pricing.properties")
    assert cost_of(prices, "nvidia/nemotron-3.5-lightning:free", "openrouter", {"prompt_tokens": 500}) == (
        0.0, 0.0, 0.0, "бесплатный провайдер",
    )


def test_pricing_nous_free_provider_is_zero() -> None:
    prices = load_prices("/nonexistent/pricing.properties")
    assert cost_of(
        prices, "stepfun/step-3.7-flash:free", "nous",
        {"prompt_tokens": 500, "completion_tokens": 500},
    ) == (0.0, 0.0, 0.0, "бесплатный провайдер")


def test_pricing_unknown_model_has_no_price() -> None:
    prices = load_prices("/nonexistent/pricing.properties")
    _, _, cost, note = cost_of(prices, "unknown", "deepseek", {"prompt_tokens": 1000})
    assert cost == 0.0
    assert note == "цена не задана"


def test_pricing_file_overrides_defaults(tmp_path) -> None:
    path = tmp_path / "pricing.properties"
    path.write_text("deepseek-flash.in = 1.5\ndeepseek-flash.out = 2.5\n", encoding="utf-8")
    prices = load_prices(str(path))
    assert prices["deepseek-flash"] == (1.5, 2.5)
