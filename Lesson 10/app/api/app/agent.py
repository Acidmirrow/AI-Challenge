"""Контекстный агент урока 10.

Агент генерирует ветвящийся диалог, собирает контекст по выбранной стратегии
и отвечает на вопрос. Три стратегии сжатия (Sliding window, Sticky facts,
Summary блоки) дополнены режимом без сжатия — полной историей.
"""

from __future__ import annotations

from typing import Any

from .generator import generate_dialogue
from .llm import chat_with_context
from .qa import answer_question, context_text
from .strategies import build_strategies


class ContextAgent:
    """Агент управления контекстом с четырьмя режимами."""

    name = "Context Strategy Agent"
    strategies = ("sliding", "sticky", "summary", "full")

    def generate(self) -> dict[str, Any]:
        return generate_dialogue()

    def rows(
        self,
        messages: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        *,
        sliding_window: int,
        facts_window: int,
    ) -> list[dict[str, Any]]:
        return build_strategies(
            messages,
            summaries,
            sliding_window=sliding_window,
            facts_window=facts_window,
        )

    def ask(
        self,
        messages: list[dict[str, Any]],
        summaries: list[dict[str, Any]],
        strategy: str,
        question: str,
        *,
        sliding_window: int,
        facts_window: int,
    ) -> dict[str, Any]:
        rows = self.rows(
            messages,
            summaries,
            sliding_window=sliding_window,
            facts_window=facts_window,
        )
        row = next((item for item in rows if item["id"] == strategy), None)
        if row is None:
            return {"answer": "Неизвестная стратегия.", "source": "", "found": False}
        answer, source, found = answer_question(question, row)
        model_answer, model = chat_with_context(question, context_text(row))
        if model != "fallback":
            answer = model_answer
        return {
            "answer": answer,
            "source": source,
            "found": found,
            "strategy": strategy,
            "context": row,
        }
