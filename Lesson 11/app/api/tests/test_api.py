import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.context import build_context
from app.memory import SHORT_TERM_LIMIT, MemoryStore


@pytest.fixture()
def store(tmp_path) -> MemoryStore:
    return MemoryStore(tmp_path / "memory.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", MemoryStore(tmp_path / "memory.db"))
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_and_memory_model(client) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["lesson"] == 11
    assert health["layers"] == ["short_term", "working", "long_term"]
    assert health["retrieval_limit"] >= 1

    model = client.get("/api/model").json()
    assert [layer["id"] for layer in model["layers"]] == [
        "short_term",
        "working",
        "long_term",
    ]
    assert "профиль" in model["layers"][2]["description"].lower()
    assert "FTS5" in model["retrieval"]["method"]


def test_seeded_long_term_memory_has_three_sections(client) -> None:
    state = client.get("/api/state").json()
    long_term = state["long_term"]
    assert long_term["count"] >= 3
    assert long_term["profile"]
    assert long_term["decisions"]
    assert long_term["knowledge"]
    assert any(item["key"] == "Имя" for item in long_term["profile"])
    assert all(item["source"] for item in long_term["items"])
    assert all(0 <= item["confidence"] <= 1 for item in long_term["items"])


def test_short_term_is_bounded_and_can_be_cleared(client) -> None:
    for index in range(SHORT_TERM_LIMIT + 6):
        response = client.post(
            "/api/message",
            json={"session_id": "s1", "content": f"сообщение {index}"},
        )
        assert response.status_code == 200

    state = client.get("/api/state", params={"session_id": "s1"}).json()
    assert state["short_term"]["count"] == SHORT_TERM_LIMIT
    assert state["short_term"]["messages"][0]["content"] != "сообщение 0"
    assert state["short_term"]["messages"][-1]["content"] == "сообщение 29"

    cleared = client.delete("/api/short-term", params={"session_id": "s1"}).json()
    assert cleared["removed"] == SHORT_TERM_LIMIT
    assert cleared["state"]["short_term"]["count"] == 0


def test_working_memory_is_isolated_by_session(client) -> None:
    payload = {
        "session_id": "task-a",
        "title": "Собрать урок 11",
        "goal": "Показать три слоя памяти",
        "status": "В работе",
        "next_step": "Проверить UI",
        "constraints": "Не раскрывать секреты",
    }
    saved = client.post("/api/working", json=payload).json()
    assert saved["working"]["title"] == "Собрать урок 11"
    assert saved["working"]["status"] == "В работе"

    other = client.get("/api/state", params={"session_id": "task-b"}).json()
    assert other["working"]["title"] == ""

    cleared = client.delete("/api/working", params={"session_id": "task-a"}).json()
    assert cleared["removed"] == 1


def test_long_term_upsert_updates_instead_of_duplicating(client) -> None:
    first = client.post(
        "/api/long-term",
        json={"section": "knowledge", "key": "Формат", "value": "кратко"},
    ).json()
    item_id = first["item"]["id"]
    second = client.post(
        "/api/long-term",
        json={
            "section": "knowledge",
            "key": "Формат",
            "value": "структурированно",
            "confidence": 0.95,
        },
    ).json()
    assert second["item"]["id"] == item_id
    assert second["item"]["value"] == "структурированно"
    assert second["item"]["confidence"] == 0.95

    state = client.get("/api/state").json()
    matches = [
        item for item in state["long_term"]["knowledge"] if item["key"] == "Формат"
    ]
    assert len(matches) == 1


def test_context_contains_all_three_layers(client) -> None:
    client.post("/api/message", json={"session_id": "ctx", "content": "Меня зовут Борис"})
    client.post(
        "/api/working",
        json={
            "session_id": "ctx",
            "title": "Урок 11",
            "goal": "Проверить память",
            "status": "В работе",
        },
    )
    client.post(
        "/api/long-term",
        json={"section": "profile", "key": "Город", "value": "Москва"},
    )

    context = client.get("/api/context", params={"session_id": "ctx"}).json()
    prompt = context["system_prompt"]
    assert "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ" in prompt
    assert "РАБОЧАЯ ПАМЯТЬ" in prompt
    assert "КРАТКОСРОЧНАЯ ПАМЯТЬ" in prompt
    assert "Меня зовут Борис" in prompt
    assert "Проверить память" in prompt
    assert "Москва" in prompt
    assert context["messages"][0]["role"] == "system"
    assert context["layers"]["short_term"]["count"] == 1
    assert context["layers"]["long_term"]["count"] <= context["layers"]["long_term"]["available"]


