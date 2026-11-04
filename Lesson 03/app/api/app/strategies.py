"""Способы рассуждений: как просить модель думать.

Каждая стратегия — это пара «system-промпт + правило разбора ответа»:
модель возвращает один текст, а мы делим его на рассуждение и итог по разделителю.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SPLIT_MARKER = "\n---\n"


@dataclass(frozen=True)
class Strategy:
    """Один способ рассуждения."""

    id: str
    label: str
    description: str
    system_prompt: str
    #: показывать ли первую часть ответа как «рассуждение»
    shows_reasoning: bool = True
    #: подсказка, что ожидать от блока рассуждения
    reasoning_hint: str = "Рассуждение"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "shows_reasoning": self.shows_reasoning,
            "reasoning_hint": self.reasoning_hint,
            "notes": list(self.notes),
        }


STRATEGIES: list[Strategy] = [
    Strategy(
        id="direct",
        label="Прямой ответ",
        description="Модель отвечает сразу, без пошаговых рассуждений. Быстро и дешево, "
                    "но на многошаговых задачах ошибается чаще.",
        system_prompt=(
            "Отвечай сразу и по существу. Не рассуждай вслух, не показывай ход мыслей, "
            "не расписывай шаги — только итоговый ответ."
        ),
        shows_reasoning=False,
    ),
    Strategy(
        id="cot",
        label="Пошаговые рассуждения (CoT)",
        description="Просьба «думай по шагам»: модель сначала строит цепочку рассуждений, "
                    "потом даёт ответ после разделителя '---'.",
        system_prompt=(
            "Решай задачу пошагово. Сначала подробно рассуждай: разбери условие, "
            "выдели промежуточные величины, посчитай их. Затем поставь строку '---' "
            "на отдельной строке и после неё дай короткий итоговый ответ."
        ),
        reasoning_hint="Цепочка рассуждений",
    ),
    Strategy(
        id="cot_few_shot",
        label="CoT с примером (few-shot)",
        description="Тот же пошаговый формат, но с готовым примером в system-промпте: "
                    "модель копирует стиль рассуждения, а не придумывает его сама.",
        system_prompt=(
            "Решай задачи по образцу.\n\n"
            "Пример.\n"
            "Вопрос: В корзине 5 яблок, 3 груши и 2 апельсина. Сколько всего фруктов?\n"
            "Рассуждение: яблоки — 5, груши — 3, апельсины — 2. Складываю: 5 + 3 = 8, "
            "8 + 2 = 10. Итого 10 фруктов.\n"
            "---\n"
            "Ответ: 10 фруктов.\n\n"
            "Теперь реши мою задачу в том же формате: сначала блок «Рассуждение», "
            "затем строка '---' на отдельной строке, затем «Ответ»."
        ),
        reasoning_hint="Рассуждение по образцу",
    ),
    Strategy(
        id="plan_solve",
        label="План и решение (Plan-and-Solve)",
        description="Сначала план из шагов, потом выполнение плана. Помогает на задачах, "
                    "где важно не потерять условие.",
        system_prompt=(
            "Реши задачу в два этапа.\n"
            "1) Составь короткий план: пронумерованные шаги, что и в каком порядке нужно сделать.\n"
            "2) Выполни план по шагам, показывая вычисления.\n"
            "Потом поставь строку '---' на отдельной строке и дай итоговый ответ."
        ),
        reasoning_hint="План и шаги",
    ),
    Strategy(
        id="self_check",
        label="Ответ с самопроверкой",
        description="Модель сразу отвечает, затем отдельно проверяет себя и при "
                    "необходимости исправляет ответ.",
        system_prompt=(
            "Сначала дай ответ на вопрос.\n"
            "Затем поставь строку '---' на отдельной строке и напиши блок «Проверка»: "
            "перепроверь вычисления и допущения, укажи, есть ли ошибка. "
            "Если ошибка есть — приведи исправленный итоговый ответ в конце блока."
        ),
        reasoning_hint="Проверка",
    ),
]

STRATEGIES_BY_ID: dict[str, Strategy] = {item.id: item for item in STRATEGIES}
STRATEGY_IDS: tuple[str, ...] = tuple(item.id for item in STRATEGIES)
DEFAULT_STRATEGY = STRATEGIES[0].id


def get_strategy(strategy_id: str) -> Strategy:
    try:
        return STRATEGIES_BY_ID[strategy_id]
    except KeyError as exc:  # noqa: TRY003 - сообщение уходит в 400
        raise KeyError(f"Неизвестный способ рассуждения: {strategy_id}") from exc


def split_answer(strategy: Strategy, text: str) -> tuple[str, str]:
    """Разделить ответ на (рассуждение, итог) по маркеру стратегии."""
    if not strategy.shows_reasoning:
        return "", text.strip()
    head, separator, tail = text.partition(SPLIT_MARKER)
    if not separator:
        return text.strip(), ""
    return head.strip(), tail.strip()
