"""MCP-сервер урока 16.

Сервер публикует встроенные инструменты урока 16 через Model Context Protocol.
Схемы и обработчики находятся в `app.agent_tools`.
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .agent_tools import DEFAULT_REGISTRY, TOOL_LABELS, TOOL_SCHEMAS

server = Server("lesson16-tools")


def _tools() -> list[Tool]:
    result: list[Tool] = []
    for item in TOOL_SCHEMAS:
        function = item["function"]
        result.append(
            Tool(
                name=function["name"],
                description=function.get("description") or "",
                inputSchema=function.get("parameters") or {"type": "object", "properties": {}},
            )
        )
    return result


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _tools()


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    observation = DEFAULT_REGISTRY.execute(name, arguments or {})
    label = TOOL_LABELS.get(name, name)
    text = json.dumps(
        {"tool": name, "label": label, "observation": observation},
        ensure_ascii=False,
    )
    return [TextContent(type="text", text=text)]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
