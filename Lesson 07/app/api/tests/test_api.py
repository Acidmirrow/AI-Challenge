import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def session_id() -> str:
    return f"ctx-{uuid.uuid4().hex[:10]}"


def chat(client: TestClient, sid: str, prompt: str, **extra):
    payload = {
        "session_id": sid,
        "prompt": prompt,
        "model": "mock-fast",
        "temperature": 0.2,
        "max_tokens": 220,
        "max_messages": 20,
        "tools": [],
        **extra,
    }
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_storage(client: TestClient) -> None:
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["storage"].endswith("context.db")
    assert data["max_context_messages"] == 20
    assert data["sessions"] >= 0


def test_models_are_available(client: TestClient) -> None:
    models = client.get("/api/models").json()
    assert any(item["id"] == "mock-fast" for item in models)


def test_chat_saves_history_and_reuses_it(client: TestClient) -> None:
    sid = session_id()
    first = chat(client, sid, "Меня зовут Борис.")
    assert first["total_messages"] == 2
    assert first["context"]["included_messages"] == 0

    second = chat(client, sid, "Как меня зовут?")
    assert second["total_messages"] == 4
    assert second["context"]["included_messages"] == 2
    assert [m["role"] for m in second["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]

    detail = client.get(f"/api/sessions/{sid}").json()
    assert detail["message_count"] == 4
    assert detail["messages"][0]["content"] == "Меня зовут Борис."


def test_context_window_drops_old_messages(client: TestClient) -> None:
    sid = session_id()
    for index in range(3):
        chat(client, sid, f"Сообщение номер {index}")

    result = chat(client, sid, "Последний вопрос", max_messages=2)
    assert result["context"]["included_messages"] == 2
    assert result["context"]["dropped_messages"] == 4
    assert result["context"]["max_messages"] == 2
    assert result["total_messages"] == 8


def test_tool_calls_are_saved_in_history(client: TestClient) -> None:
    sid = session_id()
    first = chat(client, sid, "Посчитай 2 + 2", tools=["calculator"])
    roles = [item["role"] for item in first["messages"]]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert first["messages"][1]["tool_calls"][0]["function"]["name"] == "calculator"
    assert first["messages"][2]["name"] == "calculator"
    assert first["steps"][0]["tool"] == "calculator"

    second = chat(client, sid, "Продолжи диалог", tools=["calculator"])
    assert second["total_messages"] == 6
    assert second["context"]["included_messages"] == 4
    assert second["messages"][2]["role"] == "tool"
    assert second["messages"][2]["content"].startswith("{")


def test_selected_past_conversation_is_used_as_context(client: TestClient) -> None:
    past = session_id()
    chat(client, past, "Меня зовут Борис.", tools=[])
    current = session_id()
    chat(client, current, "Привет.", tools=[])

    result = chat(
        client,
        current,
        "Как меня зовут?",
        tools=[],
        context_sessions=[past],
    )
    assert result["context"]["past_sessions"] == 1
    # 2 реплики прошлого диалога + 2 системных маркера + 2 текущие реплики
    assert result["context"]["included_messages"] == 6
    assert result["context_sessions"] == [past]
    assert result["total_messages"] == 4


def test_unknown_past_context_session_is_rejected(client: TestClient) -> None:
    sid = session_id()
    response = client.post(
        "/api/chat",
        json={
            "session_id": sid,
            "prompt": "Привет",
            "model": "mock-fast",
            "tools": [],
            "context_sessions": ["ctx-does-not-exist"],
        },
    )
    assert response.status_code == 400


def test_clear_and_delete_session(client: TestClient) -> None:
    sid = session_id()
    chat(client, sid, "Привет")

    cleared = client.post(f"/api/sessions/{sid}/clear")
    assert cleared.status_code == 200
    assert cleared.json()["message_count"] == 0
    assert client.get(f"/api/sessions/{sid}").json()["messages"] == []
    # пустой диалог не считается сохранённым и не попадает в список
    assert all(item["id"] != sid for item in client.get("/api/sessions").json())

    deleted = client.delete(f"/api/sessions/{sid}")
    assert deleted.status_code == 200
    assert client.get(f"/api/sessions/{sid}").status_code == 404


def test_unknown_session_returns_404(client: TestClient) -> None:
    assert client.get("/api/sessions/ctx-missing").status_code == 404
    assert client.delete("/api/sessions/ctx-missing").status_code == 404


def test_invalid_session_id_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        json={
            "session_id": "bad/id",
            "prompt": "Привет",
            "model": "mock-fast",
        },
    )
    assert response.status_code == 422


def test_prompt_reference_auto_includes_past_session(client: TestClient) -> None:
    past = session_id()
    chat(client, past, "Запомни пароль: сорок два.", tools=[])
    past_row = app.state.store.get_session(past)
    assert past_row is not None
    current = session_id()
    chat(client, current, "Привет.", tools=[])

    result = chat(
        client,
        current,
        f"Возьми мой запрос из Диалога {past_row['number']} и ответь на него.",
        tools=[],
    )
    assert past in result["context_sessions"]
    assert result["context"]["past_sessions"] == 1


def test_delete_all_contexts(client: TestClient) -> None:
    sid = session_id()
    chat(client, sid, "Удалить всё", tools=[])
    response = client.delete("/api/sessions")
    assert response.status_code == 200
    data = response.json()
    assert data["deleted_sessions"] >= 1
    assert data["deleted_messages"] >= 2
    assert client.get("/api/sessions").json() == []
