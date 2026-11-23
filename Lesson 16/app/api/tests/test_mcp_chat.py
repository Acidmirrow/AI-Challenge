"""Тесты урока 16: встроенные MCP-инструменты и чат через MCP."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.mcp_agent import _yougile_defaults

client = TestClient(app)

EXPECTED_TOOLS = {
    "calculator",
    "current_time",
    "text_stats",
    "currency_rates",
    "unit_converter",
    "date_diff",
    "number_base",
    "number_stats",
    "text_hash",
}


def test_health_reports_nine_lesson06_tools() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson"] == 16
    assert payload["tools"] == 9


def test_mcp_lists_tools_from_lesson06() -> None:
    response = client.post("/api/mcp/inspect")
    assert response.status_code == 200
    payload = response.json()
    assert payload["server"]["name"] == "lesson16-tools"
    assert payload["tool_count"] == 9
    assert {tool["name"] for tool in payload["tools"]} == EXPECTED_TOOLS


def test_chat_uses_mcp_text_stats_tool() -> None:
    response = client.post(
        "/api/chat",
        json={
            "prompt": "Сколько слов в тексте: агент вызывает инструменты по шагам",
            "model": "mock-fast",
            "history": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["stopped_reason"] == "final"
    assert payload["steps"]
    assert payload["steps"][0]["tool"] == "text_stats"
    assert payload["steps"][0]["result"]["ok"] is True
    assert payload["steps"][0]["result"]["result"]["words"] == 9
    assert "Демо-агент" in payload["answer"]


def test_chat_uses_mcp_calculator_tool() -> None:
    response = client.post(
        "/api/chat",
        json={
            "prompt": "Посчитай 17 * 4",
            "model": "mock-fast",
            "history": [
                {"role": "user", "content": "Привет"},
                {"role": "assistant", "content": "Здравствуйте"},
            ],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"][0]["result"]["result"]["value"] == 68


def test_chat_rejects_unknown_model() -> None:
    response = client.post(
        "/api/chat",
        json={"prompt": "Привет", "model": "nope", "history": []},
    )
    assert response.status_code == 400
    assert "Неизвестная модель" in response.json()["detail"]


def test_direct_mcp_call_uses_lesson06_tool() -> None:
    response = client.post(
        "/api/mcp/call",
        json={"tool": "calculator", "arguments": {"expression": "17 * 4"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_error"] is False
    assert '"value": 68' in payload["text"]


def test_yougile_new_tasks_default_to_ai_board_column() -> None:
    name, args = _yougile_defaults(
        "manage_tasks",
        {
            "tasks": [
                {
                    "id": None,
                    "title": "Задача",
                    "columnId": "other-column",
                    "description": "",
                    "color": None,
                    "complete": False,
                    "archived": False,
                }
            ]
        },
    )
    assert name == "manage_tasks"
    assert args["tasks"][0]["columnId"] == "b641afe4-f71a-44f6-8331-85abf1346ba4"


def test_add_task_without_board_is_routed_to_ai_board() -> None:
    name, args = _yougile_defaults("add_task_without_board", {"title": "Без доски", "users": ""})
    assert name == "manage_tasks"
    assert args["tasks"][0]["columnId"] == "b641afe4-f71a-44f6-8331-85abf1346ba4"
    assert args["tasks"][0]["title"] == "Без доски"
