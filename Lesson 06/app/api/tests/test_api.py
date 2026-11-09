"""Тесты API урока 06: каталог инструментов и агентский цикл на mock-модели."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

SMALL = "mock-fast"
MEDIUM = "mock-reasoner"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("PROVIDER", "mock")
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


def _agent_payload(**overrides) -> dict:
    payload = {
        "prompt": "Посчитай 17 * 4.",
        "model": SMALL,
        "temperature": 0.2,
        "reasoning": "off",
        "max_tokens": 600,
        "max_steps": 4,
    }
    payload.update(overrides)
    return payload


def test_health_reports_tools(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["tools"] == 9


def test_tools_catalog(client: TestClient) -> None:
    tools = client.get("/api/tools").json()
    assert len(tools) == 9
    for tool in tools:
        assert tool["name"]
        assert tool["label"]
        assert tool["description"]
        assert tool["parameters"]["type"] == "object"


def test_agent_calls_calculator(client: TestClient) -> None:
    response = client.post("/api/agent", json=_agent_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["answer"].strip()
    assert body["stopped_reason"] == "final"
    assert body["steps"], "агент должен вызвать хотя бы один инструмент"
    step = body["steps"][0]
    assert step["tool"] == "calculator"
    assert step["result"]["ok"] is True
    assert step["result"]["result"]["value"] == 68
    assert body["usage"]["completion_tokens"] > 0
    assert body["elapsed_ms"] >= 0


def test_agent_uses_only_selected_tool(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Посчитай 17 * 4.", tools=["calculator"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tools"] == ["calculator"]
    assert body["steps"][0]["tool"] == "calculator"


def test_agent_refuses_without_required_tool(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Посчитай 17 * 4.", tools=[]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "missing_tool"
    assert body["missing_tools"] == ["calculator"]
    assert body["steps"] == []
    assert "нет возможности" in body["answer"]


def test_agent_refuses_when_wrong_tool_selected(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Посчитай 17 * 4.", tools=["current_time"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "missing_tool"
    assert body["missing_tools"] == ["calculator"]


def test_agent_refuses_when_second_tool_missing(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(
            prompt="Узнай курс доллара и посчитай, сколько рублей в 250 долларах.",
            tools=["currency_rates"],
        ),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "missing_tool"
    assert body["missing_tools"] == ["calculator"]
    assert body["steps"] == []


def test_agent_refuses_without_unit_tool(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Переведи 5 км в метры.", tools=[]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "missing_tool"
    assert body["missing_tools"] == ["unit_converter"]
    assert body["steps"] == []


def test_agent_calls_hash_tool(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Сделай SHA256 от текста hello.", tools=["text_hash"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "final"
    assert body["steps"][0]["tool"] == "text_hash"
    assert body["steps"][0]["result"]["ok"] is True


def test_agent_without_tools_answers_general_question(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Привет! Как дела?", tools=[]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "final"
    assert body["answer"].strip()
    assert body["steps"] == []


def test_agent_rejects_unknown_tool(client: TestClient) -> None:
    response = client.post(
        "/api/agent",
        json=_agent_payload(prompt="Посчитай 17 * 4.", tools=["nope"]),
    )
    assert response.status_code == 400


def test_agent_rejects_unknown_model(client: TestClient) -> None:
    response = client.post("/api/agent", json=_agent_payload(model="nope"))
    assert response.status_code == 400


def test_agent_validates_max_steps(client: TestClient) -> None:
    assert client.post("/api/agent", json=_agent_payload(max_steps=0)).status_code == 422
    assert client.post("/api/agent", json=_agent_payload(max_steps=11)).status_code == 422


def test_agent_requires_prompt(client: TestClient) -> None:
    assert client.post("/api/agent", json=_agent_payload(prompt="")).status_code == 422
