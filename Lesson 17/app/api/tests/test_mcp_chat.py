"""Тесты урока 17: MCP-инструменты вокруг mock CRM API и агентский вызов."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _call(tool: str, arguments: dict | None = None) -> dict:
    response = client.post("/api/mcp/call", json={"tool": tool, "arguments": arguments or {}})
    assert response.status_code == 200
    return response.json()


def _payload(result: dict) -> dict:
    return json.loads(result["text"])


def test_health_reports_three_tools() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson"] == 17
    assert payload["tools"] == 4
    assert payload["topic"] == "Первый инструмент MCP"


def test_mcp_registers_customer_tools_with_input_schemas() -> None:
    response = client.post("/api/mcp/inspect")
    assert response.status_code == 200
    payload = response.json()
    assert payload["server"]["name"] == "lesson17-crm"
    assert payload["tool_count"] == 4
    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert set(tools) == {"get_customer", "list_customers", "create_customer", "delete_customer"}
    assert tools["get_customer"]["input_schema"]["required"] == ["customer_id"]
    assert tools["list_customers"]["input_schema"]["properties"] == {}
    assert set(tools["create_customer"]["input_schema"]["required"]) == {"name", "email", "plan"}
    assert tools["delete_customer"]["input_schema"]["required"] == ["customer_id"]


def test_direct_mcp_call_returns_customer() -> None:
    payload = _payload(_call("get_customer", {"customer_id": "C-104"}))
    assert payload["ok"] is True
    assert payload["customer"]["name"] == "ООО «Ромашка»"


def test_direct_mcp_call_returns_error_for_unknown_customer() -> None:
    payload = _payload(_call("get_customer", {"customer_id": "C-999"}))
    assert payload["ok"] is False
    assert "не найден" in payload["error"].lower()


def test_list_customers_returns_all_records() -> None:
    payload = _payload(_call("list_customers"))
    assert payload["ok"] is True
    ids = {customer["id"] for customer in payload["customers"]}
    assert "C-104" in ids
    assert payload["count"] >= 1


def test_create_customer_then_get_and_list_it() -> None:
    created = _payload(
        _call(
            "create_customer",
            {
                "name": "ООО «Вектор»",
                "email": "hello@vector.example",
                "plan": "Pro",
                "balance_rub": 5000,
                "open_tickets": 1,
                "manager": "Мария Орлова",
            },
        )
    )
    assert created["ok"] is True
    customer = created["customer"]
    assert customer["id"].startswith("C-")
    assert customer["name"] == "ООО «Вектор»"

    fetched = _payload(_call("get_customer", {"customer_id": customer["id"]}))
    assert fetched["ok"] is True
    assert fetched["customer"]["email"] == "hello@vector.example"

    listed = _payload(_call("list_customers"))
    assert customer["id"] in {item["id"] for item in listed["customers"]}


def test_agent_calls_mcp_tool_and_uses_result() -> None:
    response = client.post(
        "/api/chat",
        json={"prompt": "Что с клиентом C-104?", "model": "mock-fast", "history": []},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"]
    assert payload["steps"][0]["tool"] == "get_customer"
    assert payload["steps"][0]["result"]["ok"] is True
    assert payload["steps"][0]["result"]["customer"]["name"] == "ООО «Ромашка»"
    assert "Наблюдение инструмента" in payload["answer"]


def test_agent_can_list_customers() -> None:
    response = client.post(
        "/api/chat",
        json={"prompt": "Покажи всех клиентов", "model": "mock-fast", "history": []},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"][0]["tool"] == "list_customers"
    assert payload["steps"][0]["result"]["ok"] is True
    assert payload["steps"][0]["result"]["count"] >= 1


def test_agent_can_create_customer() -> None:
    response = client.post(
        "/api/chat",
        json={"prompt": "Добавь клиента", "model": "mock-fast", "history": []},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"][0]["tool"] == "create_customer"
    assert payload["steps"][0]["result"]["ok"] is True


def test_delete_customer_removes_it_from_get_and_list() -> None:
    created = _payload(
        _call(
            "create_customer",
            {"name": "ООО «Удалить»", "email": "delete@example.com", "plan": "Start"},
        )
    )["customer"]
    deleted = _payload(_call("delete_customer", {"customer_id": created["id"]}))
    assert deleted["ok"] is True
    assert deleted["deleted"]["id"] == created["id"]

    missing = _payload(_call("get_customer", {"customer_id": created["id"]}))
    assert missing["ok"] is False
    listed = _payload(_call("list_customers"))
    assert created["id"] not in {item["id"] for item in listed["customers"]}
