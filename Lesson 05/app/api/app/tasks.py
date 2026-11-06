"""Пять задач для сравнения моделей: от арифметики до головоломки.

Задача — это один prompt с эталонным ответом и уровнем сложности. Сложность
растёт сверху вниз: на `low` модели обычно сходятся, на `expert` — расходятся,
и разница в токенах, времени и стоимости становится видна в таблице сравнения.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Уровни сложности по возрастанию — ровно пять, по одной задаче на уровень
COMPLEXITY_ORDER = ("low", "medium", "high", "very high", "expert")


@dataclass(frozen=True)
class LogicTask:
    """Одна задача сравнения: промпт, уровень сложности и эталонный ответ."""

    id: str
    title: str
    complexity: str
    text: str
    reference: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "complexity": self.complexity,
            "text": self.text,
            "reference": self.reference,
        }


TASKS: list[LogicTask] = [
    LogicTask(
        id="arithmetic",
        title="Арифметика в одно действие",
        complexity="low",
        text="Сколько будет 17 × 4? Ответь только числом, без пояснений.",
        reference="68",
    ),
    LogicTask(
        id="fruits",
        title="Корзина с фруктами",
        complexity="medium",
        text=(
            "В корзине 5 яблок, 3 груши и 2 апельсина. Два яблока съели, "
            "а потом добавили 4 груши. Сколько всего фруктов в корзине?"
        ),
        reference="12 фруктов",
    ),
    LogicTask(
        id="train",
        title="Поезд с задержкой",
        complexity="high",
        text=(
            "Поезд отправляется в 14:35 и едет 3 часа 50 минут, но на одной станции "
            "стоит ещё 25 минут сверх графика. Во сколько он прибудет и сколько всего "
            "минут займёт дорога?"
        ),
        reference="18:50, 255 минут",
    ),
    LogicTask(
        id="warehouse",
        title="Склад и проценты",
        complexity="very high",
        text=(
            "На складе 240 коробок. В первый день вывезли 3/8 всех коробок, во второй — "
            "40% остатка, в третий — половину того, что осталось после второго дня. "
            "Сколько коробок осталось на складе?"
        ),
        reference="45 коробок",
    ),
    LogicTask(
        id="bridge",
        title="Мост с фонариком",
        complexity="expert",
        text=(
            "Четыре человека должны перейти мост ночью с одним фонариком. Одновременно "
            "идут не больше двух, фонарик обратно кто-то должен возвращать. Скорости: "
            "1, 2, 5 и 10 минут на переход. За какое минимальное время все окажутся на "
            "другой стороне? Ответь числом минут и приведи порядок переходов."
        ),
        reference="17 минут",
    ),
]

TASKS_BY_ID: dict[str, LogicTask] = {task.id: task for task in TASKS}
DEFAULT_TASK_ID = "fruits"
