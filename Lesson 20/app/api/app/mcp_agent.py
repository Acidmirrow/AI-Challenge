"""Агент урока 20: выбирает инструменты из нескольких MCP-серверов."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .agent import AgentConfig, Turn, _merge_usage, _parse_arguments, _turn
from .hub import MCPHub
from .providers import Provider

SYSTEM_PROMPT = (
    "Ты — агент оркестрации MCP учебного проекта AI Challenge. У тебя есть "
    "инструменты с нескольких серверов: заказы, аналитика и внешний time-сервер. "
    "Имена с префиксом `server__tool` означают, что одинаковые имена есть на разных "
    "серверах.\n"
    "Правила:\n"
    "1. Для фактов о клиенте, прогнозе, статусе сервиса или времени вызывай "
    "соответствующий инструмент, не отвечай по памяти.\n"
    "2. Можно выполнить несколько вызовов подряд, но не повторяй один и тот же вызов "
    "без причины и не вызывай инструмент, которого нет в списке.\n"
    "3. Если сервер или инструмент недоступен, честно сообщи об этом. Не выдумывай "
    "данные и не подменяй результат другого сервера.\n"
    "4. После наблюдений дай краткий итог по-русски с числами из инструментов."
)


def _mcp_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": (
                f"[{tool['server']}] {tool.get('description') or ''} "
                f"(оригинальное имя: {tool['original']})"
            ),
            "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
        },
    }


def _observation(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok"):
        return result
    return {
        "ok": False,
        "error": result.get("error") or "Ошибка MCP-инструмента",
        "server": result.get("server"),
    }


class MultiMCPChat:
    """Один запуск чата с агрегированным каталогом трёх MCP-серверов."""

    def __init__(
        self,
        provider: Provider,
        config: AgentConfig,
        history: list[dict[str, str]] | None = None,
        disabled_servers: list[str] | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.history = list(history or [])[-20:]
        self.disabled_servers = list(disabled_servers or [])
        self.steps: list[dict[str, Any]] = []
        self.usage: dict[str, Any] = {}
        self.answer = ""
        self.stopped_reason = "max_steps"
        self.finish_reason: str | None = None
        self._started = 0.0

    async def run(self, prompt: str) -> dict[str, Any]:
        self._started = time.perf_counter()
        async with MCPHub(self.disabled_servers) as hub:
            inspect = hub.inspect()
            if not hub.tools:
                raise RuntimeError(
                    "Ни один MCP-сервер не доступен: "
                    + "; ".join(f"{name}: {error}" for name, error in hub.failures.items())
                )
            schemas = [_mcp_tool_schema(tool) for tool in hub.tools]
            status = self._server_status(inspect, hub.failures)
            messages: list[dict[str, Any]] = [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT + "\n\n" + status,
                },
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
                    messages=messages,
                    temperature=self.config.temperature,
                    reasoning=self.config.reasoning,
                    max_tokens=self.config.max_tokens,
                    supports_reasoning=self.config.supports_reasoning,
                    supports_temperature=self.config.supports_temperature,
                    tools=schemas,
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
                await self._execute_calls(hub, calls, turn.text, messages)
            else:
                self.stopped_reason = "max_steps"

            return {
                "answer": self.answer or "Агент не смог сформулировать итог.",
                "steps": self.steps,
                "usage": self.usage,
                "elapsed_ms": int((time.perf_counter() - self._started) * 1000),
                "finish_reason": self.finish_reason,
                "stopped_reason": self.stopped_reason,
                "tools": [tool["name"] for tool in hub.tools],
                "servers": inspect["servers"],
                "failures": hub.failures,
                "tool_routes": {
                    tool["name"]: f"{tool['server']}/{tool['original']}"
                    for tool in hub.tools
                },
            }

    @staticmethod
    def _server_status(inspect: dict[str, Any], failures: dict[str, str]) -> str:
        available = [
            f"{item['name']} ({item['tool_count']} инструментов)"
            for item in inspect.get("servers", [])
            if item.get("connected")
        ]
        unavailable = [
            f"{name}: {reason}" for name, reason in failures.items()
        ]
        text = "Доступные серверы: " + (", ".join(available) or "нет") + "."
        if unavailable:
            text += " Недоступные серверы: " + "; ".join(unavailable) + "."
        return text

    async def _execute_calls(
        self,
        hub: MCPHub,
        calls: list[dict[str, Any]],
        content: str,
        messages: list[dict[str, Any]],
    ) -> None:
        message_calls: list[dict[str, Any]] = []
        observations: list[tuple[str, dict[str, Any]]] = []
        for call in calls:
            name = str(call.get("name") or "")
            arguments, parse_error = _parse_arguments(str(call.get("arguments") or ""))
            started = time.perf_counter()
            if parse_error:
                observation = {"ok": False, "error": parse_error, "server": None}
                arguments = {}
                route = None
            else:
                route = hub.routes.get(name)
                if route is None:
                    observation = {
                        "ok": False,
                        "error": f"Неизвестный MCP-инструмент: {name}",
                        "server": None,
                    }
                else:
                    result = await hub.call(name, arguments or {})
                    observation = _observation(result)
            self.steps.append(
                {
                    "index": len(self.steps) + 1,
                    "tool": name,
                    "server": (route or {}).get("server"),
                    "original": (route or {}).get("original"),
                    "arguments": arguments or {},
                    "result": observation,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
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

        messages.append({"role": "assistant", "content": content, "tool_calls": message_calls})
        for call_id, observation in observations:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(observation, ensure_ascii=False),
                }
            )
