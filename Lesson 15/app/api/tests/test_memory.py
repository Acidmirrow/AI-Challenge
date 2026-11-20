from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.memory import MemoryStore

SESSION = {"X-Session-Id": "memory-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = MemoryStore(tmp_path / "lesson15.db")
    monkeypatch.setattr(main, "_store", store)
    monkeypatch.setattr(
        main,
        "generate_answer",
        lambda question, facts: ("Ответ по актуальной памяти", "test", "prompt"),
    )
    with TestClient(main.app) as test_client:
        yield test_client


def test_replacement_keeps_one_current_fact_and_logs_conflict(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!fact deadline = 30 ноября", "session_id": "memory-test"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["changes"][0]["key"] == "deadline"
    assert data["changes"][0]["old_value"] == "15 декабря"
    assert data["changes"][0]["new_value"] == "30 ноября"
    assert data["changes"][0]["policy"] == "replace"
    facts = client.get("/api/state?session_id=memory-test").json()["facts"]
    deadline = [item for item in facts if item["key"] == "deadline"]
    assert len(deadline) == 1
    assert deadline[0]["value"] == "30 ноября"
    history = client.get("/api/state?session_id=memory-test").json()["history"]
    assert any(
        item["key"] == "deadline"
        and item["old_value"] == "15 декабря"
        and item["new_value"] == "30 ноября"
        for item in history
    )


def test_append_policy_accumulates_decisions(client: TestClient) -> None:
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!decision Выбрали SQLite", "session_id": "memory-test"},
    )
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!decision Добавили проверку", "session_id": "memory-test"},
    )
    facts = client.get("/api/state?session_id=memory-test").json()["facts"]
    decisions = next(item for item in facts if item["key"] == "decisions")
    assert "Выбрали SQLite" in decisions["value"]
    assert "Добавили проверку" in decisions["value"]


def test_prompt_contains_only_current_values(client: TestClient) -> None:
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!fact deadline = 30 ноября", "session_id": "memory-test"},
    )
    prompt = client.get("/api/prompt?session_id=memory-test").json()
    assert "30 ноября" in prompt["prompt"]
    assert "15 декабря" not in prompt["prompt"]
    assert prompt["old_values_in_prompt"] == []


def test_scenario_counts_stale_answers(client: TestClient, monkeypatch) -> None:
    def answer(question: str, facts: list) -> tuple[str, str, str]:
        by_key = {item.key: item.value for item in facts}
        texts = {
            "срок": f"Срок: {by_key['deadline']}",
            "sms": f"SMS: {by_key['sms_requirement']}",
            "подход": f"Подход: {by_key['approach']}",
            "версия": f"Версия: {by_key['version']}",
        }
        for marker, text in texts.items():
            if marker in question.lower():
                return text, "test", "prompt"
        return "ok", "test", "prompt"

    monkeypatch.setattr(main, "generate_answer", answer)
    response = client.post("/api/scenario?session_id=memory-test", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["steps"]) == 4
    assert data["stale_answers"] == 0
    assert data["stale_mentions"] == 0
    assert data["old_values_in_prompt"] == 0


def test_every_replace_fact_keeps_one_current_value(client: TestClient) -> None:
    updates = {
        "deadline": "31 декабря",
        "status": "на проверке",
        "version": "v3",
        "approach": "Автоматическая проверка",
        "sms_requirement": "отменено",
    }
    for key, value in updates.items():
        response = client.post(
            "/api/chat",
            headers=SESSION,
            json={"message": f"!fact {key} = {value}", "session_id": "memory-test"},
        )
        assert response.status_code == 200, response.text
        change = response.json()["changes"][0]
        assert change["policy"] == "replace"
        assert change["new_value"] == value
    facts = client.get("/api/state?session_id=memory-test").json()["facts"]
    for key, value in updates.items():
        matching = [item for item in facts if item["key"] == key]
        assert len(matching) == 1
        assert matching[0]["value"] == value
    prompt = client.get("/api/prompt?session_id=memory-test").json()["prompt"]
    for value in updates.values():
        assert value in prompt
    history = client.get("/api/state?session_id=memory-test").json()["history"]
    assert len([item for item in history if item["key"] in updates]) == len(updates)


def test_natural_status_update_is_replaced(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Статус теперь: на проверке", "session_id": "memory-test"},
    )
    assert response.status_code == 200
    change = response.json()["changes"][0]
    assert change["key"] == "status"
    assert change["new_value"] == "на проверке"
    facts = client.get("/api/state?session_id=memory-test").json()["facts"]
    status = next(item for item in facts if item["key"] == "status")
    assert status["value"] == "на проверке"


def test_change_history_accumulates_each_fact_change(client: TestClient) -> None:
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!fact deadline = 30 ноября", "session_id": "memory-test"},
    )
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!fact version = v2", "session_id": "memory-test"},
    )
    facts = client.get("/api/state?session_id=memory-test").json()["facts"]
    history = next(item for item in facts if item["key"] == "change_history")
    value = history["value"]
    assert "Срок: 15 декабря → 30 ноября" in value
    assert "Версия: v1 → v2" in value


def test_dialog_scenario_combines_replace_and_append(client: TestClient) -> None:
    response = client.post("/api/dialog-scenario?session_id=memory-test", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["steps"]) == 9
    assert data["facts_overwritten"] == 5
    assert data["facts_added"] == 2
    assert data["skipped"] == 1
    assert data["probe_attempted"] is True
    assert "!fact deadline = 30 ноября" in data["steps"][0]["user_message"]
    assert "!decision Выбрали автоматическую проверку" in data["steps"][2]["user_message"]
    assert data["steps"][4]["change"]["skipped"] is True
    assert data["stale_answers"] == 0
    assert data["old_values_in_prompt"] == 0
    decisions = next(
        item for item in data["state"]["facts"] if item["key"] == "decisions"
    )
    assert "Выбрали автоматическую проверку" in decisions["value"]
    assert "Добавили проверку конфликтов" in decisions["value"]



def test_append_scenario_unique_and_duplicate(client: TestClient) -> None:
    first = client.post(
        "/api/append-scenario?session_id=memory-test",
        json={"mode": "unique", "session_id": "memory-test"},
    )
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["added"] == 1
    assert first_data["skipped"] == 0
    assert first_data["decisions_count"] == 2

    second = client.post(
        "/api/append-scenario?session_id=memory-test",
        json={"mode": "unique", "session_id": "memory-test"},
    )
    second_data = second.json()
    assert second_data["added"] == 1
    assert second_data["decisions_count"] == 3

    duplicate = client.post(
        "/api/append-scenario?session_id=memory-test",
        json={"mode": "duplicate", "session_id": "memory-test"},
    )
    duplicate_data = duplicate.json()
    assert duplicate_data["added"] == 0
    assert duplicate_data["skipped"] == 1
    assert duplicate_data["decisions_count"] == 3
    assert "уже есть" in duplicate_data["message"]

def test_complete_task_clears_working_and_short_but_keeps_facts(
    client: TestClient,
) -> None:
    client.post(
        "/api/task/start",
        json={"goal": "Задача", "session_id": "memory-test"},
    )
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Какой срок?", "session_id": "memory-test"},
    )
    before = client.get("/api/state?session_id=memory-test").json()
    assert before["working"]
    assert before["short_term"]
    count = len(before["facts"])
    response = client.post(
        "/api/task/complete", json={"session_id": "memory-test"}
    )
    assert response.status_code == 200
    after = response.json()["state"]
    assert after["working"] == {}
    assert after["short_term"] == []
    assert len(after["facts"]) == count
