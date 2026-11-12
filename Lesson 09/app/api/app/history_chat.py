"""Ответы на вопросы по выбранной части истории.

Это не вызов модели, а детерминированный поиск по фактам демо-диалога. Так
урок показывает главный эффект управления контекстом: если сообщение с фактом
отброшено, ответить на вопрос по нему нельзя.
"""

from __future__ import annotations

import re
from typing import Any

#: ключевые слова запроса → подстроки, по которым ищем факт в сообщении
FACT_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("адрес", "где находится", "лесная"), ("адрес", "москва, ул. лесная")),
    (("бюджет", "итого"), ("бюджет", "итого")),
    (("стоимость", "сколько стоит", "цена", "сумма"), ("15 156", "₽/м²", "стоимость —")),
    (("оплат", "аванс", "30/40/30"), ("оплата 30/40/30", "аванс")),
    (("срок", "когда", "дата", "сдач"), ("срок сдачи", "этапы:", "31 марта", "31.03.2027", "сдача")),
    (("этап", "контрольн"), ("этапы:", "15 декабря", "1 февраля")),
    (("площад", "метр", "м²"), ("площадь", "м²")),
    (("этаж", "этажност"), ("этажа", "этажность")),
    (("подрядчик", "кто строит", "стройконтур"), ("подрядчик", "стройконтур")),
    (("контакт", "соколов", "телефон", "почта"), ("контакт", "соколова", "телефон")),
    (("риск", "резерв"), ("риск", "резерв")),
    (("штраф", "просрочк"), ("штраф", "просрочк")),
    (("приёмк", "приемк", "комисси"), ("приёмка", "комиссия")),
    (("электр", "вентил", "отопл", "инженер"), ("электрика", "вентиляция", "отопление")),
    (("материал", "фасад", "кровл", "окн"), ("фасад — клинкерный", "кровля — мембрана", "окна — алюминиевый")),
    (("парков", "логист", "доставк", "въезд"), ("парков", "логистик", "доставк", "въезд")),
)

_WORD_RE = re.compile(r"[\wа-яёА-ЯЁ]+", re.IGNORECASE)


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def _question_words(question: str) -> set[str]:
    return {word for word in _WORD_RE.findall(_norm(question)) if len(word) > 2}


def answer_question(question: str, messages: list[dict[str, Any]]) -> tuple[str, list[int]]:
    """Найти ответ в сообщениях, которые реально попали в контекст."""
    query = _norm(question)
    candidates = [item for item in messages if item.get("role") == "assistant"]

    for triggers, needles in FACT_RULES:
        if not any(trigger in query for trigger in triggers):
            continue
        matches = [
            item
            for item in candidates
            if any(needle in _norm(item.get("content", "")) for needle in needles)
        ]
        if matches:
            # Последнее совпадение обычно самое полное (например, итоговая сводка).
            answer = matches[-1]["content"]
            return answer, [matches[-1]["id"]]

    words = _question_words(question)
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in candidates:
        content = _norm(item.get("content", ""))
        score = sum(1 for word in words if word in content)
        if score:
            scored.append((score, item))
    if scored:
        scored.sort(key=lambda pair: (pair[0], pair[1]["id"]))
        best = scored[-1][1]
        return best["content"], [best["id"]]

    return (
        "В выбранной части контекста нет сообщения с ответом на этот вопрос. "
        "Увеличьте лимит сообщений, окно токенов или выберите стратегию «Вся история».",
        [],
    )
