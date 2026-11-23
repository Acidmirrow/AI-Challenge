"""Чат-агент урока 16: модель выбирает инструменты, вызовы идут через MCP.

Инструменты не импортируются в агент напрямую: их список и схемы приходят из
`app.mcp_server` по протоколу. Локальный код знает только MCP-клиент.
"""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .agent import AgentConfig, Turn, _merge_usage, _parse_arguments, _turn
from .agent_tools import TOOL_LABELS, tool_result_json
from .mcp_client import (
    YOUGILE_URL,
    MCPError,
    call_http_tool,
    call_tool,
    inspect_http,
    inspect_server,
)
from .providers import Provider

EXTERNAL_PROMPT = (
    "Ты — ИИ-агент учебного проекта AI Challenge. Инструменты подключены по MCP "
    "к внешнему сервису (например, YouGile). Решай задачу по шагам, используй только "
    "доступные инструменты и не выдумывай результаты. Перед изменением данных уточняй "
    "цель; для чтения используй поиск и дерево проектов. Финальный ответ дай по-русски, "
    "кратко, с названиями проектов, досок и задач из наблюдений."
)

DEFAULT_YOUGILE_COLUMN_ID = os.getenv(
    "YOUGILE_DEFAULT_COLUMN_ID", "b641afe4-f71a-44f6-8331-85abf1346ba4"
)


