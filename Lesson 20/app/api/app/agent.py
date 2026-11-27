"""Цикл ИИ-агента: модель → инструмент → наблюдение → итог.

Агент не стримит ответ по кускам: сначала он может несколько раз вызвать
инструменты, и только потом выдаёт финальный текст. Наружу отдаём полную
трассу шагов, чтобы в UI было видно, откуда взялся ответ.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .agent_tools import TOOL_LABELS, ToolRegistry, tool_result_json
from .providers import Provider, ProviderError, ProviderRequest

SYSTEM_PROMPT = (
    "Ты — ИИ-агент учебного проекта AI Challenge. Решай задачу по шагам и используй "
    "инструменты, когда нужны точные вычисления, текущее время, статистика текста или "
    "курсы валют.\n"
    "Правила:\n"
    "1. Если данных не хватает — вызови ровно один инструмент и дождись наблюдения.\n"
    "2. Не выдумывай результат инструмента и не повторяй один и тот же вызов без причины.\n"
    "3. После наблюдения реши: нужен ещё инструмент или уже можно ответить.\n"
    "4. Финальный ответ дай по-русски, кратко и по делу; приводи числа, которые вернули "
    "инструменты.\n"
    "5. Если задача не требует инструментов — ответь сразу."
)


@dataclass
class Turn:
    """Один ответ модели: либо текст, либо запрос инструмента."""

    text: str = ""
    reasoning: str = ""
    tool_name: str | None = None
    tool_arguments: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRun:
    answer: str
    steps: list[dict[str, Any]]
    usage: dict[str, Any]
    elapsed_ms: int
    finish_reason: str | None
    truncated: bool
    stopped_reason: str
    tools: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)


def _missing_message(names: list[str]) -> str:
    labels = ", ".join(f"«{TOOL_LABELS.get(name, name)}»" for name in names)
    if len(names) == 1:
        return (
            f"У ИИ-агента нет возможности ответить на этот вопрос: нужен инструмент "
            f"{labels}, но он не выбран. Выберите его в сайдбаре и повторите задачу."
        )
    return (
        f"У ИИ-агента нет возможности ответить на этот вопрос: нужны инструменты "
        f"{labels}, но они не выбраны. Выберите их в сайдбаре и повторите задачу."
    )


def _system_prompt(allowed: list[str]) -> str:
    if not allowed:
        return (
            SYSTEM_PROMPT
            + "\nСейчас инструменты не выбраны. Если задача требует вычислений, курса, "
            "времени или статистики текста, не отвечай по памяти, а скажи: «У ИИ-агента "
            "нет возможности ответить на этот вопрос: нужный инструмент не выбран»."
        )
    listing = "\n".join(f"- {name}: {TOOL_LABELS.get(name, name)}" for name in allowed)
    return (
        SYSTEM_PROMPT
        + f"\nДоступные инструменты:\n{listing}\n"
        "Если для задачи нужен инструмент, которого нет в этом списке, не пытайся "
        "ответить по памяти — скажи: «У ИИ-агента нет возможности ответить на этот "
        "вопрос: нужный инструмент не выбран»."
    )


async def _turn(
    active: Provider,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None,
    reasoning: str,
    max_tokens: int | None,
    supports_reasoning: bool,
    supports_temperature: bool,
    tools: list[dict[str, Any]] | None,
) -> Turn:
    """Собрать один ответ провайдера, включая аргументы tool call."""
    request = ProviderRequest(
        messages=messages,
        model=model,
        temperature=temperature if supports_temperature else None,
        reasoning=reasoning,
        max_tokens=max_tokens,
        supports_reasoning=supports_reasoning,
        supports_temperature=supports_temperature,
        tools=tools,
        tool_choice="auto" if tools else None,
        parallel_tool_calls=False if tools else None,
    )
    text, reasoning_text, arguments = "", "", ""
    calls: dict[int, dict[str, Any]] = {}
    result = Turn()
    async for event in active.stream(request):
        if event.type == "delta":
            text += event.text
        elif event.type == "reasoning":
            reasoning_text += event.text
        elif event.type == "tool_delta":
            arguments += event.text
            index = int(event.data.get("index") or 0)
            call = calls.setdefault(
                index, {"id": "", "name": "", "arguments": ""}
            )
            if event.data.get("id"):
                call["id"] = str(event.data["id"])
            if event.data.get("name"):
                call["name"] = str(event.data["name"])
            call["arguments"] += event.text
        elif event.type == "done":
            result.tool_name = event.data.get("tool_name")
            result.finish_reason = event.data.get("finish_reason")
            result.usage = {
                key: event.data[key]
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if key in event.data
            }
    result.text = text
    result.reasoning = reasoning_text
    result.tool_arguments = arguments
    result.tool_calls = [calls[index] for index in sorted(calls)]
    if result.tool_name:
        for call in result.tool_calls:
            if not call.get("name"):
                call["name"] = result.tool_name
    if not result.tool_calls and result.tool_name:
        result.tool_calls = [{
            "id": "",
            "name": result.tool_name,
            "arguments": arguments,
        }]
    return result


def _usage_total(usage: dict[str, Any]) -> int:
    total = int(usage.get("total_tokens") or 0)
    if total:
        return total
    return int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)


def _merge_usage(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in extra and extra[key] is not None:
            target[key] = int(target.get(key) or 0) + int(extra[key])


def _parse_arguments(raw: str) -> tuple[dict[str, Any] | None, str]:
    """Вернуть аргументы и текст ошибки, если JSON битый."""
    raw = (raw or "").strip()
    if not raw:
        return {}, ""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"Аргументы инструмента — не JSON: {exc.msg}"
    if not isinstance(value, dict):
        return None, "Аргументы инструмента должны быть JSON-объектом."
    return value, ""


@dataclass(frozen=True)
class AgentConfig:
    """Параметры одного запуска агента."""

    model: str
    temperature: float = 0.2
    reasoning: str = "off"
    max_tokens: int | None = 1_500
    max_steps: int = 10
    supports_reasoning: bool = False
    supports_temperature: bool = True


class Agent:
    """Самостоятельный агент: состояние диалога, цикл и вызовы инструментов.

    HTTP-слой не управляет циклом: он создаёт агента с провайдером и реестром
    инструментов и вызывает `run()`. Экземпляр хранит историю сообщений, шаги,
    usage и результат; повторный `run()` начинает с чистого состояния.
    """

    def __init__(
        self,
        provider: Provider,
        tools: ToolRegistry,
        config: AgentConfig,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.config = config
        self.messages: list[dict[str, Any]] = []
        self.steps: list[dict[str, Any]] = []
        self.usage: dict[str, Any] = {}
        self.status = "new"
        self.answer = ""
        self.finish_reason: str | None = None
        self.stopped_reason = "max_steps"
        self.missing_tools: list[str] = []
        self.step_index = 0
        self._tools_enabled = True
        self._started = 0.0

    def reset(self, prompt: str) -> None:
        """Начать новый запуск, не смешивая состояние с предыдущим."""
        self.messages = [
            {"role": "system", "content": _system_prompt(self.tools.names)},
            {"role": "user", "content": prompt.strip()},
        ]
        self.steps = []
        self.usage = {}
        self.status = "running"
        self.answer = ""
        self.finish_reason = None
        self.stopped_reason = "max_steps"
        self.missing_tools = []
        self.step_index = 0
        self._tools_enabled = True
        self._started = time.perf_counter()

    async def run(self, prompt: str) -> AgentRun:
        """Выполнить задачу: цикл продолжается, пока модель просит инструменты."""
        self.reset(prompt)

        missing = self.tools.missing_for(prompt)
        if missing:
            self.missing_tools = list(missing)
            self.answer = _missing_message(missing)
            self.stopped_reason = "missing_tool"
            self.status = "missing_tool"
            return self._result()

        for _ in range(self.config.max_steps):
            try:
                turn = await self._call_model()
            except ProviderError as exc:
                if self._tools_enabled and _looks_like_tools_error(exc):
                    self._tools_enabled = False
                    turn = await self._call_model(use_tools=False)
                else:
                    self.status = "error"
                    raise

            _merge_usage(self.usage, turn.usage)
            self.finish_reason = turn.finish_reason

            calls = turn.tool_calls or (
                [{"id": "", "name": turn.tool_name, "arguments": turn.tool_arguments}]
                if turn.tool_name else []
            )
            if not calls:
                self.answer = turn.text.strip()
                self.stopped_reason = "final" if self.answer else "empty"
                self.status = "done"
                break

            unallowed = [call["name"] for call in calls if call["name"] not in self.tools.names]
            if unallowed:
                self.missing_tools = list(dict.fromkeys(unallowed))
                self.answer = _missing_message(self.missing_tools)
                self.stopped_reason = "missing_tool"
                self.status = "missing_tool"
                break

            self._execute_tool_calls(calls, turn.text)
        else:
            await self._finalize_after_limit()

        return self._result()

    async def _call_model(self, use_tools: bool = True) -> Turn:
        schemas = self.tools.schemas() if use_tools and self._tools_enabled else None
        return await _turn(
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

    def _execute_tool_calls(
        self, calls: list[dict[str, Any]], content: str = ""
    ) -> None:
        message_calls: list[dict[str, Any]] = []
        tool_messages: list[tuple[str, dict[str, Any]]] = []

        for call in calls:
            tool_name = str(call.get("name") or "")
            arguments, parse_error = _parse_arguments(str(call.get("arguments") or ""))
            tool_started = time.perf_counter()
            if parse_error:
                observation = {"ok": False, "error": parse_error}
                arguments = {}
            else:
                observation = self.tools.execute(tool_name, arguments or {})
            tool_elapsed = int((time.perf_counter() - tool_started) * 1000)

            self.step_index += 1
            self.steps.append(
                {
                    "index": self.step_index,
                    "tool": tool_name,
                    "label": TOOL_LABELS.get(tool_name, tool_name),
                    "arguments": arguments or {},
                    "result": observation,
                    "elapsed_ms": tool_elapsed,
                }
            )

            call_id = str(call.get("id") or f"call_{uuid.uuid4().hex[:10]}")
            message_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments or {}, ensure_ascii=False),
                    },
                }
            )
            tool_messages.append((call_id, observation))

        self.messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": message_calls,
            }
        )
        for call_id, observation in tool_messages:
            self.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": tool_result_json(observation),
                }
            )

    async def _finalize_after_limit(self) -> None:
        """Лимит шагов: попросить модель подвести итог без новых инструментов."""
        self.messages.append(
            {
                "role": "user",
                "content": (
                    "Лимит шагов исчерпан. Сформулируй итоговый ответ по уже собранным "
                    "наблюдениям, без новых вызовов инструментов."
                ),
            }
        )
        try:
            turn = await self._call_model(use_tools=False)
            _merge_usage(self.usage, turn.usage)
            self.answer = turn.text.strip()
            self.finish_reason = turn.finish_reason
            self.status = "done"
        except ProviderError:
            self.answer = ""
            self.status = "error"

    def _result(self) -> AgentRun:
        self.usage["total_tokens"] = max(
            int(self.usage.get("total_tokens") or 0), _usage_total(self.usage)
        )
        answer = self.answer or (
            "Агент не успел сформулировать итог за отведённые шаги. "
            f"Выполнено инструментов: {len(self.steps)}."
        )
        return AgentRun(
            answer=answer,
            steps=self.steps,
            usage=self.usage,
            elapsed_ms=int((time.perf_counter() - self._started) * 1000)
            if self._started else 0,
            finish_reason=self.finish_reason,
            truncated=self.finish_reason == "length",
            stopped_reason=self.stopped_reason,
            tools=self.tools.names,
            missing_tools=self.missing_tools,
        )


async def run_agent(
    active: Provider,
    *,
    model: str,
    prompt: str,
    temperature: float = 0.2,
    reasoning: str = "off",
    max_tokens: int | None = 1_500,
    max_steps: int = 10,
    tools: list[str] | None = None,
    supports_reasoning: bool = False,
    supports_temperature: bool = True,
) -> AgentRun:
    """Совместимая обёртка: создать Agent и выполнить один запуск."""
    from .agent_tools import DEFAULT_REGISTRY

    agent = Agent(
        active,
        DEFAULT_REGISTRY.select(tools),
        AgentConfig(
            model=model,
            temperature=temperature,
            reasoning=reasoning,
            max_tokens=max_tokens,
            max_steps=max_steps,
            supports_reasoning=supports_reasoning,
            supports_temperature=supports_temperature,
        ),
    )
    return await agent.run(prompt)


def _looks_like_tools_error(exc: ProviderError) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("tool", "function calling", "functions"))
