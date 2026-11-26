"""Тесты урока 19: композиция MCP-инструментов и остановка пайплайна."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _payload(result: dict) -> dict:
    assert result.get("text")
    return json.loads(result["text"])


def _call(tool: str, arguments: dict | None = None) -> dict:
    response = client.post(
        "/api/mcp/call", json={"tool": tool, "arguments": arguments or {}}
    )
    assert response.status_code == 200
    return _payload(response.json())


def _run(query: str = "MCP инструменты", scenario: str = "none") -> dict:
    response = client.post(
        "/api/pipeline/run", json={"query": query, "scenario": scenario}
    )
    assert response.status_code == 200
    return response.json()


def test_health_reports_pipeline_and_three_tools() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson"] == 19
    assert payload["topic"] == "Композиция MCP инструментов"
    assert payload["tools"] == 3
    assert payload["pipeline"] == ["search", "summarize", "saveToFile"]


def test_mcp_registers_all_pipeline_tools_on_one_server() -> None:
    response = client.post("/api/mcp/inspect")
    assert response.status_code == 200
    payload = response.json()
    assert payload["server"]["name"] == "lesson19-pipeline"
    assert payload["tool_count"] == 3
    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert set(tools) == {"search", "summarize", "saveToFile"}
    assert tools["search"]["input_schema"]["required"] == ["query"]
    assert tools["summarize"]["input_schema"]["required"] == ["results"]
    assert set(tools["saveToFile"]["input_schema"]["required"]) == {"filename", "content"}


def test_search_returns_results_and_empty_scenario_is_explicit() -> None:
    normal = _call("search", {"query": "MCP"})
    assert normal["ok"] is True
    assert normal["count"] >= 1
    assert normal["results"]

    empty = _call("search", {"query": "MCP", "empty": True})
    assert empty["ok"] is True
    assert empty["count"] == 0
    assert empty["results"] == []
    assert empty["empty"] is True


def test_normal_pipeline_executes_all_steps_and_passes_data() -> None:
    result = _run()
    assert result["ok"] is True
    assert result["status"] == "done"
    assert [step["tool"] for step in result["steps"]] == [
        "search",
        "summarize",
        "saveToFile",
    ]

    search_step, summarize_step, save_step = result["steps"]
    assert search_step["status"] == "ok"
    assert summarize_step["status"] == "ok"
    assert save_step["status"] == "ok"
    assert summarize_step["arguments"]["results"] == search_step["result"]["results"]
    assert save_step["arguments"]["content"] == result["output"]
    assert result["file"]["bytes"] > 0

    path = Path(result["file"]["path"])
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip() == result["output"].strip()
    assert "Найдено источников" in result["output"]


def test_empty_search_stops_before_summarize_and_has_no_result() -> None:
    result = _run(scenario="empty_search")
    assert result["ok"] is False
    assert result["status"] == "stopped"
    assert result["stopped_at"] == "search"
    assert result["stopped_step"] == 1
    assert "пустой результат" in result["reason"]
    assert [step["tool"] for step in result["steps"]] == ["search"]
    assert result["steps"][0]["status"] == "empty"
    assert result["output"] is None
    assert result["file"] is None


def test_summarize_error_stops_and_does_not_call_save() -> None:
    result = _run(scenario="summarize_error")
    assert result["ok"] is False
    assert result["stopped_at"] == "summarize"
    assert result["stopped_step"] == 2
    assert [step["tool"] for step in result["steps"]] == ["search", "summarize"]
    assert result["steps"][1]["status"] == "error"
    assert result["output"] is None
    assert result["file"] is None
    assert "принудительная ошибка" in result["reason"]


def test_save_error_is_reported_and_result_is_not_claimed() -> None:
    result = _run(scenario="save_error")
    assert result["ok"] is False
    assert result["stopped_at"] == "saveToFile"
    assert result["stopped_step"] == 3
    assert [step["tool"] for step in result["steps"]] == [
        "search",
        "summarize",
        "saveToFile",
    ]
    assert result["steps"][-1]["status"] == "error"
    assert result["output"] is None
    assert result["file"] is None
    assert "принудительная ошибка" in result["reason"]


def test_query_without_matches_stops_on_empty_search() -> None:
    result = _run(query="нет-такого-слова-12345")
    assert result["ok"] is False
    assert result["stopped_at"] == "search"
    assert len(result["steps"]) == 1
    assert result["output"] is None
