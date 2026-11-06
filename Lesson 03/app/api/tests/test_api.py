"""Способы рассуждений: разбор ответа, стриминг чата, сравнение стратегий."""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.providers import Provider, ProviderError, ProviderRequest, StreamEvent
from app.strategies import STRATEGIES, STRATEGY_IDS, get_strategy, split_answer

MOCK_MODEL = "mock-fast"
REASONING_MODEL = "mock-reasoner"


class ScriptedProvider(Provider):
    """Провайдер, который отдаёт заранее заданные куски текста."""

    def __init__(self, pieces: list[str] | Exception):
        self.pieces = pieces
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if isinstance(self.pieces, Exception):
            raise self.pieces
        for piece in self.pieces:
            yield StreamEvent("delta", text=piece)
        yield StreamEvent("done", data={"finish_reason": "stop", "completion_tokens": 42})


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        event, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        events.append((event, json.loads(data) if data else {}))
    return events


@pytest.fixture
def client(monkeypatch) -> TestClient:
    provider = ScriptedProvider(["Рассуждаю шаг за шагом. ", "\n---\n", "Ответ: 42"])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    test_client = TestClient(main_module.create_app())
    test_client.provider = provider  # type: ignore[attr-defined]
    return test_client


def chat(client: TestClient, **overrides):
    payload = {
        "model": MOCK_MODEL,
        "messages": [{"role": "user", "content": "Сколько будет 40 + 2?"}],
        "strategy": "cot",
        "temperature": 0.2,
        "reasoning": "off",
        "max_tokens": 512,
    }
    payload.update(overrides)
    return client.post("/api/chat", json=payload)


# -- каталог стратегий --------------------------------------------------------
def test_strategies_catalog(client: TestClient) -> None:
    items = client.get("/api/strategies").json()
    assert [item["id"] for item in items] == list(STRATEGY_IDS)
    assert {item["id"] for item in items} == {
        "direct", "cot", "cot_few_shot", "plan_solve", "self_check",
    }
    assert all(item["system_prompt"] for item in items)
    assert next(item for item in items if item["id"] == "direct")["shows_reasoning"] is False