def test_context_reports_empty_layers_explicitly() -> None:
    context = build_context(
        {
            "long_term": {"items": [], "count": 0},
            "working": {},
            "short_term": {"messages": []},
        },
        retrieved=[],
    )
    prompt = context["system_prompt"]
    assert "пусто: релевантных записей не найдено" in prompt
    assert "пусто — задача не задана" in prompt
    assert "пусто — сообщений нет" in prompt
    assert context["layers"]["long_term"]["empty"] is True
    assert context["layers"]["working"]["empty"] is True
    assert context["layers"]["short_term"]["empty"] is True


def test_context_marks_missing_long_term_section() -> None:
    item = {
        "id": 1,
        "section": "profile",
        "key": "Имя",
        "value": "Борис",
        "source": "пользователь",
        "confidence": 0.9,
        "importance": 0.5,
        "updated_at": "2026-11-16T00:00:00+00:00",
    }
    context = build_context(
        {
            "long_term": {"items": [item], "count": 1},
            "working": {},
            "short_term": {"messages": []},
        },
        retrieved=[item],
    )
    prompt = context["system_prompt"]
    assert "РЕШЕНИЯ: сведений не найдено" in prompt
    assert "ЗНАНИЯ: сведений не найдено" in prompt


def test_reset_keeps_long_term_memory(client) -> None:
    before = client.get("/api/state").json()["long_term"]["count"]
    client.post("/api/message", json={"session_id": "reset", "content": "привет"})
    client.post(
        "/api/working",
        json={"session_id": "reset", "title": "Временная задача"},
    )
    result = client.post("/api/chat/reset", json={"session_id": "reset"}).json()
    assert result["state"]["short_term"]["count"] == 0
    assert result["state"]["working"]["title"] == ""
    assert result["state"]["long_term"]["count"] == before


def test_long_term_survives_store_restart(tmp_path) -> None:
    path = tmp_path / "persistent.db"
    first = MemoryStore(path)
    first.upsert_long("demo", "knowledge", "Факт", "Память переживает перезапуск")

    second = MemoryStore(path)
    state = second.state("demo")
    values = {item["key"]: item["value"] for item in state["long_term"]["knowledge"]}
    assert values["Факт"] == "Память переживает перезапуск"


def test_long_term_conflict_keeps_previous_version(store) -> None:
    first = store.upsert_long("demo", "knowledge", "Формат", "кратко")
    second = store.upsert_long("demo", "knowledge", "Формат", "подробно")
    assert first["id"] == second["id"]
    history = store.history("demo", "knowledge", "Формат")
    assert len(history) == 1
    assert history[0]["value"] == "кратко"


def test_long_term_is_isolated_by_owner(store) -> None:
    store.upsert_long("alice", "profile", "Имя", "Алиса")
    store.upsert_long("bob", "profile", "Имя", "Боб")

    alice = store.state("alice")
    bob = store.state("bob")
    assert any(item["value"] == "Алиса" for item in alice["long_term"]["profile"])
    assert not any(item["value"] == "Алиса" for item in bob["long_term"]["profile"])
    assert any(item["value"] == "Боб" for item in bob["long_term"]["profile"])


def test_retrieval_returns_relevant_items(store) -> None:
    store.upsert_long("demo", "knowledge", "Город", "Москва")
    store.upsert_long("demo", "knowledge", "Стек", "FastAPI и Streamlit")
    items = store.retrieve("demo", "Москва", limit=10, max_tokens=1_000)
    assert any(item["key"] == "Город" for item in items)
    assert any("Москва" in item["value"] for item in items)


def test_short_term_ttl_and_secret_rejection(store) -> None:
    store.append_short("demo", "ttl", "user", "временное сообщение", ttl_hours=-1)
    assert store.state("demo", "ttl")["short_term"]["count"] == 0

    with pytest.raises(ValueError, match="секрет"):
        store.upsert_long("demo", "knowledge", "Ключ", "oc_sk_1234567890abcdef")


def test_api_disables_http_cache(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["pragma"] == "no-cache"


def test_chat_uses_layers_and_appends_answer(client, monkeypatch) -> None:
    def fake_chat(messages, model=None):
        assert messages[0]["role"] == "system"
        assert "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ" in messages[0]["content"]
        return (
            "Ответ с учётом памяти",
            "test-model",
            {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366, "estimated": False},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    result = client.post(
        "/api/chat",
        json={"session_id": "chat", "message": "Что ты помнишь?"},
    ).json()
    assert result["answer"] == "Ответ с учётом памяти"
    assert result["model"] == "test-model"
    assert result["question"] == "Что ты помнишь?"
    assert "ДОЛГОВРЕМЕННАЯ ПАМЯТЬ" in result["context"]["system_prompt"]
    assert [item["role"] for item in result["state"]["short_term"]["messages"]] == [
        "user",
        "assistant",
    ]
    assert result["context"]["layers"]["long_term"]["count"] >= 3
    assert result["request_tokens"] == 321
    assert result["response_tokens"] == 45
    assistant = result["state"]["short_term"]["messages"][-1]
    assert assistant["prompt_tokens"] == 321
    assert assistant["completion_tokens"] == 45
