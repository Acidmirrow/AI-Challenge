"""MCP-клиент урока 17: stdio-сессия и вызов get_customer."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REQUEST_TIMEOUT = float(os.getenv("MCP_REQUEST_TIMEOUT", "30"))


class MCPError(RuntimeError):
    """Ошибка подключения или вызова MCP."""


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        env=dict(os.environ),
    )


@asynccontextmanager
async def _session():
    try:
        async with stdio_client(_server_params()) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                yield session
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Не удалось подключиться к MCP-серверу: {exc}") from exc


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return value


async def inspect_server() -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _session() as session:
                initialize = await session.initialize()
                result = await session.list_tools()
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка MCP initialize/tools/list: {exc}") from exc
    server = _dump(initialize.serverInfo) or {}
    tools = [
        {
            "name": _dump(tool).get("name", ""),
            "description": _dump(tool).get("description", ""),
            "input_schema": _dump(tool).get("inputSchema") or {},
        }
        for tool in result.tools
    ]
    return {
        "transport": "stdio",
        "protocol_version": initialize.protocolVersion,
        "server": {"name": server.get("name", ""), "version": server.get("version", "")},
        "capabilities": _dump(initialize.capabilities) or {},
        "tools": tools,
        "tool_count": len(tools),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if not name.strip():
        raise MCPError("Имя инструмента не может быть пустым")
    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _session() as session:
                await session.initialize()
                result = await session.call_tool(name, arguments or {})
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка вызова инструмента {name}: {exc}") from exc
    texts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            texts.append(text)
    return {
        "tool": name,
        "arguments": arguments or {},
        "is_error": bool(getattr(result, "isError", False)),
        "text": "\n".join(texts),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
