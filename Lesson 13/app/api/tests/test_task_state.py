from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.task_state.domain import TaskNotFound
from app.task_state.service import TaskService
from app.web_search import SearchResult
from app.llm import LLMError
from app.task_state.sqlite_repository import SQLiteTaskRepository

SESSION = {"X-Session-Id": "session-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    service = TaskService(SQLiteTaskRepository(tmp_path / "lesson13.db"))
    monkeypatch.setattr(main, "_task_service", service)
    with TestClient(main.app) as test_client:
        yield test_client


def create(client: TestClient, goal: str = "Подготовить отчёт") -> dict:
    response = client.post("/api/task", headers=SESSION, json={"goal": goal})
    assert response.status_code == 201, response.text
    return response.json()


def transition(
    client: TestClient,
    action: str,
    version: int,
    *,
    plan_text: str | None = None,
) -> dict:
    payload = {"action": action, "version": version}
    if plan_text is not None:
        payload["plan_text"] = plan_text
    return client.post("/api/task/transition", headers=SESSION, json=payload)


def test_health_reports_available_machine(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["state_machine"] == "available"


def test_create_task_starts_in_planning(client: TestClient) -> None:
    task = create(client)
    assert task["stage"] == "planning"
    assert task["version"] == 1
    assert task["expected_action"] == "submit_plan"
    assert "submit_plan" in task["available_actions"]
    assert task["paused"] is False


def test_active_task_cannot_be_created_twice(client: TestClient) -> None:
    create(client)
    response = client.post("/api/task", headers=SESSION, json={"goal": "Другая"})
    assert response.status_code == 409
    assert response.json()["code"] == "active_task_exists"


def test_cannot_start_execution_without_plan(client: TestClient) -> None:
    task = create(client)
    response = transition(client, "start_execution", task["version"])
    assert response.status_code == 409
    assert response.json()["code"] == "guard_failed"
    assert client.get("/api/task", headers=SESSION).json()["stage"] == "planning"


def test_cannot_jump_to_validation_or_done(client: TestClient) -> None:
    task = create(client)
    for action in ("start_validation", "finish"):
        response = transition(client, action, task["version"])
        assert response.status_code == 409
        assert response.json()["code"] == "transition_not_allowed"
    assert client.get("/api/task", headers=SESSION).json()["stage"] == "planning"


def test_full_lifecycle(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(main, "generate_step_result", lambda *args: "Шаг выполнен")
    task = create(client)
    task = transition(client, "submit_plan", task["version"], plan_text="1. Сделать").json()
    assert task["stage"] == "planning"
    assert task["expected_action"] == "approve_plan"

    task = transition(client, "approve_plan", task["version"]).json()
    task = transition(client, "start_execution", task["version"]).json()
    assert task["stage"] == "execution"
    step = client.post("/api/task/step", headers=SESSION)
    assert step.status_code == 200, step.text
    task = step.json()["task"]
    assert task["stage"] == "execution"
    assert task["execution_complete"] is True
    task = transition(client, "start_validation", task["version"]).json()
    assert task["stage"] == "validation"

    task = transition(client, "pass_validation", task["version"]).json()
    assert task["stage"] == "done"
    assert task["done"] is True
    assert task["expected_action"] == "none"


def test_step_failure_returns_reason_and_hint(
    client: TestClient, monkeypatch
) -> None:
    def fail(*_args, **_kwargs):
        raise LLMError(
            "empty_response",
            "Модель вернула пустой ответ",
            hint="Увеличьте max_tokens и повторите шаг",
        )

    monkeypatch.setattr(main, "generate_step_result", fail)
    task = create(client)
    task = transition(client, "submit_plan", task["version"], plan_text="1. Шаг").json()
    task = transition(client, "approve_plan", task["version"]).json()
    task = transition(client, "start_execution", task["version"]).json()
    response = client.post("/api/task/step", headers=SESSION)
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "step_failed"
    assert "Увеличьте max_tokens" in body["hint"]
    assert body["details"]["llm_code"] == "empty_response"


def test_rework_resets_execution_and_validation_flags(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(main, "generate_step_result", lambda *args: "Шаг выполнен")
    task = create(client)
    task = transition(client, "submit_plan", task["version"], plan_text="План").json()
    task = transition(client, "approve_plan", task["version"]).json()
    task = transition(client, "start_execution", task["version"]).json()
    step = client.post("/api/task/step", headers=SESSION)
    assert step.status_code == 200, step.text
    task = step.json()["task"]
    assert task["stage"] == "execution"
    assert task["execution_complete"] is True
    task = transition(client, "start_validation", task["version"]).json()
    assert task["stage"] == "validation"
    task = transition(client, "fail_validation", task["version"]).json()
    assert task["validation_failed"] is True
    assert task["validation_passed"] is False

    task = transition(client, "rework", task["version"]).json()
    assert task["stage"] == "execution"
    assert task["execution_complete"] is False
    assert task["validation_passed"] is False
    assert task["validation_failed"] is False


def test_pause_blocks_mutations_and_resume_keeps_stage(client: TestClient) -> None:
    task = create(client)
    task = transition(client, "submit_plan", task["version"], plan_text="План").json()
    task = client.post("/api/task/pause", headers=SESSION, json={"version": task["version"]}).json()
    assert task["paused"] is True
    assert task["stage"] == "planning"

    blocked = transition(client, "approve_plan", task["version"])
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "task_paused"

    resumed = client.post(
        "/api/task/resume", headers=SESSION, json={"version": task["version"]}
    ).json()
    assert resumed["paused"] is False
    assert resumed["stage"] == "planning"
    assert resumed["current_step"] == task["current_step"]


def test_pause_is_idempotent(client: TestClient) -> None:
    task = create(client)
    first = client.post("/api/task/pause", headers=SESSION, json={"version": task["version"]}).json()
    second = client.post("/api/task/pause", headers=SESSION, json={"version": first["version"]}).json()
    assert first["version"] == second["version"]


def test_version_conflict_does_not_change_state(client: TestClient) -> None:
    task = create(client)
    response = transition(client, "submit_plan", task["version"] + 10, plan_text="План")
    assert response.status_code == 409
    assert response.json()["code"] == "version_conflict"
    assert client.get("/api/task", headers=SESSION).json()["version"] == task["version"]


def test_rejection_is_logged_without_version_increment(client: TestClient) -> None:
    task = create(client)
    transition(client, "start_execution", task["version"])
    history = client.get("/api/task/history", headers=SESSION).json()["items"]
    rejected = [item for item in history if not item["success"]]
    assert rejected
    assert rejected[-1]["error_code"] == "guard_failed"
    assert rejected[-1]["version_before"] == rejected[-1]["version_after"] == task["version"]


def test_sessions_are_isolated(client: TestClient) -> None:
    create(client)
    other = client.get("/api/task", headers={"X-Session-Id": "other-session"})
    assert other.status_code == 404
    assert other.json()["code"] == "task_not_found"


def test_task_requires_session_header(client: TestClient) -> None:
    response = client.get("/api/task")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_chat_receives_task_snapshot_without_mutating_it(client: TestClient, monkeypatch) -> None:
    task = create(client)
    captured = {}

    def fake_chat(messages, model=None):
        captured["messages"] = messages
        return "Ответ", "test-model", {"prompt_tokens": 10, "completion_tokens": 2}

    monkeypatch.setattr(main, "model_chat", fake_chat)
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Что дальше?", "history": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["stage"] == "planning"
    assert "planning" in captured["messages"][0]["content"]
    assert "Ты не можешь сам менять этап" in captured["messages"][0]["content"]
    assert client.get("/api/task", headers=SESSION).json()["stage"] == "planning"


def test_state_persists_across_repository_reopen(tmp_path) -> None:
    path = tmp_path / "persistent.db"
    first = TaskService(SQLiteTaskRepository(path))
    first.create("persistent-session", "Пережить перезапуск")

    second = TaskService(SQLiteTaskRepository(path))
    task = second.get("persistent-session")
    assert task["stage"] == "planning"
    assert task["goal"] == "Пережить перезапуск"


def test_unknown_action_is_structured(client: TestClient) -> None:
    task = create(client)
    response = transition(client, "jump_to_done", task["version"])
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_action"
    assert client.get("/api/task", headers=SESSION).json()["stage"] == "planning"


def test_repository_recovers_after_database_file_is_deleted(tmp_path) -> None:
    path = tmp_path / "recover.db"
    service = TaskService(SQLiteTaskRepository(path))
    service.create("recover-session", "Пересоздать схему")
    path.unlink()

    with pytest.raises(TaskNotFound):
        service.get("recover-session")

    recreated = service.create("recover-session", "Новая схема")
    assert recreated["stage"] == "planning"


def test_chat_web_search_adds_sources_to_prompt(
    client: TestClient, monkeypatch
) -> None:
    create(client)
    captured = {}

    async def fake_search(query: str, limit: int = 5):
        return [SearchResult("Источник", "https://example.com", "Факт")]

    def fake_chat(messages, model=None):
        captured["messages"] = messages
        return "Ответ со ссылкой", "test-model", {"prompt_tokens": 10, "completion_tokens": 2}

    monkeypatch.setattr(main, "search_web", fake_search)
    monkeypatch.setattr(main, "model_chat", fake_chat)
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Что нового?", "history": [], "web_search": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["web_search"]["enabled"] is True
    assert body["web_search"]["used"] is True
    assert body["web_search"]["results"][0]["url"] == "https://example.com"
    assert "https://example.com" in captured["messages"][1]["content"]


def test_chat_web_search_off_does_not_call_search(
    client: TestClient, monkeypatch
) -> None:
    create(client)
    called = {"value": False}

    async def fake_search(query: str, limit: int = 5):
        called["value"] = True
        return []

    def fake_chat(messages, model=None):
        return "Ответ", "test-model", {"prompt_tokens": 10, "completion_tokens": 2}

    monkeypatch.setattr(main, "search_web", fake_search)
    monkeypatch.setattr(main, "model_chat", fake_chat)
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Что нового?", "history": [], "web_search": False},
    )
    assert response.status_code == 200
    assert called["value"] is False
    assert response.json()["web_search"]["enabled"] is False


def test_agent_log_records_creation_and_transition_error(client: TestClient) -> None:
    task = create(client)
    transition(client, "start_execution", task["version"])
    log = client.get("/api/task/log", headers=SESSION)
    assert log.status_code == 200
    items = log.json()["items"]
    assert any(item["kind"] == "task" and item["level"] == "info" for item in items)
    assert any(item["kind"] == "transition" and item["level"] == "error" for item in items)


def test_clarify_asks_questions_and_does_not_plan(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        main,
        "generate_clarification",
        lambda goal, history: {
            "status": "questions",
            "questions": ["Какой результат считается готовым?", "Какие сроки?"],
            "plan": "",
        },
    )
    task = create(client, "Подготовить отчёт")
    response = client.post(
        "/api/task/clarify",
        headers=SESSION,
        json={"history": [{"role": "user", "content": "Подготовить отчёт"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "questions"
    assert body["questions"][0].startswith("Какой результат")
    assert body["task"]["plan_text"] is None
    assert client.get("/api/task", headers=SESSION).json()["plan_text"] is None


def test_clarify_creates_plan_only_after_enough_context(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        main,
        "generate_clarification",
        lambda goal, history: {
            "status": "plan",
            "questions": [],
            "plan": "1. Собрать данные\n2. Проверить",
        },
    )
    task = create(client, "Подготовить отчёт")
    response = client.post(
        "/api/task/clarify",
        headers=SESSION,
        json={
            "history": [
                {"role": "user", "content": "Подготовить отчёт"},
                {"role": "user", "content": "Результат — отчёт DOCX, срок — пятница."},
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "plan"
    assert body["plan"].startswith("1. Собрать данные")
    assert body["task"]["expected_action"] == "approve_plan"


def test_plan_is_explicitly_passed_to_chat_context(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        main,
        "generate_clarification",
        lambda goal, history: {
            "status": "plan",
            "questions": [],
            "plan": "План: собрать данные и проверить",
        },
    )
    task = create(client)
    planned = client.post(
        "/api/task/clarify",
        headers=SESSION,
        json={"history": [{"role": "user", "content": "Подготовить отчёт"}]},
    ).json()
    captured = {}

    def fake_chat(messages, model=None):
        captured["messages"] = messages
        return "Ответ", "test-model", {"prompt_tokens": 10, "completion_tokens": 2}

    monkeypatch.setattr(main, "model_chat", fake_chat)
    client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Что дальше?", "history": []},
    )
    assert planned["plan"].startswith("План:")
    assert planned["plan"] in captured["messages"][0]["content"]


def test_clarification_never_invents_a_plan_from_invalid_text() -> None:
    parsed = main.parse_clarification("Не могу разобрать задачу.", "Цель")
    assert parsed["status"] == "error"
    assert parsed["plan"] == ""
    plain = main.parse_clarification(
        "1. Какой результат нужен?\n2. Какой срок?", "Цель"
    )
    assert plain["status"] == "questions"
    assert len(plain["questions"]) == 2


def test_chat_history_is_persisted_for_task(client: TestClient, monkeypatch) -> None:
    create(client)
    monkeypatch.setattr(
        main,
        "model_chat",
        lambda messages, model=None: (
            "Ответ ассистента",
            "test-model",
            {"prompt_tokens": 10, "completion_tokens": 3},
        ),
    )
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Вопрос по задаче", "history": []},
    )
    assert response.status_code == 200
    history = client.get("/api/chat/history", headers=SESSION).json()["messages"]
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "Вопрос по задаче"
    assert history[1]["content"] == "Ответ ассистента"
