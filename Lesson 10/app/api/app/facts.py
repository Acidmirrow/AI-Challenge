"""Sticky facts / Key-Value memory для урока 10.

Facts — отдельный словарь «ключ → значение». Он обновляется после каждого
сообщения пользователя по последним N сообщениям. Старые facts сохраняются:
новые значения добавляются, найденные ключи заменяются.
"""

from __future__ import annotations

import re
from typing import Any

from .tokenizer import count_tokens

#: Ключ: значение; значения разделяются точкой с запятой.
PAIR_RE = re.compile(
    r"(?P<key>[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9 /-]{1,35}):\s*(?P<value>[^;\n]+)"
)
#: Служебные заголовки, которые не являются фактами проекта.
IGNORED_KEYS = {"Сводка", "Главное", "Проверка"}


def extract_facts(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in PAIR_RE.finditer(text):
        key = match.group("key").strip()
        value = match.group("value").strip().rstrip(".")
        if key in IGNORED_KEYS or not value:
            continue
        found[key] = value
    return found


def build_facts(messages: list[dict[str, Any]], window: int) -> tuple[dict[str, str], int]:
    """Обновлять facts после каждого пользовательского сообщения.

    ``window`` — сколько последних сообщений (включая текущее) участвует
    в обновлении facts. Возвращает накопленный словарь и число обновлений.
    """
    step = max(1, min(window, len(messages) or 1))
    facts: dict[str, str] = {}
    updates = 0
    for index, item in enumerate(messages):
        if item.get("role") != "user":
            continue
        updates += 1
        recent = messages[max(0, index - step + 1) : index + 1]
        for message in recent:
            facts.update(extract_facts(message.get("content") or ""))
    return facts, updates


def facts_text(facts: dict[str, str]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in facts.items())


def facts_stats(facts: dict[str, str]) -> dict[str, Any]:
    text = facts_text(facts)
    return {
        "facts": facts,
        "facts_count": len(facts),
        "facts_tokens": count_tokens(text),
        "facts_text": text,
    }
