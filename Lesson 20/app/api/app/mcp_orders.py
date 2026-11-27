"""MCP-сервер lesson20-orders: клиенты и заказы."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("lesson20-orders")

CUSTOMERS = {
    "C-104": {
        "id": "C-104",
        "name": "ООО «Ромашка»",
        "plan": "Pro",
        "balance_rub": 128000,
        "manager": "Анна Смирнова",
    },
    "C-207": {
        "id": "C-207",
        "name": "ИП Волков",
        "plan": "Start",
        "balance_rub": 0,
        "manager": "Илья Петров",
    },
}
ORDERS: list[dict[str, Any]] = [
    {"id": "O-1001", "customer_id": "C-104", "amount_rub": 84000, "status": "paid"},
    {"id": "O-1002", "customer_id": "C-104", "amount_rub": 16000, "status": "new"},
]


TOOLS = [
    Tool(
        name="get_customer",
        description="Получить клиента из CRM заказов по идентификатору.",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {
                    "type": "string",
                    "description": "Идентификатор клиента, например C-104",
                    "pattern": "^C-\\d+$",
                }
            },
            "required": ["customer_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_status",
        description="Статус сервиса заказов: онлайн, количество заказов и последний заказ.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="create_order",
        description="Создать новый заказ для клиента.",
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "ID клиента"},
                "amount_rub": {"type": "integer", "minimum": 1, "description": "Сумма заказа"},
            },
            "required": ["customer_id", "amount_rub"],
            "additionalProperties": False,
        },
    ),
]


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _error(message: str) -> list[TextContent]:
    return _text({"ok": False, "error": message})


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    if name == "get_customer":
        customer_id = str(args.get("customer_id") or "").strip().upper()
        customer = CUSTOMERS.get(customer_id)
        if customer is None:
            return _error("orders: клиент не найден")
        return _text({"ok": True, "server": "orders", "customer": customer})

    if name == "get_status":
        return _text(
            {
                "ok": True,
                "server": "orders",
                "status": "online",
                "orders_count": len(ORDERS),
                "last_order": ORDERS[-1] if ORDERS else None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    if name == "create_order":
        customer_id = str(args.get("customer_id") or "").strip().upper()
        if customer_id not in CUSTOMERS:
            return _error("orders: клиент не найден")
        order = {
            "id": f"O-{1000 + len(ORDERS) + 1}-{uuid4().hex[:3]}",
            "customer_id": customer_id,
            "amount_rub": int(args.get("amount_rub") or 0),
            "status": "new",
        }
        ORDERS.append(order)
        return _text({"ok": True, "server": "orders", "order": order})

    return _error(f"Неизвестный инструмент orders: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
