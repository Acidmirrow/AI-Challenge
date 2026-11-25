"""MCP-сервер урока 18: сбор, сохранение и чтение снимков метрик.

Инструменты:
- `fetch_metrics` — получить новую порцию демо-метрик;
- `save_snapshot` — сохранить снимок в SQLite;
- `read_snapshots` — прочитать накопленные снимки за период.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import storage

SOURCE = os.getenv("SCHEDULER_SOURCE", "demo-api")
server = Server("lesson18-scheduler")

TOOLS = [
    Tool(
        name="fetch_metrics",
        description=(
            "Получить свежий снимок демо-метрик сервиса: CPU, число запросов, "
            "ошибки, p95-задержку и глубину очереди. Каждый вызов создаёт новый run_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Источник данных, по умолчанию demo-api",
                }
            },
            "additionalProperties": False,
        },
    ),
    Tool(
        name="save_snapshot",
        description=(
            "Сохранить снимок метрик в SQLite. Повторный run_id не создаёт дубликат. "
            "В хранилище остаётся не больше 500 снимков: при превышении самый ранний "
            "удаляется. Возвращает запись, общее число снимков и число вытесненных."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "snapshot": {
                    "type": "object",
                    "description": "Снимок с полями run_id, collected_at, source и метриками",
                    "additionalProperties": True,
                }
            },
            "required": ["snapshot"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="read_snapshots",
        description=(
            "Прочитать накопленные снимки за период. Возвращает все записи периода "
            "в хронологическом порядке, а не только последнюю."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "Начало периода, ISO 8601"},
                "until": {"type": "string", "description": "Конец периода, ISO 8601"},
                "limit": {
                    "type": "integer",
                    "description": "Максимум записей, по умолчанию 500",
                    "minimum": 1,
                    "maximum": 5000,
                },
            },
            "additionalProperties": False,
        },
    ),
]


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _error(message: str) -> list[TextContent]:
    return _text({"ok": False, "error": message})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_metrics(source: str | None = None) -> dict[str, Any]:
    """Детерминированная по форме, но меняющаяся по значениям порция метрик."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"run-{stamp}-{uuid4().hex[:6]}"
    return {
        "run_id": run_id,
        "collected_at": _now(),
        "source": (source or SOURCE).strip() or SOURCE,
        "window": "5m",
        "cpu_pct": round(random.uniform(8.0, 92.0), 1),
        "requests": random.randint(60, 420),
        "errors": random.randint(0, 14),
        "latency_ms": round(random.uniform(65.0, 480.0), 1),
        "queue_depth": random.randint(0, 36),
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    try:
        if name == "fetch_metrics":
            snapshot = collect_metrics(args.get("source"))
            return _text({"ok": True, "snapshot": snapshot})

        if name == "save_snapshot":
            snapshot = args.get("snapshot")
            if not isinstance(snapshot, dict):
                return _error("snapshot должен быть объектом")
            saved = storage.save_snapshot(snapshot)
            return _text({"ok": True, "snapshot": saved, "total": saved["total"]})

        if name == "read_snapshots":
            result = storage.read_snapshots(
                since=args.get("since"),
                until=args.get("until"),
                limit=int(args.get("limit") or 500),
            )
            return _text({"ok": True, **result})

        return _error(f"Неизвестный инструмент: {name}")
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        return _error(f"Ошибка инструмента {name}: {exc}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
