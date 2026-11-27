"""MCP-сервер lesson20-analytics: прогноз и статус аналитики."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("lesson20-analytics")

TOOLS = [
    Tool(
        name="forecast",
        description=(
            "Построить прогноз по клиенту и сумме заказа: риск, ожидаемая выручка "
            "и рекомендация."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "customer_id": {"type": "string", "description": "ID клиента"},
                "amount_rub": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Планируемая сумма",
                },
            },
            "required": ["customer_id", "amount_rub"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="get_status",
        description="Статус аналитического сервиса и число доступных моделей прогноза.",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
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
    if name == "forecast":
        customer_id = str(args.get("customer_id") or "").strip().upper()
        if not customer_id:
            return _error("analytics: customer_id обязателен")
        amount = int(args.get("amount_rub") or 0)
        if amount <= 0:
            return _error("analytics: amount_rub должен быть больше нуля")
        risk = 12 if amount < 100_000 else 24
        expected = round(amount * (1 - risk / 100))
        return _text(
            {
                "ok": True,
                "server": "analytics",
                "customer_id": customer_id,
                "amount_rub": amount,
                "risk_pct": risk,
                "expected_revenue_rub": expected,
                "recommendation": "Сделка приоритетная" if risk < 20 else "Нужна проверка",
                "calculated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    if name == "get_status":
        return _text(
            {
                "ok": True,
                "server": "analytics",
                "status": "online",
                "models": ["risk-v2", "revenue-v3"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    return _error(f"Неизвестный инструмент analytics: {name}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
