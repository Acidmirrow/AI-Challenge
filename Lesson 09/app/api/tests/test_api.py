import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_demo(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["demo_messages"] == 25
    assert health["demo_summaries"] == 3
    demo = client.get("/api/demo-dialogue").json()
    assert len(demo["messages"]) == 25
    assert len(demo["summaries"]) == 3
    assert "Ласточка" in demo["title"]


def test_context_budget(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/context",
        json={
            "messages": demo["messages"],
            "strategy": "budget",
            "max_messages": 24,
            "max_tokens": 500,
            "reserve_tokens": 100,
            "system_tokens": 20,
        },
    ).json()
    assert result["strategy_label"] == "Бюджет токенов"
    assert result["available"] == 400
    assert result["message_budget"] == 380
    assert result["included_ids"]
    assert result["dropped_ids"]
    assert result["included_tokens"] <= 380
    assert result["fits"] is True


def test_context_full(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/context",
        json={
            "messages": demo["messages"],
            "strategy": "full",
            "max_messages": 2,
            "max_tokens": 100_000,
            "reserve_tokens": 100,
        },
    ).json()
    assert len(result["included_ids"]) == 25
    assert result["dropped_ids"] == []


def test_context_last(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/context",
        json={
            "messages": demo["messages"],
            "strategy": "last",
            "max_messages": 4,
            "max_tokens": 100_000,
            "reserve_tokens": 100,
        },
    ).json()
    assert result["included_ids"] == [22, 23, 24, 25]
    assert len(result["dropped_ids"]) == 21


def test_ask_uses_selected_context(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/ask",
        json={
            "messages": demo["messages"],
            "question": "Какой бюджет проекта?",
            "strategy": "full",
            "max_messages": 24,
            "max_tokens": 100_000,
            "reserve_tokens": 100,
        },
    ).json()
    assert "4 850 000" in result["answer"]
    assert result["source_ids"]
    assert result["included_ids"]


def test_ask_explains_missing_fact_and_dropped_range(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/ask",
        json={
            "messages": demo["messages"],
            "question": "Какая кровля используется?",
            "strategy": "budget",
            "max_messages": 12,
            "max_tokens": 4_000,
            "reserve_tokens": 500,
        },
    ).json()
    assert result["found"] is False
    assert result["source_ids"] == []
    assert "Бюджет токенов" in result["answer"]
    assert "12 из 25" in result["answer"]
    assert "№14–25" in result["answer"]
    assert "№1–13" in result["answer"]
    assert "Лимит сообщений" in result["answer"]


def test_compress_compares_full_history_and_summaries(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/compress",
        json={
            "messages": demo["messages"],
            "summaries": demo["summaries"],
            "max_tokens": 4_000,
            "reserve_tokens": 500,
            "system_tokens": 20,
        },
    ).json()
    assert result["before"]["messages"] == 25
    assert result["before"]["summaries"] == 0
    assert result["after"]["messages"] == 0
    assert result["after"]["summaries"] == 3
    assert result["after"]["tokens"] < result["before"]["tokens"]
    assert result["saved_tokens"] > 0
    assert result["saved_percent"] > 0


def test_context_can_use_summaries(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/context",
        json={
            "messages": demo["messages"],
            "summaries": demo["summaries"],
            "use_summaries": True,
            "strategy": "budget",
            "max_messages": 12,
            "max_tokens": 4_000,
            "reserve_tokens": 500,
        },
    ).json()
    assert result["compressed"] is True
    assert result["summary_count"] == 3
    assert result["included_ids"]
    assert all(item >= 1001 for item in result["included_ids"])


def test_ask_uses_summaries_when_compressed(client: TestClient) -> None:
    demo = client.get("/api/demo-dialogue").json()
    result = client.post(
        "/api/ask",
        json={
            "messages": demo["messages"],
            "summaries": demo["summaries"],
            "use_summaries": True,
            "question": "Какой бюджет проекта?",
            "strategy": "budget",
            "max_messages": 12,
            "max_tokens": 4_000,
            "reserve_tokens": 500,
        },
    ).json()
    assert result["compressed"] is True
    assert "4 850 000" in result["answer"]
    assert result["source_ids"]
    assert all(item >= 1001 for item in result["source_ids"])


def test_chat_endpoint_answers_without_dialogue(client: TestClient) -> None:
    result = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Привет"}]},
    ).json()
    assert result["answer"]
    assert result["model"]
