"""Агент урока 17: модель вызывает единственный MCP-инструмент get_customer."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .agent import AgentConfig, Turn, _merge_usage, _parse_arguments, _turn
from .agent_tools import TOOL_LABELS, tool_result_json
from .mcp_client import MCPError, call_tool, inspect_server
from .providers import Provider

SYSTEM_PROMPT = (
    "Ты — агент поддержки учебного проекта AI Challenge. У тебя есть MCP-инструменты "
    "для CRM: get_customer — карточка клиента, list_customers — все клиенты, "
    "create_customer — добавить клиента. Когда пользователь спрашивает о клиенте, "
    "вызови get_customer; когда просит список — list_customers; когда просит "
    "добавить клиента — create_customer с name, email и plan. Используй данные "
    "инструментов в ответе. Не выдумывай имя, тариф, баланс или количество обращений. "
    "Если инструмент вернул ошибку, честно скажи об этом. Отвечай по-русски, кратко."
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
    text = result.get("text") or ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if result.get("is_error"):
        return {"ok": False, "error": text or "Ошибка MCP-инструмента"}
    if isinstance(payload, dict) and "ok" in payload:
        return payload
    return {"ok": True, "result": payload if payload is not None else text}


@dataclass(frozen=True)
class MCPServer:
    name: str
    inspect: Callable[[], Awaitable[dict[str, Any]]]
    call: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class MCPChat:
    """Один запуск чата с MCP-инструментом CRM."""

    def __init__(
        self,
        provider: Provider,
        config: AgentConfig,
        history: list[dict[str, str]] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.history = list(history or [])[-20:]
        self.servers = [MCPServer("crm", inspect_server, call_tool)]
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
        snapshot = await inspect_server()
        self._server_snapshots = [
            {
                "name": "crm",
                "transport": snapshot.get("transport"),
                "tool_count": snapshot.get("tool_count", 0),
                "error": "",
            }
        ]
        self.tools = snapshot.get("tools") or []
        for raw in self.tools:
            name = str(raw.get("name") or "")
            if name:
                self._tool_servers[name] = (self.servers[0], name)
        if not self.tools:
            raise MCPError("MCP-сервер не вернул инструменты")
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
                    try:
                        result = await server.call(original, arguments or {})
                        observation = _observation(result)
                    except MCPError as exc:
                        observation = {"ok": False, "error": str(exc)}
            self.steps.append(
                {
                    "index": len(self.steps) + 1,
                    "tool": name,
                    "label": TOOL_LABELS.get(name, name),
                    "arguments": arguments or {},
                    "result": observation,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                    "server": "crm",
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
        except Exception:  # noqa: BLE001
            self.stopped_reason = "max_steps"
