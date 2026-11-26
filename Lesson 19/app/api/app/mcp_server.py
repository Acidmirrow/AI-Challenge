"""MCP-сервер урока 19: search → summarize → saveToFile.

Один сервер предоставляет три инструмента, которые образуют пайплайн.
Инструменты поддерживают управляемые сбои (`empty`, `fail`), чтобы показать
остановку цепочки на нужном шаге.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

OUTPUT_DIR = Path(os.getenv("PIPELINE_OUTPUT_DIR", "/srv/data/output"))
server = Server("lesson19-pipeline")

CORPUS = [
    {
        "id": "doc-1",
        "title": "MCP: протокол инструментов",
        "url": "https://modelcontextprotocol.io/docs",
        "snippet": "MCP описывает, как приложение передаёт модели инструменты и получает результаты их вызова.",
    },
    {
        "id": "doc-2",
        "title": "Композиция инструментов",
        "url": "https://example.local/mcp/composition",
        "snippet": "Цепочка инструментов строится последовательно: результат предыдущего шага становится входом следующего.",
    },
    {
        "id": "doc-3",
        "title": "Обработка ошибок в пайплайне",
        "url": "https://example.local/mcp/errors",
        "snippet": "Если шаг вернул ошибку или пустые данные, следующие шаги не должны запускаться.",
    },
    {
        "id": "doc-4",
        "title": "MCP и сохранение результатов",
        "url": "https://example.local/mcp/storage",
        "snippet": "Инструмент сохранения принимает подготовленный результат и записывает его в файл.",
    },
]

TOOLS = [
    Tool(
        name="search",
        description=(
            "Найти документы по запросу. Возвращает список результатов с title, "
            "url и snippet. При empty=true возвращает пустой список."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "empty": {
                    "type": "boolean",
                    "description": "Принудительно вернуть пустой результат для проверки остановки",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="summarize",
        description=(
            "Сделать краткую сводку по результатам поиска. При fail=true возвращает "
            "управляемую ошибку, чтобы проверить остановку пайплайна."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "description": "Результаты предыдущего шага search",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "fail": {
                    "type": "boolean",
                    "description": "Принудительно вернуть ошибку",
                },
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="saveToFile",
        description=(
            "Сохранить итоговый текст в файл. При fail=true возвращает управляемую "
            "ошибку и ничего не записывает."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла"},
                "content": {"type": "string", "description": "Содержимое результата"},
                "fail": {
                    "type": "boolean",
                    "description": "Принудительно вернуть ошибку сохранения",
                },
            },
            "required": ["filename", "content"],
            "additionalProperties": False,
        },
    ),
]


def _text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _error(message: str) -> list[TextContent]:
    return _text({"ok": False, "error": message})


def _safe_filename(value: Any) -> str:
    name = Path(str(value or "pipeline-summary.md")).name.strip()
    if not name or name in {".", ".."}:
        return "pipeline-summary.md"
    return name


def _search(query: str, empty: bool = False) -> dict[str, Any]:
    query = query.strip()
    if empty:
        results: list[dict[str, str]] = []
    else:
        words = [word.lower() for word in query.split() if word.strip()]
        results = [
            dict(item)
            for item in CORPUS
            if not words
            or any(
                word in f"{item['title']} {item['snippet']}".lower()
                for word in words
            )
        ]
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "empty": not results,
        "results": results,
    }


def _summarize(results: Any, fail: bool = False) -> dict[str, Any]:
    if fail:
        return {"ok": False, "error": "summarize: принудительная ошибка обработки"}
    if not isinstance(results, list):
        return {"ok": False, "error": "summarize: results должен быть массивом"}
    if not results:
        return {"ok": False, "error": "summarize: нет данных для обработки"}
    lines = [f"Найдено источников: {len(results)}", "", "Краткая сводка:"]
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            return {"ok": False, "error": "summarize: некорректный элемент results"}
        title = str(item.get("title") or "Без названия")
        snippet = str(item.get("snippet") or "").strip()
        lines.append(f"{index}. {title}: {snippet}")
    return {
        "ok": True,
        "source_count": len(results),
        "summary": "\n".join(lines),
    }


def _save(filename: Any, content: Any, fail: bool = False) -> dict[str, Any]:
    if fail:
        return {"ok": False, "error": "saveToFile: принудительная ошибка сохранения"}
    text = str(content or "").strip()
    if not text:
        return {"ok": False, "error": "saveToFile: пустой результат не сохраняется"}
    name = _safe_filename(filename)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    path.write_text(text + "\n", encoding="utf-8")
    return {
        "ok": True,
        "filename": name,
        "path": str(path),
        "bytes": len(path.read_bytes()),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    args = arguments or {}
    try:
        if name == "search":
            query = str(args.get("query") or "").strip()
            if not query:
                return _error("search: query обязателен")
            return _text(_search(query, bool(args.get("empty"))))

        if name == "summarize":
            return _text(_summarize(args.get("results"), bool(args.get("fail"))))

        if name == "saveToFile":
            return _text(
                _save(
                    args.get("filename"),
                    args.get("content"),
                    bool(args.get("fail")),
                )
            )

        return _error(f"Неизвестный инструмент: {name}")
    except (OSError, ValueError, TypeError) as exc:
        return _error(f"Ошибка инструмента {name}: {exc}")


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
