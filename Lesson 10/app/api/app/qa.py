"""Ответы на вопросы по выбранной стратегии контекста для урока 10."""

from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[\wа-яёА-ЯЁ]+", re.IGNORECASE)


def _words(text: str) -> set[str]:
    return {word.lower().replace("ё", "е") for word in _WORD_RE.findall(text) if len(word) > 2}


def answer_question(question: str, row: dict[str, Any]) -> tuple[str, str, bool]:
    """Найти ответ в facts, summary или сообщениях выбранного контекста."""
    words = _words(question)
    if not words:
        return "Задайте вопрос по выбранному диалогу.", "", False

    if row["id"] == "sticky":
        facts = row.get("facts") or {}
        scored = []
        for key, value in facts.items():
            score = len(words & _words(f"{key} {value}"))
            if score:
                scored.append((score, key, value))
        if scored:
            _, key, value = max(scored)
            return f"{key}: {value}", key, True
        return (
            "В текущем блоке facts нет ответа на этот вопрос. "
            "Попробуйте увеличить окно обновления facts.",
            "",
            False,
        )

    candidates: list[tuple[int, str, str]] = []
    if row["id"] == "summary":
        for summary in row.get("included_summaries", []):
            score = len(words & _words(summary["content"]))
            if score:
                candidates.append((score, summary["content"], f"summary №{summary['id']}"))
    else:
        for message in row.get("included_messages", []):
            score = len(words & _words(message["content"]))
            if score:
                candidates.append((score, message["content"], f"№{message['id']}"))

    if candidates:
        _, content, source = max(candidates)
        return content, source, True
    return (
        "В выбранном контексте нет ответа на этот вопрос. "
        "Попробуйте другую стратегию или увеличьте окно.",
        "",
        False,
    )


def context_text(row: dict[str, Any]) -> str:
    if row["id"] == "sticky":
        facts = row.get("facts") or {}
        return "\n".join(f"{key}: {value}" for key, value in facts.items())
    if row["id"] == "summary":
        return "\n".join(item["content"] for item in row.get("included_summaries", []))
    return "\n".join(item["content"] for item in row.get("included_messages", []))
