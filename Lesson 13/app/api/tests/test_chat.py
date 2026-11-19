from fastapi.testclient import TestClient

import app.main as main
from app.task_state.service import TaskService
from app.task_state.sqlite_repository import SQLiteTaskRepository


def test_health() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["lesson"] == 13
    assert response.json()["state_machine"] == "available"


def test_chat_uses_history(tmp_path, monkeypatch) -> None:
    service = TaskService(SQLiteTaskRepository(tmp_path / "chat.db"))
    monkeypatch.setattr(main, "_task_service", service)
    captured = {}

    def fake_chat(messages, model=None):
        captured["messages"] = messages
        return (
            "Следующий шаг — уточнить цель.",
            "test-model",
            {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/chat",
            json={
                "message": "Что дальше?",
                "history": [
                    {"role": "user", "content": "Нужно подготовить отчёт."},
                    {"role": "assistant", "content": "Уточните срок."},
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Следующий шаг — уточнить цель."
    assert body["request_tokens"] == 42
    assert [item["role"] for item in captured["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert captured["messages"][-1]["content"] == "Что дальше?"


def test_chat_has_no_http_cache() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/health")
    assert "no-store" in response.headers["cache-control"]