def _yougile_defaults(name: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Новые задачи должны попадать на доску AI, даже если модель забыла columnId."""

    args = copy.deepcopy(arguments)
    if name == "manage_tasks":
        tasks = args.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                if task.get("id") in (None, ""):
                    task["columnId"] = DEFAULT_YOUGILE_COLUMN_ID
                    task.setdefault("description", "")
                    task.setdefault("color", None)
                    task.setdefault("complete", False)
                    task.setdefault("archived", False)
        return name, args
    if name == "add_task_without_board":
        title = str(args.get("title") or "").strip()
        if title:
            return "manage_tasks", {
                "tasks": [
                    {
                        "id": None,
                        "title": title,
                        "columnId": DEFAULT_YOUGILE_COLUMN_ID,
                        "description": "",
                        "color": None,
                        "complete": False,
                        "archived": False,
                    }
                ]
            }
    return name, args


SYSTEM_PROMPT = (
    "Ты — ИИ-агент учебного проекта AI Challenge. Все доступные инструменты "
    "подключены по MCP и выбираются автоматически по задаче. Используй точные "
    "вычисления, время, статистику, курсы, единицы, даты, а также инструменты "
    "YouGile для проектов, досок, задач, CRM, чатов и базы знаний, когда это нужно.\n"
    "Все новые задачи в YouGile создавай на доске «AI» в колонке «Задачи»; "
    "не используй add_task_without_board.\n"
    "Правила:\n"
    "1. Если данных не хватает — вызови ровно один инструмент и дождись наблюдения.\n"
    "2. Не выдумывай результат инструмента и не повторяй один и тот же вызов без причины.\n"
    "3. После наблюдения реши: нужен ещё инструмент или уже можно ответить.\n"
    "4. Финальный ответ дай по-русски, кратко и по делу; приводи числа из наблюдений.\n"
    "5. Если задача не требует инструментов — ответь сразу."
)


def _mcp_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description") or "",
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def _observation(result: dict[str, Any]) -> dict[str, Any]:
    """Разобрать ответ MCP в наблюдение, которое понимает модель."""

    text = result.get("text") or ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and "observation" in payload:
        value = payload["observation"]
        if isinstance(value, dict):
            return value
    if result.get("is_error"):
        return {"ok": False, "error": text or "Ошибка MCP-инструмента"}
    return {"ok": True, "result": payload if payload is not None else text}


@dataclass(frozen=True)
class MCPServer:
    """Один подключённый MCP-сервер и его транспорт."""

    name: str
    inspect: Callable[[], Awaitable[dict[str, Any]]]
    call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MCPChat:
    """Один запуск чата с MCP-инструментами."""

    def __init__(
        self,
        provider: Provider,
        config: AgentConfig,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.history = list(history or [])[-20:]
        self.servers = [
            MCPServer("builtin", inspect_server, call_tool),
            MCPServer(
                "yougile",
                lambda: inspect_http(YOUGILE_URL),
                lambda name, arguments: call_http_tool(name, arguments, YOUGILE_URL),
            ),
        ]
        self._tool_servers: dict[str, tuple[MCPServer, str]] = {}
        self._server_snapshots: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.usage: dict[str, Any] = {}
        self.answer = ""
        self.stopped_reason = "max_steps"
        self.finish_reason: str | None = None
        self.tools: list[dict[str, Any]] = []
        self._started = 0.0

    async def run(self, prompt: str) -> dict[str, Any]:
        self._started = time.perf_counter()
        self.tools = []
        self._tool_servers = {}
        self._server_snapshots = []
        for server in self.servers:
            try:
                snapshot = await server.inspect()
                error = ""
            except MCPError as exc:
                snapshot = {
                    "server": {"name": server.name},
                    "transport": "stdio" if server.name == "builtin" else "http",
                    "tool_count": 0,
                    "tools": [],
                }
                error = str(exc)
            self._server_snapshots.append(
                {
                    "name": server.name,
                    "transport": snapshot.get("transport"),
                    "tool_count": snapshot.get("tool_count", 0),
                    "error": error,
                }
            )
            for raw in snapshot.get("tools") or []:
                original = str(raw.get("name") or "")
                if not original:
                    continue
                exposed = original
                if exposed in self._tool_servers:
                    exposed = f"{server.name}__{original}"
                item = dict(raw)
                item["name"] = exposed
                item["label"] = TOOL_LABELS.get(original, original)
                item["server"] = server.name
                self.tools.append(item)
                self._tool_servers[exposed] = (server, original)
        if not self.tools:
            raise MCPError("Ни один MCP-сервер не вернул инструменты")
        schemas = [_mcp_tool_schema(tool) for tool in self.tools]
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *[
                {"role": item["role"], "content": item["content"]}
                for item in self.history
                if item.get("role") in {"user", "assistant"} and item.get("content")
            ],
            {"role": "user", "content": prompt.strip()},
        ]

        for _ in range(self.config.max_steps):
            turn = await _turn(
                self.provider,
                model=self.config.model,
                messages=self.messages,
                temperature=self.config.temperature,
                reasoning=self.config.reasoning,
                max_tokens=self.config.max_tokens,
                supports_reasoning=self.config.supports_reasoning,
                supports_temperature=self.config.supports_temperature,
                tools=schemas or None,
            )
            _merge_usage(self.usage, turn.usage)
            self.finish_reason = turn.finish_reason
            calls = turn.tool_calls or (
                [{"id": "", "name": turn.tool_name, "arguments": turn.tool_arguments}]
                if turn.tool_name
                else []
            )
            if not calls:
                self.answer = turn.text.strip()
                self.stopped_reason = "final" if self.answer else "empty"
                break
            await self._execute_calls(calls, turn.text)
        else:
            await self._finalize_after_limit()

        return {
            "answer": self.answer or "Агент не успел сформулировать итог.",
            "steps": self.steps,
            "usage": self.usage,
            "elapsed_ms": int((time.perf_counter() - self._started) * 1000),
            "finish_reason": self.finish_reason,
            "stopped_reason": self.stopped_reason,
            "tools": [tool["name"] for tool in self.tools],
            "servers": self._server_snapshots,
        }

    async def _execute_calls(self, calls: list[dict[str, Any]], content: str) -> None:
        message_calls: list[dict[str, Any]] = []
        observations: list[tuple[str, dict[str, Any]]] = []
        for call in calls:
            name = str(call.get("name") or "")
            arguments, parse_error = _parse_arguments(str(call.get("arguments") or ""))
            started = time.perf_counter()
            if parse_error:
                observation = {"ok": False, "error": parse_error}
                arguments = {}
            else:
                route = self._tool_servers.get(name)
                if route is None:
                    observation = {"ok": False, "error": f"Неизвестный MCP-инструмент: {name}"}
                else:
                    server, original = route
                    call_name, call_arguments = (
                        _yougile_defaults(original, arguments or {})
                        if server.name == "yougile"
                        else (original, arguments or {})
                    )
                    arguments = call_arguments
                    try:
                        result = await server.call(call_name, call_arguments)
                        observation = _observation(result)
                    except MCPError as exc:
                        observation = {"ok": False, "error": str(exc)}
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.steps.append(
                {
                    "index": len(self.steps) + 1,
                    "tool": name,
                    "label": TOOL_LABELS.get(name, name),
                    "server": route[0].name if route else "",
                    "arguments": arguments or {},
                    "result": observation,
                    "elapsed_ms": elapsed_ms,
                }
            )
            call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:10]}")
            message_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments or {}, ensure_ascii=False),
                    },
                }
            )
            observations.append((call_id, observation))

        self.messages.append(
            {"role": "assistant", "content": content, "tool_calls": message_calls}
        )
        for call_id, observation in observations:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_result_json(observation),
                }
            )

    async def _finalize_after_limit(self) -> None:
        self.messages.append(
            {
                "role": "user",
                "content": "Лимит шагов исчерпан. Сформулируй итог по наблюдениям без новых инструментов.",
            }
        )
        try:
            turn: Turn = await _turn(
                self.provider,
                model=self.config.model,
                messages=self.messages,
                temperature=self.config.temperature,
                reasoning=self.config.reasoning,
                max_tokens=self.config.max_tokens,
                supports_reasoning=self.config.supports_reasoning,
                supports_temperature=self.config.supports_temperature,
                tools=None,
            )
            _merge_usage(self.usage, turn.usage)
            self.answer = turn.text.strip()
            self.finish_reason = turn.finish_reason
            self.stopped_reason = "max_steps"
        except Exception:  # noqa: BLE001 - не ломаем уже собранную трассу
            self.stopped_reason = "max_steps"
