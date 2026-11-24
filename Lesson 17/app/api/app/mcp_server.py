"""MCP-сервер урока 17: инструменты вокруг mock CRM API.

Зарегистрированы три инструмента:
- `get_customer` — карточка одного клиента;
- `list_customers` — все клиенты;
- `create_customer` — добавление клиента.

Сервер не хранит данные сам: он обращается к HTTP API приложения.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

MOCK_API_URL = os.getenv("MOCK_API_URL", "http://127.0.0.1:8000/mock")
TIMEOUT = float(os.getenv("MOCK_API_TIMEOUT", "10"))

server = Server("lesson17-crm")

TOOLS = [
    Tool(
        name="get_customer",
        description=(
            "Получить карточку клиента CRM по идентификатору: имя, тариф, "
            "баланс, количество открытых обращений и менеджера."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Идентификатор клиента в формате C-104",
                    "pattern": "^C-\\d+$",
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="list_customers",
        description="Получить список всех клиентов CRM с их тарифом и балансом.",
        inputSchema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    ),
    Tool(
        name="create_customer",
        description=(
            "Добавить нового клиента в CRM. Обязательны name, email и plan; "
            "баланс, число обращений и менеджер можно не указывать."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Название компании или ФИО клиента"},
                "email": {"type": "string", "description": "Контактный email"},
                "plan": {
                    "type": "string",
                    "description": "Тариф клиента",
                    "enum": ["Start", "Pro", "Enterprise"],
                },
                "balance_rub": {
                    "type": "integer",
                    "description": "Баланс в рублях",
                    "minimum": 0,
                },
                "open_tickets": {
                    "type": "integer",
                    "description": "Количество открытых обращений",
                    "minimum": 0,
                },
                "manager": {"type": "string", "description": "Менеджер клиента"},
            },
            "required": ["name", "email", "plan"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="delete_customer",
        description="Удалить клиента CRM по идентификатору.",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Идентификатор клиента в формате C-104",
                    "pattern": "^C-\\d+$",
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
    ),
]


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _error(message: str) -> list[TextContent]:
    return _text({"ok": False, "error": message})


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(method, f"{MOCK_API_URL}{path}", json=payload)
    if response.status_code >= 400:
        detail = response.text[:300]
        try:
            detail = response.json().get("detail") or detail
        except ValueError:
            pass
        raise ValueError(f"CRM API вернул {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("CRM API вернул не JSON") from exc


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    try:
        if name == "get_customer":
            customer_id = str(args.get("customer_id") or "").strip().upper()
            if not customer_id:
                return _error("customer_id обязателен")
            customer = await _request("GET", f"/customers/{customer_id}")
            return _text({"ok": True, "customer": customer})

        if name == "list_customers":
            customers = await _request("GET", "/customers")
            return _text({"ok": True, "count": len(customers), "customers": customers})

        if name == "delete_customer":
            customer_id = str(args.get("customer_id") or "").strip().upper()
            if not customer_id:
                return _error("customer_id обязателен")
            deleted = await _request("DELETE", f"/customers/{customer_id}")
            return _text({"ok": True, "deleted": deleted})

        if name == "create_customer":
            if not str(args.get("name") or "").strip():
                return _error("name обязателен")
            if not str(args.get("email") or "").strip():
                return _error("email обязателен")
            if not str(args.get("plan") or "").strip():
                return _error("plan обязателен")
            payload = {
                "name": str(args["name"]).strip(),
                "email": str(args["email"]).strip(),
                "plan": str(args["plan"]).strip(),
                "balance_rub": int(args.get("balance_rub") or 0),
                "open_tickets": int(args.get("open_tickets") or 0),
                "manager": str(args.get("manager") or "").strip(),
            }
            customer = await _request("POST", "/customers", payload)
            return _text({"ok": True, "customer": customer})

        return _error(f"Неизвестный инструмент: {name}")
    except (httpx.HTTPError, ValueError) as exc:
        return _error(f"CRM API недоступен: {exc}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
