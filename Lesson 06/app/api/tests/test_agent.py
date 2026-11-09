"""Тесты агентского цикла на scripted-провайдере: без сети и без ключей."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from app.agent import Agent, AgentConfig, run_agent
from app.agent_tools import DEFAULT_REGISTRY
from app.providers.base import Provider, ProviderRequest, StreamEvent


class ScriptedProvider(Provider):
    """Отдаёт заранее заданные ответы: tool call или финальный текст."""

    name = "scripted"

    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        item = self.script.pop(0)
        if item.get("tool"):
            arguments = item.get("arguments", {})
            raw = item.get("raw", json.dumps(arguments, ensure_ascii=False))
            yield StreamEvent("tool_delta", text=raw)
            yield StreamEvent(
                "done",
                data={
                    "tool_name": item["tool"],
                    "finish_reason": "tool_calls",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            )
            return
        yield StreamEvent("delta", text=item.get("text", ""))
        yield StreamEvent(
            "done",
            data={
                "finish_reason": "stop",
                "prompt_tokens": 10,
                "completion_tokens": 5,
            },
        )


class ParallelProvider(Provider):
    """Отдаёт два tool call в одном ответе, как OpenAI при parallel tool calls."""

    name = "parallel"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield StreamEvent(
                "tool_delta",
                text='{"expression": "2 + 2"}',
                data={"index": 0, "id": "call_a", "name": "calculator"},
            )
            yield StreamEvent(
                "tool_delta",
                text='{"timezone": "Europe/Moscow"}',
                data={"index": 1, "id": "call_b", "name": "current_time"},
            )
            yield StreamEvent(
                "done",
                data={
                    "tool_name": "current_time",
                    "finish_reason": "tool_calls",
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                },
            )
            return
        yield StreamEvent("delta", text="Готово: 4, время получено.")
        yield StreamEvent(
            "done",
            data={"finish_reason": "stop", "prompt_tokens": 5, "completion_tokens": 3},
        )


def test_agent_handles_multiple_tool_calls_in_one_turn() -> None:
    provider = ParallelProvider()
    result = asyncio.run(
        run_agent(
            provider,
            model="parallel-model",
            prompt="Привет",
            tools=["calculator", "current_time"],
            max_steps=2,
        )
    )
    assert [step["tool"] for step in result.steps] == ["calculator", "current_time"]
    assert [step["index"] for step in result.steps] == [1, 2]
    assert result.answer.startswith("Готово")
    assert result.stopped_reason == "final"

    messages = provider.requests[1].messages
    assistant_calls = [
        message for message in messages
        if message["role"] == "assistant" and message.get("tool_calls")
    ]
    assert len(assistant_calls) == 1
    assert len(assistant_calls[0]["tool_calls"]) == 2
    assert len([message for message in messages if message["role"] == "tool"]) == 2


def _run(provider: ScriptedProvider, **overrides):
    params = {
        "model": "scripted-model",
        "prompt": "Сколько будет 17 * 4?",
        "temperature": 0.2,
        "reasoning": "off",
        "max_tokens": 500,
        "max_steps": 4,
    }
    params.update(overrides)
    return asyncio.run(run_agent(provider, **params))


def test_agent_runs_two_tools_then_answers() -> None:
    provider = ScriptedProvider(
        [
            {"tool": "calculator", "arguments": {"expression": "17 * 4"}},
            {"tool": "calculator", "arguments": {"expression": "68 + 6"}},
            {"text": "Получилось 74."},
        ]
    )
    result = _run(provider)
    assert [step["tool"] for step in result.steps] == ["calculator", "calculator"]
    assert result.answer == "Получилось 74."
    assert result.stopped_reason == "final"
    assert len(provider.requests) == 3

    # во втором запросе уже есть assistant tool_calls и наблюдение role=tool
    messages = provider.requests[1].messages
    assert any(message["role"] == "assistant" and message.get("tool_calls") for message in messages)
    tool_messages = [message for message in messages if message["role"] == "tool"]
    assert tool_messages and "68" in tool_messages[-1]["content"]


def test_agent_stops_at_max_steps_and_summarises() -> None:
    provider = ScriptedProvider(
        [
            {"tool": "calculator", "arguments": {"expression": "1 + 1"}},
            {"tool": "calculator", "arguments": {"expression": "2 + 2"}},
            {"text": "Итог: инструменты вызваны дважды."},
        ]
    )
    result = _run(provider, max_steps=2)
    assert len(result.steps) == 2
    assert result.stopped_reason == "max_steps"
    assert "Итог" in result.answer
    # финальный вызов идёт без инструментов
    assert provider.requests[-1].tools is None


def test_agent_reports_broken_tool_arguments() -> None:
    provider = ScriptedProvider(
        [
            {"tool": "calculator", "arguments": {}, "raw": "{oops"},
            {"text": "Не удалось посчитать."},
        ]
    )
    result = _run(provider)
    assert result.steps[0]["result"]["ok"] is False
    assert "JSON" in result.steps[0]["result"]["error"]
    assert result.answer == "Не удалось посчитать."


def test_agent_class_is_reusable_and_resets_state() -> None:
    provider = ScriptedProvider(
        [
            {"tool": "calculator", "arguments": {"expression": "2 + 2"}},
            {"text": "4"},
            {"text": "Привет!"},
        ]
    )
    agent = Agent(
        provider,
        DEFAULT_REGISTRY.select(["calculator"]),
        AgentConfig(model="scripted-model", max_steps=2),
    )

    first = asyncio.run(agent.run("Посчитай 2 + 2"))
    assert len(first.steps) == 1
    assert agent.status == "done"
    assert len(agent.messages) >= 4

    second = asyncio.run(agent.run("Привет"))
    assert second.steps == []
    assert second.answer == "Привет!"
    assert len(agent.messages) == 2
    assert agent.steps == []


def test_agent_registry_blocks_unselected_tools() -> None:
    provider = ScriptedProvider([])
    agent = Agent(
        provider,
        DEFAULT_REGISTRY.select(["current_time"]),
        AgentConfig(model="scripted-model", max_steps=2),
    )
    result = asyncio.run(agent.run("Посчитай 2 + 2"))
    assert result.stopped_reason == "missing_tool"
    assert result.missing_tools == ["calculator"]
    assert provider.requests == []


def test_agent_refuses_before_model_when_tool_missing() -> None:
    provider = ScriptedProvider([])
    result = _run(provider, prompt="Посчитай 17 * 4", tools=[])
    assert result.stopped_reason == "missing_tool"
    assert result.missing_tools == ["calculator"]
    assert result.steps == []
    assert "нет возможности" in result.answer
    assert provider.requests == []


def test_agent_refuses_when_model_calls_unselected_tool() -> None:
    provider = ScriptedProvider(
        [{"tool": "calculator", "arguments": {"expression": "17 * 4"}}]
    )
    result = _run(provider, prompt="Просто ответь без расчётов", tools=["current_time"])
    assert result.stopped_reason == "missing_tool"
    assert result.missing_tools == ["calculator"]
    assert result.steps == []
    assert "нет возможности" in result.answer
    assert len(provider.requests) == 1


def test_agent_merges_usage() -> None:
    provider = ScriptedProvider(
        [
            {"tool": "calculator", "arguments": {"expression": "2 + 2"}},
            {"text": "4"},
        ]
    )
    result = _run(provider)
    assert result.usage["prompt_tokens"] == 20
    assert result.usage["completion_tokens"] == 10
    assert result.usage["total_tokens"] == 30
