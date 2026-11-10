"""Сборка окна контекста для запроса к модели."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

SYSTEM_PROMPT = (
    "Ты — ассистент учебного проекта AI Challenge. Продолжай диалог с учётом "
    "сохранённой истории: не переспрашивай то, что пользователь уже сообщил, "
    "и явно опирайся на предыдущие сообщения, когда это уместно.\n"
    "Если история была частично сокращена, не выдумывай пропущенные детали: "
    "скажи, чего не хватает."
)


@dataclass(frozen=True)
class ContextWindow:
    """Сообщения, которые реально уйдут в модель, и статистика отбора."""

    messages: list[dict[str, Any]]
    history: list[dict[str, Any]]
    included: int
    dropped: int
    chars: int


def _model_message(item: dict[str, Any]) -> dict[str, Any]:
    """Строка SQLite → сообщение OpenAI, сохраняя tool calls и наблюдения."""
    message: dict[str, Any] = {
        "role": item["role"],
        "content": item.get("content") or "",
    }
    tool_calls = item.get("tool_calls") or []
    if tool_calls:
        message["tool_calls"] = tool_calls
    if item["role"] == "tool":
        message["tool_call_id"] = item.get("tool_call_id") or ""
        if item.get("name"):
            message["name"] = item["name"]
    return message


def _groups(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Разбить историю на ходы «пользователь → ответ/инструменты».

    Нельзя обрезать историю посередине tool call: иначе модель получит
    assistant.tool_calls без соответствующего role=tool.
    """
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in history:
        if item["role"] == "user" and current:
            groups.append(current)
            current = [item]
        else:
            current.append(item)
    if current:
        groups.append(current)
    return groups


def _chars(items: list[dict[str, Any]]) -> int:
    return sum(len(str(item.get("content") or "")) for item in items)


def build_context(
    history: list[dict[str, Any]],
    prompt: str,
    *,
    max_messages: int,
    max_chars: int,
) -> ContextWindow:
    """Взять последние полные ходы, уложившись в лимиты."""
    groups = _groups(history)
    selected: list[list[dict[str, Any]]] = []
    for group in reversed(groups):
        if selected and sum(len(item) for item in selected) + len(group) > max_messages:
            break
        selected.insert(0, group)

    selected_history = [item for group in selected for item in group]
    while selected_history and _chars(selected_history) + len(prompt) > max_chars:
        # убираем самый старый полный ход, а не отдельное сообщение
        first_group_len = len(selected[0]) if selected else 1
        selected_history = selected_history[first_group_len:]
        if selected:
            selected.pop(0)

    history_messages = [_model_message(item) for item in selected_history]
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history_messages,
        {"role": "user", "content": prompt},
    ]
    return ContextWindow(
        messages=messages,
        history=history_messages,
        included=len(selected_history),
        dropped=len(history) - len(selected_history),
        chars=_chars(messages),
    )


def merge_histories(
    current: list[dict[str, Any]],
    past: list[tuple[str, list[dict[str, Any]]]],
    labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Добавить прошлые диалоги перед текущим, не ломая tool call id.

    Если переданы `labels`, перед каждым архивным диалогом ставится системная
    пометка: иначе модель может принять его за текущую переписку.
    """
    merged: list[dict[str, Any]] = []
    for session_id, history in past:
        if labels is not None:
            label = labels.get(session_id) or "прошлый диалог"
            merged.append(
                {
                    "role": "system",
                    "content": (
                        f"Справочный контекст из прошлого диалога «{label}». "
                        "Это не сообщения текущей сессии; используй его как источник фактов."
                    ),
                }
            )
        safe = re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:16] or "past"
        mapping: dict[str, str] = {}
        for item in history:
            clone = copy.deepcopy(item)
            for call in clone.get("tool_calls") or []:
                old = str(call.get("id") or "")
                new = f"{safe}:{old}" if old else f"{safe}:call"
                mapping[old] = new
                call["id"] = new
            if clone.get("role") == "tool":
                old = str(clone.get("tool_call_id") or "")
                clone["tool_call_id"] = mapping.get(old, f"{safe}:{old}" if old else "")
            merged.append(clone)

    if past and labels is not None:
        merged.append(
            {
                "role": "system",
                "content": (
                    "Конец справочных прошлых диалогов. Ниже — текущая переписка; "
                    "отвечай на последний запрос пользователя."
                ),
            }
        )
    merged.extend(copy.deepcopy(current))
    return merged
