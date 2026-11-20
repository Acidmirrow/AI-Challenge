from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.invariants import InvariantStore, check_text
from app.invariants.domain import BYPASS_PROMPTS

SESSION = {"X-Session-Id": "invariant-test"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = InvariantStore(tmp_path / "lesson14.db")
    monkeypatch.setattr(main, "_store", store)
    with TestClient(main.app) as test_client:
        yield test_client


def test_default_invariants_are_stored_separately(client: TestClient) -> None:
    response = client.get("/api/invariants")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 5
    assert {item["id"] for item in items} >= {"INV-001", "INV-002", "INV-004"}


def test_conflicting_request_is_refused_by_code(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Предлагаю перейти на PostgreSQL вместо SQLite."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "refuse"
    assert data["source"] == "code_precheck"
    assert any(item["id"] == "INV-002" for item in data["violations"])
    assert "Не могу" in data["answer"]


def test_benign_request_is_sent_to_model(client: TestClient, monkeypatch) -> None:
    def answer(*_args, **_kwargs):
        return {
            "decision": "allow",
            "invariants_considered": ["INV-001", "INV-002"],
            "reasoning": "REST и SQLite соответствуют ограничениям.",
            "answer": "Документируйте REST-контракт и храните данные в SQLite.",
        }

    monkeypatch.setattr(main, "generate_guarded_answer", answer)
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Как документировать REST API в текущем стеке?"},
    )
    data = response.json()
    assert data["decision"] == "allow"
    assert data["source"] == "model"
    assert data["invariants_considered"] == ["INV-001", "INV-002"]


def test_model_answer_violating_invariant_is_blocked_postcheck(
    client: TestClient, monkeypatch
) -> None:
    def answer(*_args, **_kwargs):
        return {
            "decision": "allow",
            "invariants_considered": [],
            "reasoning": "",
            "answer": "Для ускорения можно добавить Redis.",
        }

    monkeypatch.setattr(main, "generate_guarded_answer", answer)
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "Как ускорить кэширование?"},
    )
    data = response.json()
    assert data["decision"] == "refuse"
    assert data["source"] == "postcheck"
    assert any(item["id"] == "INV-002" for item in data["violations"])


def test_invariant_change_requires_explicit_command(client: TestClient) -> None:
    bad = client.post(
        "/api/invariants/change",
        headers=SESSION,
        json={"command": "измени INV-002", "reason": "диалог"},
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "command_required"

    good = client.post(
        "/api/invariants/change",
        headers=SESSION,
        json={
            "command": "!invariant INV-002 => Можно использовать SQLite и PostgreSQL.",
            "reason": "Пилотное решение",
            "changed_by": "operator",
        },
    )
    assert good.status_code == 200, good.text
    data = good.json()
    assert data["invariant"]["id"] == "INV-002"
    assert data["old_statement"] != data["new_statement"]
    history = client.get("/api/invariants/history").json()["items"]
    assert history[0]["invariant_id"] == "INV-002"
    assert history[0]["changed_by"] == "operator"


def test_chat_cannot_change_invariant(client: TestClient) -> None:
    response = client.post(
        "/api/chat",
        headers=SESSION,
        json={"message": "!invariant INV-002 => PostgreSQL разрешён."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "refuse"
    assert data["source"] == "chat_change_blocked"
    items = client.get("/api/invariants").json()["items"]
    invariant = next(item for item in items if item["id"] == "INV-002")
    assert "PostgreSQL разрешён" not in invariant["statement"]


def test_bypass_prompts_report_known_bypass(client: TestClient) -> None:
    response = client.post("/api/bypass-test", headers=SESSION, json={})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == len(BYPASS_PROMPTS) == 9
    assert data["blocked"] == 8
    assert data["escaped"] == 1
    escaped = [item for item in data["results"] if not item["blocked"]]
    assert len(escaped) == 1
    assert escaped[0]["label"] == "managed_db"
    stats = client.get("/api/attempts", headers=SESSION).json()["stats"]
    assert stats["total"] >= 9
    assert stats["blocked"] >= 8


def test_checker_ignores_negated_mentions(tmp_path) -> None:
    items = InvariantStore(tmp_path / "checker.db").list_invariants()
    assert check_text("Не используйте PostgreSQL; остаёмся на SQLite.", items) == []
    assert check_text("Используйте PostgreSQL.", items)