def test_health_reports_strategies(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["strategies"] == len(STRATEGIES)


def test_free_models_picked_from_remote_list() -> None:
    from app.models_catalog import free_models_from

    gemini = free_models_from("gemini", [
        "gemini-2.5-flash", "gemini-2.5-pro", "text-embedding-004", "gemini-2.0-flash-tts",
    ])
    assert [model.id for model in gemini] == ["gemini-2.5-pro", "gemini-2.5-flash"]


    openrouter = free_models_from("openrouter", [
        "deepseek/deepseek-chat-v3-0324:free", "openai/gpt-4.1", "meta-llama/llama-3.3-70b-instruct:free",
    ])
    assert {model.id for model in openrouter} == {
        "deepseek/deepseek-chat-v3-0324:free", "meta-llama/llama-3.3-70b-instruct:free",
    }
    assert all(model.provider == "openrouter" for model in openrouter)


def test_free_provider_uses_its_own_endpoint() -> None:
    from app.config import Settings
    from app.providers import build_provider
    from app.providers.openai_provider import OpenAIProvider

    settings = Settings(provider="deepseek", deepseek_api_key="k", gemini_api_key="g")
    provider = build_provider(settings, "gemini")
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "gemini"
    assert "generativelanguage.googleapis.com" in str(provider._client.base_url)


def test_models_have_providers(client: TestClient) -> None:
    models = client.get("/api/models").json()
    assert {m["id"] for m in models} >= {"mock-fast", "mock-reasoner"}
    assert all("provider" in m for m in models)


# -- разбор ответа ------------------------------------------------------------
def test_split_answer_marks_reasoning_and_result() -> None:
    strategy = get_strategy("cot")
    reasoning, answer = split_answer(strategy, "шаг 1\nшаг 2\n---\nОтвет: 42")
    assert reasoning == "шаг 1\nшаг 2"
    assert answer == "Ответ: 42"


def test_direct_strategy_has_no_reasoning_part() -> None:
    strategy = get_strategy("direct")
    reasoning, answer = split_answer(strategy, "Ответ: 42\n---\nлишнее")
    assert reasoning == ""
    assert answer.startswith("Ответ: 42")


def test_missing_marker_keeps_whole_text() -> None:
    strategy = get_strategy("self_check")
    reasoning, answer = split_answer(strategy, "просто ответ без разделителя")
    assert answer == ""
    assert reasoning == "просто ответ без разделителя"


def test_unknown_strategy_rejected(client: TestClient) -> None:
    response = chat(client, strategy="telepathy")
    assert response.status_code == 400
    assert "Неизвестный способ рассуждения" in response.json()["detail"]


# -- чат ----------------------------------------------------------------------
def test_chat_streams_deltas_and_splits_answer(client: TestClient) -> None:
    events = parse_sse(chat(client).text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert kinds.count("delta") == 3
    assert kinds[-1] == "result"

    result = events[-1][1]
    assert result["strategy"] == "cot"
    assert result["reasoning_part"] == "Рассуждаю шаг за шагом."
    assert result["answer_part"] == "Ответ: 42"
    assert result["usage"]["completion_tokens"] == 42
    assert result["truncated"] is False


def test_chat_sends_strategy_system_prompt(client: TestClient) -> None:
    chat(client, strategy="plan_solve")
    request = client.provider.requests[-1]  # type: ignore[attr-defined]
    assert request.messages[0]["role"] == "system"
    assert request.messages[0]["content"] == get_strategy("plan_solve").system_prompt
    assert request.messages[1]["content"].startswith("Сколько будет")


def test_chat_passes_temperature_reasoning_and_limit(client: TestClient) -> None:
    chat(client, model=REASONING_MODEL, temperature=0.9, reasoning="high", max_tokens=777)
    request = client.provider.requests[-1]  # type: ignore[attr-defined]
    assert request.temperature == 0.9
    assert request.reasoning == "high"
    assert request.max_tokens == 777


def test_reasoning_level_validated(client: TestClient) -> None:
    response = chat(client, model=REASONING_MODEL, reasoning="ultra")
    assert response.status_code == 400
    assert "reasoning" in response.json()["detail"]


def test_max_tokens_capped_at_ten_thousand(client: TestClient) -> None:
    assert chat(client, max_tokens=10_000).status_code == 200
    assert chat(client, max_tokens=10_001).status_code == 422


def test_empty_history_rejected(client: TestClient) -> None:
    assert chat(client, messages=[]).status_code == 422


def test_provider_error_surfaces_as_event(monkeypatch) -> None:
    def boom(settings, name=None):
        return ScriptedProvider(ProviderError("Провайдер недоступен", kind="connection"))

    monkeypatch.setattr(main_module, "build_provider", boom)
    client = TestClient(main_module.create_app())
    events = parse_sse(chat(client).text)
    assert events[-1][0] == "error"
    assert events[-1][1]["kind"] == "connection"


# -- сравнение стратегий ------------------------------------------------------
def test_compare_runs_every_strategy(client: TestClient) -> None:
    response = client.post(
        "/api/compare",
        json={"model": MOCK_MODEL, "prompt": "Сколько будет 40 + 2?", "reasoning": "off"},
    )
    assert response.status_code == 200
    items = response.json()
    assert [item["strategy"] for item in items] == list(STRATEGY_IDS)
    # direct не делит ответ по маркеру — у него весь текст идёт в answer
    assert all("Ответ: 42" in item["answer"] for item in items)
    assert next(item for item in items if item["strategy"] == "cot")["answer"] == "Ответ: 42"
    assert len(client.provider.requests) == len(STRATEGY_IDS)  # type: ignore[attr-defined]


# -- совет экспертов ----------------------------------------------------------
def test_council_lists_two_groups(client: TestClient) -> None:
    body = client.get("/api/council").json()
    assert [item["id"] for item in body["solvers"]] == [
        "analyst", "engineer", "critic", "manager"
    ]
    assert [item["id"] for item in body["reviewers"]] == ["auditor", "logician", "chair"]
    assert all(item["role"] for item in body["solvers"])


def test_council_answer_uses_role_prompt(client: TestClient) -> None:
    body = client.post(
        "/api/council/answer",
        json={"model": MOCK_MODEL, "prompt": "Сколько будет 2 + 2?", "expert": "analyst"},
    ).json()
    assert body["expert"] == "analyst"
    assert body["strategy"] == "cot"
    assert body["answer"] == "Ответ: 42"
    assert body["reasoning"].startswith("Рассуждаю")
    request = client.provider.requests[-1]  # type: ignore[attr-defined]
    assert "Аналитик" in request.messages[0]["content"]
    assert request.temperature == 0.2


def test_council_answer_rejects_unknown_expert(client: TestClient) -> None:
    response = client.post(
        "/api/council/answer",
        json={"model": MOCK_MODEL, "prompt": "2 + 2", "expert": "nobody"},
    )
    assert response.status_code == 400


def test_council_review_parses_verdicts(monkeypatch) -> None:
    verdicts = (
        '{"verdicts": [{"expert": "analyst", "verdict": "ok", "comment": "сходится"},'
        ' {"expert": "manager", "verdict": "wrong", "comment": "потерял условие"}],'
        ' "final_answer": "12 фруктов"}'
    )
    provider = ScriptedProvider([verdicts])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())
    client.provider = provider  # type: ignore[attr-defined]

    body = client.post(
        "/api/council/review",
        json={
            "model": MOCK_MODEL,
            "prompt": "Сколько фруктов?",
            "reviewer": "auditor",
            "answers": [
                {"id": "analyst", "label": "Аналитик", "answer": "12"},
                {"id": "manager", "label": "Менеджер", "answer": "10"},
            ],
        },
    ).json()
    assert body["parsed"] is True
    assert body["final_answer"] == "12 фруктов"
    assert {item["expert"]: item["verdict"] for item in body["verdicts"]} == {
        "analyst": "ok",
        "manager": "wrong",
    }
    # проверяющий получает задачу и ответы группы
    user_message = client.provider.requests[-1].messages[-1]["content"]  # type: ignore[attr-defined]
    assert "id=analyst" in user_message and "id=manager" in user_message


def test_council_review_survives_broken_json(monkeypatch) -> None:
    provider = ScriptedProvider(["не JSON, просто текст"])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())
    client.provider = provider  # type: ignore[attr-defined]

    body = client.post(
        "/api/council/review",
        json={
            "model": MOCK_MODEL,
            "prompt": "задача",
            "reviewer": "logician",
            "answers": [{"id": "analyst", "label": "Аналитик", "answer": "12"}],
        },
    ).json()
    assert body["parsed"] is False
    assert body["verdicts"] == []
    assert body["raw_text"]


