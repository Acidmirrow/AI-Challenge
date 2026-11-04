"""Mock / real-API switching: every model carries the provider that serves it."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events, event, data = [], None, []
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


@pytest.fixture
def app_without_key(monkeypatch):
    """Real provider configured but no key: mock models must still answer."""
    monkeypatch.setenv("PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()


def test_models_expose_provider(app_without_key: TestClient) -> None:
    models = app_without_key.get("/api/models").json()
    by_id = {m["id"]: m for m in models}
    assert by_id["deepseek-flash"]["provider"] == "deepseek"
    assert by_id["mock-reasoner"]["provider"] == "mock"


def test_mock_model_works_without_api_key(app_without_key: TestClient) -> None:
    response = app_without_key.post(
        "/api/chat",
        json={
            "model": "mock-reasoner",
            "messages": [{"role": "user", "content": "привет из демо"}],
            "reasoning": "high",
        },
    )
    assert response.status_code == 200
    events = parse_sse(response.text)
    answer = "".join(d["text"] for kind, d in events if kind == "delta")
    assert "привет из демо" in answer
    assert events[-1][0] == "done"


def test_real_model_without_key_returns_503(app_without_key: TestClient) -> None:
    response = app_without_key.post(
        "/api/chat",
        json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 503
    assert "deepseek.api.key" in response.json()["detail"]


def test_health_reports_primary_provider(app_without_key: TestClient) -> None:
    body = app_without_key.get("/api/health").json()
    assert body["status"] == "degraded"
    assert "deepseek" in body["provider"]
