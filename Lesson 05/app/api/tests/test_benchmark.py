"""Бенчмарк: проверка ответов по эталону и сводка «верных / время / токены / цена»."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.checker import answer_is_correct
from app.main import _verdicts, create_app

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


@pytest.mark.parametrize(
    ("answer", "reference", "expected"),
    [
        ("68", "68", True),
        ("Ответ: 68.", "68", True),
        ("17 × 4 = 68", "68", True),
        ("168", "68", False),
        ("12,5", "12 фруктов", False),
        ("12 фруктов", "12 фруктов", True),
        ("18:50, 255 минут", "18:50, 255 минут", True),
        ("Прибудет в 18:50, всего 255 минут", "18:50, 255 минут", True),
        ("Прибудет в 18:50", "18:50, 255 минут", False),
        ("45 коробок", "45 коробок", True),
        ("17 минут", "17 минут", True),
        ("19 минут", "17 минут", False),
        ("", "68", False),
    ],
)
def test_answer_is_correct(answer: str, reference: str, expected: bool) -> None:
    assert answer_is_correct(answer, reference) is expected


def test_benchmark_runs_every_model_on_every_task(client: TestClient) -> None:
    response = client.post(
        "/api/benchmark",
        json={
            "models": [SMALL, MEDIUM],
            "tasks": ["arithmetic", "fruits"],
            "temperature": 0.2,
            "reasoning": "off",
            "max_tokens": 300,
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert body["task_ids"] == ["arithmetic", "fruits"]
    assert len(body["runs"]) == 4
    assert {run["task"] for run in body["runs"]} == {"arithmetic", "fruits"}
    assert {run["model"] for run in body["runs"]} == {SMALL, MEDIUM}
    for run in body["runs"]:
        assert run["usage"]["completion_tokens"] > 0
        assert run["cost_usd"] == 0.0
        assert run["error"] is None
        # mock отвечает эхом — эталонных чисел в ответе нет
        assert run["correct"] is False

    models = {item["model"]: item for item in body["models"]}
    for item in models.values():
        assert item["total"] == 2
        assert item["correct"] == 0
        assert item["accuracy"] == 0.0
        assert item["total_tokens"] > 0
    assert body["totals"]["tasks"] == 2
    assert body["totals"]["runs"] == 4
    assert body["comparison"]["small"] == SMALL
    assert body["comparison"]["large"] == MEDIUM
    assert body["comparison"]["cost_ratio"] is None  # mock бесплатен
    assert body["comparison"]["both_free"] is True


def test_benchmark_rejects_unknown_task(client: TestClient) -> None:
    response = client.post(
        "/api/benchmark", json={"models": [SMALL, MEDIUM], "tasks": ["nope"]}
    )
    assert response.status_code == 400


def test_benchmark_rejects_duplicate_models(client: TestClient) -> None:
    response = client.post(
        "/api/benchmark", json={"models": [SMALL, SMALL], "tasks": ["arithmetic"]}
    )
    assert response.status_code == 422


def test_verdicts_parse_json_with_fences() -> None:
    raw = '''```json
{"verdicts": [{"task": "arithmetic", "model": "m1", "correct": true},
              {"task": "fruits", "model": "m1", "correct": false}]}
```'''
    assert _verdicts(raw) == {("arithmetic", "m1"): True, ("fruits", "m1"): False}
    assert _verdicts("не json") == {}


def test_benchmark_judge_falls_back_when_not_json(client: TestClient) -> None:
    response = client.post(
        "/api/benchmark",
        json={
            "models": [SMALL, MEDIUM],
            "tasks": ["arithmetic"],
            "max_tokens": 200,
            "judge": MEDIUM,
        },
    )
    assert response.status_code == 200
    body = response.json()
    # mock-судья отвечает эхом, а не JSON — остаётся детерминированная проверка
    assert body["totals"]["judged"] is False
    assert len(body["runs"]) == 2


def test_benchmark_analyze_returns_text(client: TestClient) -> None:
    benchmark = client.post(
        "/api/benchmark",
        json={"models": [SMALL, MEDIUM], "tasks": ["arithmetic"], "max_tokens": 300},
    ).json()
    answers = [
        {
            "model": run["model"],
            "label": run["label"],
            "answer": run["answer"],
            "correct": run["correct"],
        }
        for run in benchmark["runs"]
    ]
    response = client.post(
        "/api/benchmark/analyze",
        json={
            "model": MEDIUM,
            "summary": benchmark["models"],
            "tasks": [
                {
                    "task": "arithmetic",
                    "title": "Арифметика в одно действие",
                    "reference": "68",
                    "answers": answers,
                }
            ],
            "comparison": benchmark["comparison"],
            "max_tokens": 600,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == MEDIUM
    assert body["text"].strip()