MOCK_SOLVER = "mock-fast"
MOCK_REVIEWER = "mock-reasoner"


def test_cross_check_answers_then_reviews(client: TestClient) -> None:
    response = client.post(
        "/api/cross-check",
        json={
            "prompt": "Сколько будет 17 × 4?",
            "requirement": "extra low",
            "solver_model": MOCK_SOLVER,
            "reviewer_model": MOCK_REVIEWER,
            "max_tokens": 400,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["requirement"] == "extra low"
    assert body["answer"]["label"]
    assert body["answer"]["answer"]
    assert body["review"]["label"]
    assert body["review"]["raw_text"]
    # mock не отвечает JSON по схеме — разбор честно помечается как неудачный
    assert body["review"]["parsed"] is False


def test_cross_check_rejects_unknown_model(client: TestClient) -> None:
    response = client.post(
        "/api/cross-check",
        json={
            "prompt": "2 + 2",
            "solver_model": "нет-такой-модели",
            "reviewer_model": MOCK_REVIEWER,
        },
    )
    assert response.status_code == 400


def test_compare_accepts_subset(client: TestClient) -> None:
    response = client.post(
        "/api/compare",
        json={
            "model": MOCK_MODEL,
            "prompt": "2 + 2",
            "strategies": ["direct", "cot"],
            "reasoning": "off",
        },
    )
    assert [item["strategy"] for item in response.json()] == ["direct", "cot"]
