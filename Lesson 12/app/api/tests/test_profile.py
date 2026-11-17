import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.check import audit_answer, random_questions, summarize_audit, topics_for_role
from app.llm import PRO_MODEL
from app.profile import ProfileStore


@pytest.fixture()
def store(tmp_path) -> ProfileStore:
    return ProfileStore(tmp_path / "profile.db")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "store", ProfileStore(tmp_path / "profile.db"))
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_and_personalization_model(client) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["lesson"] == 12
    assert health["auto_enrichment"] is True
    assert "style" in health["preference_keys"]


def test_profile_is_saved_with_history(client) -> None:
    response = client.post(
        "/api/profile",
        json={"owner_id": "alice", "name": "Алиса", "role": "аналитик", "city": "Москва"},
    )
    assert response.status_code == 200
    state = response.json()
    assert state["profile"]["name"] == "Алиса"
    assert state["profile"]["role"] == "аналитик"
    assert any(item["key"] == "name" for item in state["history"])


def test_preferences_are_upserted_and_deleted(client) -> None:
    first = client.post(
        "/api/preferences",
        json={"owner_id": "demo", "key": "format", "value": "кратко"},
    ).json()
    second = client.post(
        "/api/preferences",
        json={"owner_id": "demo", "key": "format", "value": "подробно"},
    ).json()
    assert first["preference_map"]["format"] == "кратко"
    assert second["preference_map"]["format"] == "подробно"

    removed = client.delete("/api/preferences/format").json()
    assert "format" not in removed["preference_map"]


def test_auto_extraction_from_dialogue(store) -> None:
    updates = store.extract_updates(
        "demo",
        "Меня зовут Борис, я работаю разработчиком, живу в Москве. "
        "Отвечай кратко, на ты, без emoji, без примеров кода.",
    )
    keys = {(item["kind"], item["key"]) for item in updates}
    assert ("profile", "name") in keys
    assert ("profile", "role") in keys
    assert ("profile", "city") in keys
    assert ("preference", "format") in keys
    assert ("preference", "style") in keys
    assert ("preference", "emoji") in keys
    assert ("preference", "code_examples") in keys

    state = store.get("demo")
    assert state["profile"]["name"] == "Борис"
    assert state["preference_map"]["format"] == "кратко"
    assert state["preference_map"]["style"] == "обращение на «ты»"
    assert state["preference_map"]["emoji"] == "без emoji"
    assert state["preference_map"]["code_examples"] == "без примеров кода"


