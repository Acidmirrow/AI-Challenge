"""Тест агента урока 20: выбор инструментов с разных MCP-серверов."""

from __future__ import annotations

import asyncio
import json

from app.agent import AgentConfig
from app.mcp_agent import MultiMCPChat
from app.providers.base import Provider, StreamEvent


class ScriptedProvider(Provider):
    """Детерминированно выбирает три инструмента, как это сделала бы модель."""

    name = "scripted"

    async def stream(self, request):
        tool_messages = sum(1 for item in request.messages if item.get("role") == "tool")
        if tool_messages == 0:
            name, arguments = "get_customer", {"customer_id": "C-104"}
        elif tool_messages == 1:
            name, arguments = "forecast", {"customer_id": "C-104", "amount_rub": 100000}
        elif tool_messages == 2:
            name, arguments = "get_current_time", {"timezone": "Europe/Moscow"}
        else:
            yield StreamEvent("delta", text="Готово: клиент, прогноз и время получены.")
            yield StreamEvent("done", data={"finish_reason": "stop"})
            return

        yield StreamEvent(
            "tool_delta",
            text=json.dumps(arguments),
            data={"name": name, "id": f"call-{tool_messages + 1}"},
        )
        yield StreamEvent(
            "done",
            data={"finish_reason": "tool_calls", "tool_name": name},
        )


def test_agent_routes_tools_across_servers() -> None:
    config = AgentConfig(model="scripted", max_steps=5)
    result = asyncio.run(MultiMCPChat(ScriptedProvider(), config).run("Собери отчёт"))
    assert result["answer"].startswith("Готово")
    assert [step["server"] for step in result["steps"]] == ["orders", "analytics", "time"]
    assert [step["tool"] for step in result["steps"]] == [
        "get_customer",
        "forecast",
        "get_current_time",
    ]
    assert all(step["result"]["ok"] for step in result["steps"])
    assert {item["name"] for item in result["servers"]} == {"orders", "analytics", "time"}


def test_agent_reports_disabled_server_without_calling_it() -> None:
    config = AgentConfig(model="scripted", max_steps=5)
    result = asyncio.run(
        MultiMCPChat(
            ScriptedProvider(),
            config,
            disabled_servers=["time"],
        ).run("Собери отчёт")
    )
    time_steps = [step for step in result["steps"] if step["tool"] == "get_current_time"]
    assert time_steps
    assert time_steps[0]["result"]["ok"] is False
    assert "time" in result["failures"]
    assert result["servers"][-1]["connected"] is False
