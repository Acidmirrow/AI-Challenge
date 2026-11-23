"""MCP-клиент урока 16: встроенный stdio-сервер и внешний HTTP MCP."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

REQUEST_TIMEOUT = float(os.getenv("MCP_REQUEST_TIMEOUT", "30"))
YOUGILE_URL = "https://ru.yougile.com/data/ai/mcp"


class MCPError(RuntimeError):
    """Ошибка подключения или вызова MCP."""


def _server_params() -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        env=dict(os.environ),
    )


def _external_headers() -> dict[str, str]:
    """OAuth-токен YouGile, полученный Hermes; в чат и файлы проекта не попадает."""

    explicit = os.getenv("YOUGILE_MCP_TOKEN", "").strip()
    if explicit:
        return {"Authorization": f"Bearer {explicit}"}
    path = Path(os.getenv("YOUGILE_TOKEN_FILE", "/srv/data/yougile-token.json"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    token = str(payload.get("access_token") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


@asynccontextmanager
async def _stdio_session():
    try:
        async with stdio_client(_server_params()) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                yield session
    except Exception as exc:  # noqa: BLE001 - ошибку показываем в API/UI
        raise MCPError(f"Не удалось подключиться к stdio MCP-серверу: {exc}") from exc


@asynccontextmanager
async def _http_session(url: str):
    try:
        async with streamablehttp_client(url, headers=_external_headers()) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                yield session
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Не удалось подключиться к MCP {url}: {exc}") from exc


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return value


def _tool_payload(tool: Any) -> dict[str, Any]:
    payload = _dump(tool) or {}
    return {
        "name": payload.get("name", ""),
        "description": payload.get("description", ""),
        "input_schema": payload.get("inputSchema") or {},
    }


async def _inspect(session: ClientSession, transport: str, started: float) -> dict[str, Any]:
    initialize = await session.initialize()
    result = await session.list_tools()
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    server = _dump(initialize.serverInfo) or {}
    tools = [_tool_payload(item) for item in result.tools]
    return {
        "transport": transport,
        "protocol_version": initialize.protocolVersion,
        "server": {"name": server.get("name", ""), "version": server.get("version", "")},
        "capabilities": _dump(initialize.capabilities) or {},
        "instructions": initialize.instructions or "",
        "tools": tools,
        "tool_count": len(tools),
        "duration_ms": duration_ms,
    }


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, Any] | None,
    started: float,
) -> dict[str, Any]:
    await session.initialize()
    result = await session.call_tool(name, arguments or {})
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
        "structured": getattr(result, "structuredContent", None),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def inspect_server() -> dict[str, Any]:
    """initialize + tools/list для локального stdio-сервера урока 16."""

    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _stdio_session() as session:
                return await _inspect(session, "stdio", started)
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка MCP initialize/tools/list: {exc}") from exc


async def inspect_http(url: str = YOUGILE_URL) -> dict[str, Any]:
    """initialize + tools/list для внешнего Streamable HTTP MCP (YouGile)."""

    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _http_session(url) as session:
                result = await _inspect(session, "http", started)
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка внешнего MCP initialize/tools/list: {exc}") from exc
    result["url"] = url
    return result


async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Вызвать инструмент локального stdio-сервера урока 16."""

    if not name.strip():
        raise MCPError("Имя инструмента не может быть пустым")
    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _stdio_session() as session:
                return await _call(session, name, arguments, started)
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка вызова инструмента {name}: {exc}") from exc


async def call_http_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    url: str = YOUGILE_URL,
) -> dict[str, Any]:
    """Вызвать инструмент внешнего MCP (YouGile)."""

    if not name.strip():
        raise MCPError("Имя инструмента не может быть пустым")
    started = time.perf_counter()
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT):
            async with _http_session(url) as session:
                return await _call(session, name, arguments, started)
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"Ошибка внешнего инструмента {name}: {exc}") from exc
