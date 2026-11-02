"""API contract tests. Run with: docker compose exec api pytest -q"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event, data = None, []
    for line in raw.splitlines() + [""]:
        if line == "":
            if event:
                events.append((event, json.loads("".join(data) or "{}")))
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    return events


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "mock" in body["provider"]


def test_models(client: TestClient) -> None:
    models = client.get("/api/models").json()
    ids = {m["id"] for m in models}
    assert {"mock-fast", "mock-reasoner"} <= ids
    reasoner = next(m for m in models if m["id"] == "mock-reasoner")
    assert reasoner["supports_reasoning"] is True


def test_chat_streams_reasoning_and_answer(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "model": "mock-reasoner",
            "messages": [{"role": "user", "content": "Привет"}],
            "temperature": 0.3,
            "reasoning": "high",
            "max_tokens": 256,
        },
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "reasoning"
    assert "delta" in kinds
    assert kinds[-1] == "done"

    answer = "".join(data.get("text", "") for kind, data in events if kind == "delta")
    assert "Привет" in answer
    assert "0.3" in answer
    assert events[-1][1]["model"] == "mock-reasoner"


def test_chat_without_reasoning_has_no_reasoning_events(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "model": "mock-fast",
            "messages": [{"role": "user", "content": "Hi"}],
            "reasoning": "high",  # unsupported by this model → downgraded to off
        },
    )
    kinds = [kind for kind, _ in parse_sse(response.text)]
    assert "reasoning" not in kinds
    assert kinds[-1] == "done"


def test_unknown_model_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={"model": "nope", "messages": [{"role": "user", "content": "Hi"}]},
    )
    assert response.status_code == 400
    assert "Неизвестная модель" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "mock-fast", "messages": [{"role": "assistant", "content": "Hi"}]},
        {"model": "mock-fast", "messages": [{"role": "user", "content": "Hi"}], "temperature": 5},
    ],
)
def test_invalid_payload_rejected(client: TestClient, payload: dict) -> None:
    assert client.post("/api/chat", json=payload).status_code == 422
