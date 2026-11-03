"""API-контракт урока 02: каталоги, SSE-прогон форматов, авто-исправление."""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.providers.base import Provider, ProviderError, ProviderRequest, StreamEvent

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "year": {"type": "integer"},
        "rating": {"type": "number"},
    },
    "required": ["title", "year", "rating"],
    "additionalProperties": False,
}


class ScriptedProvider(Provider):
    """Отдаёт заранее заданные ответы (или исключения) по очереди."""

    name = "scripted"

    def __init__(self, outputs: list[str | Exception]):
        self._outputs = outputs
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        output = self._outputs[min(len(self.requests) - 1, len(self._outputs) - 1)]
        if isinstance(output, Exception):
            raise output
        yield StreamEvent("delta", text=output)
        yield StreamEvent("done", data={"model": request.model, "finish_reason": "stop", "elapsed_ms": 1})


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
def client(monkeypatch) -> TestClient:
    provider = ScriptedProvider(['{"title": "Матрица", "year": 1999, "rating": 8.7}'])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    return TestClient(main_module.create_app())


def run(client: TestClient, **overrides):
    payload = {
        "format": "json_object",
        "model": "mock-reasoner",
        "prompt": "Матрица 1999 рейтинг 8.7",
        "schema": SCHEMA,
        "schema_name": "movie",
        "temperature": 0.2,
        "reasoning": "off",
    }
    payload.update(overrides)
    return client.post("/api/format/run", json=payload)


def test_formats_catalog(client: TestClient) -> None:
    formats = client.get("/api/formats").json()
    ids = [item["id"] for item in formats]
    assert ids == ["text", "markdown", "json_object", "json_schema", "tool_call"]
    assert next(f for f in formats if f["id"] == "tool_call")["uses_tools"] is True
    # явное описание формата отдаётся наружу, чтобы UI показал его в поле
    assert all(f["default_instruction"] for f in formats)


def test_presets_are_valid_schemas(client: TestClient) -> None:
    from app.validation import check_schema

    for preset in client.get("/api/presets").json():
        check_schema(preset["schema"])


def test_models_have_provider_and_levels(client: TestClient) -> None:
    models = client.get("/api/models").json()
    assert {m["id"] for m in models} >= {"mock-fast", "mock-reasoner"}
    assert all("provider" in m for m in models)


def test_json_object_run_is_valid(client: TestClient) -> None:
    events = parse_sse(run(client).text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "start"
    assert kinds[-1] == "result"
    result = events[-1][1]
    assert result["parsed"]["title"] == "Матрица"
    assert result["validation"]["valid"] is True
    assert result["runs"] == 1
    assert result["sent"]["response_format"] == {"type": "json_object"}


def test_validation_failure_is_reported(monkeypatch) -> None:
    provider = ScriptedProvider(['{"title": "Матрица"}'])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())

    events = parse_sse(run(client).text)
    result = events[-1][1]
    assert result["validation"]["valid"] is False
    assert {item["path"] for item in result["validation"]["errors"]} == {"year", "rating"}
    # авто-ремонта больше нет: один запрос, без события repair
    assert len(provider.requests) == 1
    assert "repair" not in [kind for kind, _ in events]


def test_unsupported_format_surfaces_provider_error(monkeypatch) -> None:
    error = ProviderError(
        "Провайдер отклонил параметры запроса: This response_format type is unavailable now",
        kind="bad_request",
    )
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: ScriptedProvider([error]))
    client = TestClient(main_module.create_app())

    events = parse_sse(run(client, format="json_schema").text)
    assert events[-1][0] == "error"
    assert events[-1][1]["kind"] == "bad_request"
    assert "json_object" in events[-1][1]["message"]


def test_schema_is_required_for_structured_formats(client: TestClient) -> None:
    response = run(client, format="json_object", schema=None)
    assert response.status_code == 400
    assert "требует JSON Schema" in response.json()["detail"]


def test_invalid_schema_rejected(client: TestClient) -> None:
    response = run(client, schema={"type": "nope"})
    assert response.status_code == 400
    assert "JSON Schema" in response.json()["detail"]


def test_unknown_model_and_format(client: TestClient) -> None:
    assert run(client, model="nope").status_code == 400
    assert run(client, format="yaml").status_code == 422


def test_stop_and_system_prompt_reach_provider(monkeypatch) -> None:
    provider = ScriptedProvider(['{"title": "Матрица", "year": 1999, "rating": 8.7}'])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())

    run(client, stop=["\n\n"], system_prompt="Ответь строго JSON.")
    request = provider.requests[-1]
    assert request.stop == ["\n\n"]
    system = request.messages[0]["content"]
    assert system.startswith("Ответь строго JSON.")
    assert "JSON Schema" in system  # схема дописывается к явному описанию формата


def test_single_request_and_summary(monkeypatch) -> None:
    provider = ScriptedProvider(['{"title": "Матрица", "year": 1999, "rating": 8.7}'])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())

    result = parse_sse(run(client).text)[-1][1]
    assert len(provider.requests) == 1  # один прогон — один запрос
    assert result["runs"] == 1
    assert len(result["results"]) == 1
    assert result["summary"]["runs"] == 1
    assert result["summary"]["parseable"] == 1
    assert result["summary"]["valid"] == 1


def test_truncated_flag_when_output_hits_limit(monkeypatch) -> None:
    class LengthProvider(Provider):
        async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
            yield StreamEvent("delta", text='{"title": "Ма')
            yield StreamEvent("done", data={"finish_reason": "length", "completion_tokens": 16})

    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: LengthProvider())
    client = TestClient(main_module.create_app())

    result = parse_sse(run(client, max_tokens=100).text)[-1][1]
    assert result["truncated"] is True
    assert result["limit"] == {"truncated": True, "max_tokens": 100}
    assert result["parse_check"]["ok"] is False


def test_max_tokens_capped_at_ten_thousand(client: TestClient) -> None:
    assert run(client, max_tokens=10_000).status_code == 200
    assert run(client, max_tokens=10_001).status_code == 422
    assert run(client, max_tokens=32_768).status_code == 422


def test_parse_check_present_for_plain_text(monkeypatch) -> None:
    provider = ScriptedProvider(["Просто текст без структуры."])
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
    client = TestClient(main_module.create_app())

    result = parse_sse(run(client, format="text", schema=None).text)[-1][1]
    assert result["parse_check"]["ok"] is False
    assert result["parse_check"]["kind"] == "text"


def test_tool_call_flow_uses_tool_delta(monkeypatch) -> None:
    class ToolProvider(Provider):
        async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
            yield StreamEvent("tool_delta", text='{"title": "Матрица", ')
            yield StreamEvent("tool_delta", text='"year": 1999, "rating": 8.7}')
            yield StreamEvent("done", data={"finish_reason": "tool_calls", "tool_name": "save_movie"})

    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: ToolProvider())
    client = TestClient(main_module.create_app())

    events = parse_sse(run(client, format="tool_call", tool_name="save_movie").text)
    kinds = [kind for kind, _ in events]
    assert kinds.count("delta") >= 2
    result = events[-1][1]
    assert result["tool_call"]["name"] == "save_movie"
    assert result["parsed"]["year"] == 1999
    assert result["validation"]["valid"] is True
