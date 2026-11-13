"""Стратегии контекста и их сравнение для урока 10."""

from __future__ import annotations

from typing import Any

from .facts import build_facts, facts_stats
from .tokenizer import count_tokens

STRATEGIES = [
    {
        "id": "sliding",
        "label": "Sliding window",
        "description": "Хранит последние N сообщений; все остальные отбрасываются.",
    },
    {
        "id": "sticky",
        "label": "Sticky facts / Key-Value memory",
        "description": (
            "Отдельный блок facts «ключ → значение», обновляется после каждого "
            "сообщения пользователя. Можно задать, сколько последних сообщений "
            "участвует в обновлении."
        ),
    },
    {
        "id": "summary",
        "label": "Summary блоки",
        "description": "Полная история заменяется summary каждых 10 сообщений.",
    },
    {
        "id": "full",
        "label": "Без сжатия — вся история",
        "description": "В запрос уходит вся история диалога.",
    },
]


def _messages_tokens(items: list[dict[str, Any]]) -> int:
    return sum(int(item.get("tokens") or count_tokens(item.get("content") or "")) for item in items)


def build_strategies(
    messages: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
    *,
    sliding_window: int,
    facts_window: int,
) -> list[dict[str, Any]]:
    n = max(1, min(sliding_window, len(messages)))

    sliding_messages = messages[-n:]
    sliding = {
        "id": "sliding",
        "label": "Sliding window",
        "parameter": f"N = {n}",
        "messages_count": len(sliding_messages),
        "summaries_count": 0,
        "facts_count": 0,
        "tokens": _messages_tokens(sliding_messages),
        "dropped_messages": len(messages) - len(sliding_messages),
        "included_messages": sliding_messages,
        "included_summaries": [],
        "facts": {},
        "facts_updates": 0,
    }

    facts, updates = build_facts(messages, facts_window)
    sticky = {
        "id": "sticky",
        "label": "Sticky facts / Key-Value memory",
        "parameter": f"facts из {max(1, min(facts_window, len(messages)))} последних сообщений",
        "messages_count": 0,
        "summaries_count": 0,
        "facts_count": len(facts),
        "tokens": int(facts_stats(facts)["facts_tokens"]),
        "dropped_messages": len(messages),
        "included_messages": [],
        "included_summaries": [],
        "facts": facts,
        "facts_updates": updates,
    }

    summary = {
        "id": "summary",
        "label": "Summary блоки",
        "parameter": f"{len(summaries)} summary",
        "messages_count": 0,
        "summaries_count": len(summaries),
        "facts_count": 0,
        "tokens": _messages_tokens(summaries),
        "dropped_messages": 0,
        "included_messages": [],
        "included_summaries": summaries,
        "facts": {},
        "facts_updates": 0,
    }

    full = {
        "id": "full",
        "label": "Без сжатия — вся история",
        "parameter": "без сжатия",
        "messages_count": len(messages),
        "summaries_count": 0,
        "facts_count": 0,
        "tokens": _messages_tokens(messages),
        "dropped_messages": 0,
        "included_messages": messages,
        "included_summaries": [],
        "facts": {},
        "facts_updates": 0,
    }

    return [sliding, sticky, summary, full]
