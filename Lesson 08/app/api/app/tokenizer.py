"""Оценка токенов без внешнего токенизатора.

Это учебная аппроксимация: слова и знаки пунктуации считаются отдельными
единицами. Она не совпадает с BPE конкретной модели, но показывает порядок
величины и позволяет отрабатывать бюджет контекста.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
WORD_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class TokenPiece:
    index: int
    text: str


def token_pieces(text: str, limit: int | None = None) -> list[TokenPiece]:
    pieces = [
        TokenPiece(index=index, text=match.group())
        for index, match in enumerate(TOKEN_RE.finditer(text or ""), 1)
    ]
    return pieces[:limit] if limit is not None else pieces


def count_tokens(text: str) -> int:
    return sum(1 for _ in TOKEN_RE.finditer(text or ""))


def count_words(text: str) -> int:
    return sum(1 for _ in WORD_RE.finditer(text or ""))


def truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, int]:
    """Обрезать по границе токена, сохранив исходный текст до неё."""
    if max_tokens <= 0:
        return "", 0
    matches = list(TOKEN_RE.finditer(text or ""))
    if len(matches) <= max_tokens:
        return text or "", len(matches)
    return text[: matches[max_tokens - 1].end()], max_tokens


def token_stats(text: str, limit: int = 120) -> dict[str, Any]:
    pieces = token_pieces(text)
    words = count_words(text)
    tokens = len(pieces)
    return {
        "chars": len(text or ""),
        "words": words,
        "tokens": tokens,
        "tokens_per_word": round(tokens / words, 2) if words else 0.0,
        "chars_per_token": round(len(text or "") / tokens, 2) if tokens else 0.0,
        "preview": [
            {"index": piece.index, "text": piece.text}
            for piece in pieces[:limit]
        ],
        "preview_truncated": len(pieces) > limit,
    }


def repeat_to_tokens(text: str, target_tokens: int) -> str:
    """Повторить текст до целевого числа токенов и обрезать по границе."""
    if not text or target_tokens <= 0:
        return ""
    base_tokens = count_tokens(text)
    if base_tokens == 0:
        return ""
    repeats = max(1, math.ceil(target_tokens / base_tokens))
    grown = (text + "\n\n") * repeats
    return truncate_to_tokens(grown, target_tokens)[0]
