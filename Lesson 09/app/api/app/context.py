"""Стратегии управления контекстом для урока 09."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tokenizer import count_tokens

STRATEGY_LABELS = {
    "budget": "Бюджет токенов",
    "last": "Последние N сообщений",
    "full": "Вся история",
}


@dataclass(frozen=True)
class ContextSelection:
    included: list[dict[str, Any]]
    dropped: list[dict[str, Any]]
    available: int
    message_budget: int
    included_tokens: int
    context_tokens: int
    dropped_tokens: int
    overflow: int
    fits: bool


def build_context(
    messages: list[dict[str, Any]],
    *,
    strategy: str,
    max_messages: int,
    max_tokens: int,
    reserve_tokens: int,
    system_tokens: int = 20,
) -> ContextSelection:
    if strategy not in STRATEGY_LABELS:
        raise ValueError(f"Неизвестная стратегия контекста: {strategy}")

    available = max(0, max_tokens - reserve_tokens)
    message_budget = max(0, available - system_tokens)
    tokens_by_id = {item["id"]: count_tokens(item.get("content") or "") for item in messages}

    if strategy == "full":
        selected = list(messages)
    elif strategy == "last":
        selected = list(messages[-max_messages:]) if max_messages > 0 else []
    else:
        selected = []
        used = 0
        for item in reversed(messages):
            if len(selected) >= max_messages:
                break
            cost = tokens_by_id[item["id"]]
            if selected and used + cost > message_budget:
                break
            if not selected and cost > message_budget:
                break
            selected.insert(0, item)
            used += cost

    included_ids = {item["id"] for item in selected}
    dropped = [item for item in messages if item["id"] not in included_ids]
    included_tokens = sum(tokens_by_id[item["id"]] for item in selected)
    context_tokens = included_tokens + system_tokens
    return ContextSelection(
        included=selected,
        dropped=dropped,
        available=available,
        message_budget=message_budget,
        included_tokens=included_tokens,
        context_tokens=context_tokens,
        dropped_tokens=sum(tokens_by_id[item["id"]] for item in dropped),
        overflow=max(0, included_tokens - message_budget),
        fits=included_tokens <= message_budget,
    )


def build_summary_context(
    summaries: list[dict[str, Any]],
    *,
    max_tokens: int,
    reserve_tokens: int,
    system_tokens: int = 20,
) -> ContextSelection:
    """Контекст из отдельно хранимых summary вместо полной истории."""
    items = [
        {
            "id": 1000 + int(item["id"]),
            "role": "assistant",
            "content": item.get("content") or "",
            "tokens": item.get("tokens") or count_tokens(item.get("content") or ""),
        }
        for item in summaries
    ]
    return build_context(
        items,
        strategy="budget",
        max_messages=max(1, len(items)),
        max_tokens=max_tokens,
        reserve_tokens=reserve_tokens,
        system_tokens=system_tokens,
    )