def test_chat_auto_enriches_and_injects_profile(client, monkeypatch) -> None:
    captured = {}

    def fake_chat(messages, model=None):
        captured["messages"] = messages
        return (
            "Кратко: профиль учтён.",
            "test-model",
            {"prompt_tokens": 120, "completion_tokens": 12, "total_tokens": 132, "estimated": False},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    result = client.post(
        "/api/chat",
        json={
            "owner_id": "chat-profile",
            "session_id": "chat-profile",
            "message": "Меня зовут Борис, отвечай кратко и без emoji.",
        },
    ).json()

    assert result["updates"]
    assert result["profile"]["profile"]["name"] == "Борис"
    system = captured["messages"][0]["content"]
    assert "Имя: Борис" in system
    assert "Формат ответа: кратко" in system
    assert "Emoji: без emoji" in system
    assert "вне моей компетенции" in system
    assert result["request_tokens"] == 120


def test_empty_profile_is_explicit_in_context(client) -> None:
    context = client.get(
        "/api/context", params={"owner_id": "empty", "session_id": "empty"}
    ).json()
    prompt = context["system_prompt"]
    assert "не заполнено" in prompt
    assert "ПРОФИЛЬ ПУСТ" in prompt


def test_profile_is_isolated_by_owner(store) -> None:
    store.save_profile("alice", {"name": "Алиса"})
    store.save_profile("bob", {"name": "Боб"})
    assert store.get("alice")["profile"]["name"] == "Алиса"
    assert store.get("bob")["profile"]["name"] == "Боб"


def test_secret_is_rejected(store) -> None:
    with pytest.raises(ValueError, match="секрет"):
        store.set_preference("demo", "constraints", "api_key=very-secret-value")


def test_reset_clears_dialogue_but_keeps_profile(client) -> None:
    client.post("/api/profile", json={"owner_id": "reset", "name": "Борис"})
    client.post(
        "/api/chat",
        json={"owner_id": "reset", "session_id": "reset", "message": "привет"},
    )
    result = client.post("/api/chat/reset", json={"owner_id": "reset", "session_id": "reset"}).json()
    assert result["removed"] >= 1
    assert result["state"]["profile"]["name"] == "Борис"
    assert result["messages"] == []


def test_test_profiles_and_delete(store) -> None:
    store.ensure_test_profiles()
    profiles = store.list_profiles()
    ids = {item["owner_id"] for item in profiles}
    assert {"test-alice", "test-elena", "test-ivan", "test-olga"} <= ids
    assert len(profiles) >= 4

    result = store.delete_profile("test-alice")
    assert result["deleted"] == "test-alice"
    assert all(item["owner_id"] != "test-alice" for item in result["profiles"])


def test_context_exposes_code_and_emoji_preferences(client) -> None:
    client.post(
        "/api/preferences",
        json={
            "owner_id": "prefs",
            "key": "code_examples",
            "value": "с примерами кода",
        },
    )
    client.post(
        "/api/preferences",
        json={"owner_id": "prefs", "key": "emoji", "value": "без emoji"},
    )
    context = client.get(
        "/api/context", params={"owner_id": "prefs", "session_id": "prefs"}
    ).json()
    prompt = context["system_prompt"]
    assert "Примеры кода: с примерами кода" in prompt
    assert "Emoji: без emoji" in prompt


def test_profile_check_question_is_unique_and_not_cached(client) -> None:
    first = client.post("/api/profile-check/question", json={"session_id": "s1"})
    second = client.post("/api/profile-check/question", json={"session_id": "s1"})
    assert first.status_code == 200
    assert first.json()["question_id"] != second.json()["question_id"]
    assert first.json()["cached"] is False
    assert "no-store" in first.headers["cache-control"]


def test_audit_counts_real_preference_compliance() -> None:
    prefs = {
        "style": "формальный",
        "format": "таблицей",
        "code_examples": "без примеров кода",
        "emoji": "без emoji",
    }
    good = "Вы можете использовать таблицу.\n\n| A | B |\n|---|---|\n| 1 | 2 |"
    bad = good + "\n```python\nprint('x')\n``` 🚀"
    good_audit = audit_answer(good, prefs)
    bad_audit = audit_answer(bad, prefs)
    assert good_audit["checked"] == 4
    assert good_audit["passed"] == 4
    assert good_audit["compliant"] is True
    assert bad_audit["compliant"] is False
    assert "code_examples" in bad_audit["violations"]
    assert "emoji" in bad_audit["violations"]


def test_summarize_audit_reports_first_violation() -> None:
    ok = {"audit": {"checked": 2, "passed": 2, "compliant": True}}
    bad = {"audit": {"checked": 2, "passed": 1, "compliant": False}}
    summary = summarize_audit([ok, bad, ok])
    assert summary["answers"] == 3
    assert summary["compliant_answers"] == 2
    assert summary["first_violation"] == 2
    assert summary["passed"] == 5


def test_profile_check_all_answers_all_profiles(client, monkeypatch) -> None:
    client.post("/api/profile", json={"owner_id": "check-a", "name": "Анна", "role": "аналитик"})
    client.post("/api/profile", json={"owner_id": "check-b", "name": "Борис", "role": "разработчик"})

    def fake_chat(messages, model=None, max_tokens=1200, temperature=0.4):
        return (
            "Ответ с учётом профиля.",
            model or "flash",
            {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14, "estimated": False},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    result = client.post(
        "/api/profile-check/all",
        json={"question": "Объясни API.", "question_id": "q-test", "session_id": "s1"},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["profiles_count"] == 2
    assert len(body["results"]) == 2
    assert {item["name"] for item in body["results"]} == {"Анна", "Борис"}
    assert all(item["answer"] for item in body["results"])


def test_role_specific_topics() -> None:
    assert "контейнеры Docker" in topics_for_role("разработчик")
    assert "метрики продукта" in topics_for_role("продакт-менеджер")
    assert "дизайн-система" in topics_for_role("дизайнер")
    assert "SQL-запросы" in topics_for_role("аналитик")


def test_batch_questions_match_profile_specialization() -> None:
    profiles = [
        {"owner_id": "product", "role": "продакт-менеджер"},
        {"owner_id": "designer", "role": "дизайнер"},
        {"owner_id": "analyst", "role": "аналитик"},
        {"owner_id": "dev", "role": "разработчик"},
    ]
    items = random_questions(profiles, 10)
    for item in items:
        role = item["profile"]["role"]
        topics = topics_for_role(role)
        assert any(topic.lower() in item["question"].lower() for topic in topics)


def test_profile_check_batch_has_ten_questions_and_different_profiles(
    client, monkeypatch
) -> None:
    for index in range(3):
        client.post(
            "/api/profile",
            json={"owner_id": f"batch-{index}", "name": f"Профиль {index}"},
        )

    def fake_chat(messages, model=None, max_tokens=1200, temperature=0.4):
        return ("Короткий ответ.", model or "flash", {"prompt_tokens": 8, "completion_tokens": 3})

    monkeypatch.setattr(main, "model_chat", fake_chat)
    body = client.post(
        "/api/profile-check/batch", json={"session_id": "s1", "count": 10}
    ).json()
    assert body["count"] == 10
    assert len(body["results"]) == 10
    assert body["profiles_count"] > 1
    assert len({item["question"] for item in body["results"]}) == 10


def test_profile_check_continues_truncated_answer(client, monkeypatch) -> None:
    client.post("/api/profile", json={"owner_id": "cont", "name": "Тест", "role": "разработчик"})
    calls = {"count": 0}

    def fake_chat(messages, model=None, max_tokens=1200, temperature=0.4):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                "Начало ответа и",
                "flash",
                {"finish_reason": "length", "prompt_tokens": 10, "completion_tokens": 5},
            )
        return (
            "продолжение ответа.",
            "flash",
            {"finish_reason": "stop", "prompt_tokens": 10, "completion_tokens": 5},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    body = client.post(
        "/api/profile-check/all",
        json={"question": "Объясни API.", "session_id": "s1"},
    ).json()
    result = body["results"][0]
    assert calls["count"] >= 2
    assert result["answer"].endswith("продолжение ответа.")
    assert result["finish_reason"] == "stop"


def test_profile_check_enforces_code_example(client, monkeypatch) -> None:
    client.post("/api/profile", json={"owner_id": "code", "name": "Ольга", "role": "дизайнер"})
    client.post(
        "/api/preferences",
        json={"owner_id": "code", "key": "code_examples", "value": "с примерами кода"},
    )
    calls = {"count": 0}

    def fake_chat(messages, model=None, max_tokens=1200, temperature=0.4):
        calls["count"] += 1
        if calls["count"] == 1:
            return ("Ответ без примера.", "flash", {"finish_reason": "stop"})
        return (
            "Ответ с примером.\n```html\n<button>OK</button>\n```",
            "flash",
            {"finish_reason": "stop"},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    result = client.post(
        "/api/profile-check/all",
        json={"question": "Как показать кнопку?", "session_id": "s1"},
    ).json()["results"][0]
    assert "```" in result["answer"]
    assert result["code_ok"] is True


def test_context_contains_role_boundary_and_code_hint(client) -> None:
    client.post("/api/profile", json={"owner_id": "role", "role": "дизайнер"})
    client.post(
        "/api/preferences",
        json={"owner_id": "role", "key": "code_examples", "value": "с примерами кода"},
    )
    prompt = client.get(
        "/api/context", params={"owner_id": "role", "session_id": "role"}
    ).json()["system_prompt"]
    assert "ГРАНИЦЫ СПЕЦИАЛИЗАЦИИ" in prompt
    assert "HTML/CSS" in prompt
    assert "Этот вопрос вне моей компетенции" in prompt


def test_profile_check_analysis_uses_pro_model(client, monkeypatch) -> None:
    captured = {}

    def fake_chat(messages, model=None, max_tokens=1200, temperature=0.4):
        captured["model"] = model
        captured["max_tokens"] = max_tokens
        return (
            "Анализ профилей.",
            model or "flash",
            {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )

    monkeypatch.setattr(main, "model_chat", fake_chat)
    items = [
        {
            "owner_id": f"p{index}",
            "name": f"Профиль {index}",
            "question": "Вопрос?",
            "answer": "Ответ.",
            "preferences": {"style": "формальный"},
        }
        for index in range(10)
    ]
    body = client.post(
        "/api/profile-check/analyze", json={"session_id": "s1", "items": items}
    ).json()
    assert body["analysis"] == "Анализ профилей."
    assert body["model"] == PRO_MODEL
    assert body["requested_model"] == PRO_MODEL
    assert captured["model"] == PRO_MODEL
    assert captured["max_tokens"] == 2_500


def test_api_disables_http_cache(client) -> None:
    response = client.get("/api/health")
    assert "no-store" in response.headers["cache-control"]
