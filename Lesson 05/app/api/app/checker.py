"""Проверка ответа модели против эталона задачи.

Эталон — короткая строка вида «68», «12 фруктов», «18:50, 255 минут».
Сверяем не текст целиком, а все числа/время из эталона: ответ считается верным,
если в нём есть каждое из них. Так «18:50, 255 минут» требует оба значения,
а «68» не засчитывается за «168» или «12,68».
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d{1,2}:\d{2}|\d+(?:[.,]\d+)?")


def normalize(text: str) -> str:
    """Нижний регистр, единые дефисы и пробелы."""
    text = text.lower().replace("ё", "е")
    text = text.replace("—", "-").replace("–", "-").replace("−", "-")
    return re.sub(r"\s+", " ", text).strip()


def expected_tokens(reference: str) -> list[str]:
    """Числа и время из эталона: «18:50, 255 минут» → ['18:50', '255']."""
    return _NUMBER_RE.findall(normalize(reference))


def _canonical(token: str) -> str:
    """18:50 и 18.50 — одно и то же; запятая как десятичный разделитель тоже."""
    return token.replace(":", ".").replace(",", ".")


def answer_numbers(answer: str) -> set[str]:
    """Все числа/время, которые реально назвала модель."""
    return {_canonical(token) for token in _NUMBER_RE.findall(normalize(answer))}


def answer_is_correct(answer: str, reference: str) -> bool:
    """Верен ли ответ: все числа эталона присутствуют в ответе.

    Если в эталоне чисел нет — сверяем нормализованный текст по вхождению.
    """
    if not answer or not answer.strip() or not reference or not reference.strip():
        return False
    tokens = expected_tokens(reference)
    if not tokens:
        return normalize(reference) in normalize(answer)
    found = answer_numbers(answer)
    return all(_canonical(token) in found for token in tokens)
