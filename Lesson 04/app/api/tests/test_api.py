"""Тесты API урока 04: каталог задач, чат и сравнение температур на mock-провайдере."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

MOCK_MODEL = "mock-fast"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("PROVIDER", "mock")
    from app.config import get_settings

    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_health_reports_mock_provider(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["tasks"] == 5


def test_tasks_cover_required_kinds(client: TestClient) -> None:
    tasks = client.get("/api/tasks").json()
    assert len(tasks) == 5
    kinds = {task["kind"] for task in tasks}
    assert {"single-answer", "text", "variants"} <= kinds
    assert [task["id"] for task in tasks] == [
        "arithmetic", "logic", "writing", "names", "puzzle",
    ]
    # каждый тип задачи — три варианта сложности от low до high
    for task in tasks:
        variants = task["variants"]
        assert len(variants) == 3, task["id"]
        assert [variant["complexity"] for variant in variants] == ["low", "medium", "high"]
    arithmetic = next(task for task in tasks if task["id"] == "arithmetic")
    assert arithmetic["variants"][0]["reference"] == "68"


def test_analyze_compares_temperature_answers(client: TestClient) -> None:
    response = client.post(
        "/api/analyze",
        json={
            "model": MOCK_MODEL,
            "prompt": "Сколько будет 17 × 4?",
            "task": "arithmetic",
            "variant": "arithmetic-low",
            "reference": "68",
            "runs": [
                {"temperature": 0.0, "answer": "68"},
                {"temperature": 1.2, "answer": "72"},
            ],
            "max_tokens": 400,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == MOCK_MODEL
    assert body["text"]
    assert body["usage"].get("completion_tokens", 0) > 0


def test_analyze_rejects_unknown_model(client: TestClient) -> None:
    response = client.post(
        "/api/analyze",
        json={
            "model": "нет-такой-модели",
            "prompt": "привет",
            "runs": [{"temperature": 0.0, "answer": "привет"}],
        },
    )
    assert response.status_code == 400


def test_compare_runs_each_temperature_once(client: TestClient) -> None:
    response = client.post(
        "/api/temperature/compare",
        json={
            "model": MOCK_MODEL,
            "prompt": "Сколько будет 17 × 4?",
            "temperatures": [0.0, 0.7, 1.2],
            "max_tokens": 400,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [run["temperature"] for run in body["runs"]] == [0.0, 0.7, 1.2]
    assert all(run["answer"] for run in body["runs"])
    assert body["spread"]["answers"] == 3
    assert body["spread"]["errors"] == 0


def test_compare_orders_temperatures_and_deduplicates(client: TestClient) -> None:
    body = client.post(
        "/api/temperature/compare",
        json={
            "model": MOCK_MODEL,
            "prompt": "Придумай название кофейни",
            "temperatures": [1.2, 0.0, 0.0],
        },
    ).json()
    assert [run["temperature"] for run in body["runs"]] == [0.0, 1.2]


def test_compare_repeats_each_temperature(client: TestClient) -> None:
    body = client.post(
        "/api/temperature/compare",
        json={
            "model": MOCK_MODEL,
            "prompt": "Придумай название кофейни",
            "temperatures": [0.0, 1.2],
            "repeats": 2,
            "max_tokens": 300,
        },
    ).json()
    # 2 температуры × (1 + 2 повтора)
    assert len(body["runs"]) == 6
    assert [run["repeat"] for run in body["runs"]] == [0, 1, 2, 0, 1, 2]
    assert body["spread"]["repeats"] == 2
    assert body["spread"]["per_temperature"]["0.0"]["runs"] == 3
    assert body["spread"]["per_temperature"]["1.2"]["runs"] == 3


def test_compare_rejects_too_many_repeats(client: TestClient) -> None:
    response = client.post(
        "/api/temperature/compare",
        json={"model": MOCK_MODEL, "prompt": "привет", "repeats": 11},
    )
    assert response.status_code == 422


def test_compare_rejects_out_of_range_temperature(client: TestClient) -> None:
    response = client.post(
        "/api/temperature/compare",
        json={"model": MOCK_MODEL, "prompt": "привет", "temperatures": [2.5]},
    )
    assert response.status_code == 422


def test_compare_rejects_unknown_model(client: TestClient) -> None:
    response = client.post(
        "/api/temperature/compare",
        json={"model": "нет-такой-модели", "prompt": "привет", "temperatures": [0.5]},
    )
    assert response.status_code == 400


def test_chat_streams_start_delta_done(client: TestClient) -> None:
    with client.stream(
        "POST",
        "/api/chat",
        json={
            "model": MOCK_MODEL,
            "messages": [{"role": "user", "content": "привет"}],
            "temperature": 0.7,
            "max_tokens": 200,
        },
    ) as response:
        assert response.status_code == 200
        events = []
        payloads = {}
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            elif line.startswith("data:"):
                payloads[events[-1]] = json.loads(line.split(":", 1)[1].strip())
    assert events[0] == "start"
    assert "delta" in events
    assert payloads["done"]["temperature"] == 0.7


def test_compare_reports_truncation(client: TestClient) -> None:
    body = client.post(
        "/api/temperature/compare",
        json={
            "model": MOCK_MODEL,
            "prompt": "Расскажи очень подробно про RAG и fine-tuning, различия и примеры",
            "temperatures": [0.0],
            "max_tokens": 16,
        },
    ).json()
    run = body["runs"][0]
    assert run["truncated"] is True
    assert run["finish_reason"] == "length"
    assert body["spread"]["truncated"] == 1
