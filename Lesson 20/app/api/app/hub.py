"""Мультисерверный MCP-хаб урока 20.

Хаб открывает несколько stdio-соединений, собирает инструменты в один каталог,
разрешает одинаковые имена через `server__tool` и маршрутизирует вызовы обратно
в нужное соединение. Недоступный сервер не блокирует остальные.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

CONNECT_TIMEOUT = 25.0
CALL_TIMEOUT = 30.0


@dataclass(frozen=True)
class ServerSpec:
    name: str
    label: str
    module: str
    external: bool = False
    args: tuple[str, ...] = ()

    def params(self) -> StdioServerParameters:
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", self.module, *self.args],
            env=dict(__import__("os").environ),
        )


SERVERS = (
    ServerSpec("orders", "Заказы", "app.mcp_orders"),
    ServerSpec("analytics", "Аналитика", "app.mcp_analytics"),
    ServerSpec(
        "time",
        "Time (внешний reference-сервер)",
        "mcp_server_time",
        external=True,
    ),
)


def _dump(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(exclude_none=True)
    return value


def _payload(result: Any) -> dict[str, Any]:
    texts = [
        getattr(block, "text", None)
        for block in (getattr(result, "content", None) or [])
        if getattr(block, "text", None) is not None
    ]
    text = "\n".join(texts)
    try:
        parsed = json.loads(text) if text else None
    except json.JSONDecodeError:
        parsed = None
    if not isinstance(parsed, dict):
        parsed = {"ok": not bool(getattr(result, "isError", False)), "text": text}
    elif "ok" not in parsed:
        parsed = {**parsed, "ok": not bool(getattr(result, "isError", False))}
    if getattr(result, "isError", False):
        parsed = {"ok": False, "error": str(parsed.get("error") or text or "MCP error")}
    return parsed


class MCPHub:
    """Один запрос — все соединения, затем гарантированное закрытие."""

    def __init__(self, disabled: list[str] | None = None) -> None:
        self.disabled = set(disabled or [])
        self._stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.failures: dict[str, str] = {}
        self.tools: list[dict[str, Any]] = []
        self.routes: dict[str, dict[str, Any]] = {}
        self._pending: list[dict[str, Any]] = []

    async def __aenter__(self) -> "MCPHub":
        await self._stack.__aenter__()
        try:
            await self.connect()
        except Exception:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        await self._stack.aclose()

    async def connect(self) -> None:
        for spec in SERVERS:
            if spec.name in self.disabled:
                self.failures[spec.name] = "сервер отключён для проверки отказа"
                self.snapshots[spec.name] = {
                    "name": spec.name,
                    "label": spec.label,
                    "external": spec.external,
                    "connected": False,
                    "tool_count": 0,
                    "error": self.failures[spec.name],
                    "tools": [],
                }
                continue
            started = time.perf_counter()
            try:
                async with asyncio.timeout(CONNECT_TIMEOUT):
                    read, write = await self._stack.enter_async_context(
                        stdio_client(spec.params())
                    )
                    session = await self._stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    initialize = await session.initialize()
                    result = await session.list_tools()
                tools = [_dump(tool) for tool in result.tools]
                self.sessions[spec.name] = session
                self.snapshots[spec.name] = {
                    "name": spec.name,
                    "label": spec.label,
                    "external": spec.external,
                    "connected": True,
                    "tool_count": len(tools),
                    "protocol_version": initialize.protocolVersion,
                    "server_name": (_dump(initialize.serverInfo) or {}).get("name", ""),
                    "error": "",
                    "tools": [tool.get("name", "") for tool in tools],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
                for tool in tools:
                    name = str(tool.get("name") or "")
                    if name:
                        self._add_tool(spec, name, tool)
            except Exception as exc:  # noqa: BLE001
                self.failures[spec.name] = f"{type(exc).__name__}: {exc}"
                self.snapshots[spec.name] = {
                    "name": spec.name,
                    "label": spec.label,
                    "external": spec.external,
                    "connected": False,
                    "tool_count": 0,
                    "error": self.failures[spec.name],
                    "tools": [],
                }
        self._resolve_collisions()

    def _add_tool(self, spec: ServerSpec, original: str, tool: dict[str, Any]) -> None:
        self._pending.append(
            {
                "server": spec.name,
                "server_label": spec.label,
                "original": original,
                "description": tool.get("description") or "",
                "input_schema": tool.get("inputSchema")
                or {"type": "object", "properties": {}},
            }
        )

    def _resolve_collisions(self) -> None:
        pending = self._pending
        counts: dict[str, int] = {}
        for item in pending:
            counts[item["original"]] = counts.get(item["original"], 0) + 1
        self.tools = []
        self.routes = {}
        for item in pending:
            original = item["original"]
            exposed = (
                f"{item['server']}__{original}"
                if counts[original] > 1
                else original
            )
            entry = {
                **item,
                "name": exposed,
                "collision": counts[original] > 1,
            }
            self.tools.append(entry)
            self.routes[exposed] = entry

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": (
                        f"[{tool['server']}] {tool['description']} "
                        f"(оригинальное имя: {tool['original']})"
                    ),
                    "parameters": tool["input_schema"],
                },
            }
            for tool in self.tools
        ]

    def route_name(self, server: str, original: str) -> str:
        for tool in self.tools:
            if tool["server"] == server and tool["original"] == original:
                return tool["name"]
        raise KeyError(f"Нет инструмента {server}/{original}")

    def inspect(self) -> dict[str, Any]:
        return {
            "servers": list(self.snapshots.values()),
            "tools": self.tools,
            "tool_count": len(self.tools),
            "failures": self.failures,
            "available": bool(self.tools),
        }

    async def call(self, exposed: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        route = self.routes.get(exposed)
        if route is None:
            return {
                "ok": False,
                "error": f"Неизвестный инструмент: {exposed}",
                "server": None,
                "original": None,
            }
        server = route["server"]
        session = self.sessions.get(server)
        if session is None:
            return {
                "ok": False,
                "error": self.failures.get(server) or f"Сервер {server} недоступен",
                "server": server,
                "original": route["original"],
            }
        started = time.perf_counter()
        try:
            async with asyncio.timeout(CALL_TIMEOUT):
                result = await session.call_tool(route["original"], arguments or {})
        except Exception as exc:  # noqa: BLE001
            self.failures[server] = f"{type(exc).__name__}: {exc}"
            return {
                "ok": False,
                "error": self.failures[server],
                "server": server,
                "original": route["original"],
            }
        payload = _payload(result)
        return {
            **payload,
            "server": server,
            "original": route["original"],
            "exposed": exposed,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
