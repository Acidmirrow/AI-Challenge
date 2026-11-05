"""Пять типов задач и по три варианта сложности в каждом.

Кнопка на фронте — это тип задачи (точный ответ, логика, текст, названия,
головоломка), а сложность выбирается уже внутри: у каждого типа три варианта
от `low` до `high`. Так один и тот же экран проверяет и простые, и тяжёлые
промпты, не смешивая их в одном списке.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Variant:
    """Один промпт внутри типа задачи."""

    id: str
    complexity: str
    text: str
    reference: str = ""
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "complexity": self.complexity,
            "text": self.text,
            "reference": self.reference,
            "note": self.note,
        }


@dataclass(frozen=True)
class Task:
    """Тип задачи: кнопка на фронте и три варианта сложности."""

    id: str
    label: str
    kind: str
    variants: tuple[Variant, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "variants": [variant.as_dict() for variant in self.variants],
        }

    def variant(self, variant_id: str) -> Variant | None:
        return next((item for item in self.variants if item.id == variant_id), None)

    @property
    def default_variant(self) -> Variant:
        return self.variants[0]


TASKS: list[Task] = [
    Task(
        id="arithmetic",
        label="Точный ответ",
        kind="single-answer",
        variants=(
            Variant(
                id="arithmetic-low",
                complexity="low",
                text="Сколько будет 17 × 4? Ответь только числом, без пояснений.",
                reference="68",
                note="Один правильный ответ. При высокой температуре модель может «поплыть» даже здесь.",
            ),
            Variant(
                id="arithmetic-medium",
                complexity="medium",
                text="Сколько будет 23 × 17? Ответь только числом, без пояснений.",
                reference="391",
                note="Числа крупнее — больше шансов на арифметическую ошибку при разбросе.",
            ),
            Variant(
                id="arithmetic-high",
                complexity="high",
                text=(
                    "Вычисли: (48 ÷ 6) × (125 − 117) + 39. Ответь только числом, без пояснений."
                ),
                reference="103",
                note="Несколько действий: видно, как температура влияет на аккуратность счёта.",
            ),
        ),
    ),
    Task(
        id="logic",
        label="Логическая задача",
        kind="single-answer",
        variants=(
            Variant(
                id="logic-low",
                complexity="low",
                text=(
                    "В корзине 5 яблок, 3 груши и 2 апельсина. Два яблока съели, "
                    "а потом добавили 4 груши. Сколько всего фруктов в корзине?"
                ),
                reference="12 фруктов",
                note="Два действия — простая проверка аккуратности.",
            ),
            Variant(
                id="logic-medium",
                complexity="medium",
                text=(
                    "Поезд отправляется в 14:35 и едет 3 часа 50 минут, но на одной станции "
                    "стоит ещё 25 минут сверх графика. Во сколько он прибудет и сколько всего "
                    "минут займёт дорога?"
                ),
                reference="18:50, 255 минут",
                note="Время и единицы: частая точка потери при высокой температуре.",
            ),
            Variant(
                id="logic-high",
                complexity="high",
                text=(
                    "На складе 240 коробок. В первый день вывезли 3/8 всех коробок, во второй — "
                    "40% остатка, в третий — половину того, что осталось после второго дня. "
                    "Сколько коробок осталось на складе?"
                ),
                reference="45 коробок",
                note="Дроби и проценты подряд — самый чувствительный вариант среди логических.",
            ),
        ),
    ),
    Task(
        id="writing",
        label="Генерация текста",
        kind="text",
        variants=(
            Variant(
                id="writing-low",
                complexity="low",
                text="Напиши одно предложение о пользе утренних прогулок.",
                note="Правильного ответа нет: смотрите, как меняется формулировка.",
            ),
            Variant(
                id="writing-medium",
                complexity="medium",
                text=(
                    "Напиши короткий абзац (3–4 предложения) о пользе утренних прогулок. "
                    "Без списков и заголовков."
                ),
                note="Связность и стиль: при низкой температуре текст обычно суше.",
            ),
            Variant(
                id="writing-high",
                complexity="high",
                text=(
                    "Напиши три коротких абзаца о пользе утренних прогулок: первый — почему это "
                    "работает, второй — как начать с нуля, третий — типичная ошибка новичка. "
                    "Без списков и заголовков."
                ),
                note="Длинный связный текст: на высокой температуре чаще теряется структура.",
            ),
        ),
    ),
    Task(
        id="names",
        label="Варианты названий",
        kind="variants",
        variants=(
            Variant(
                id="names-low",
                complexity="low",
                text=(
                    "Придумай 3 варианта названия для кофейни рядом с парком. "
                    "Каждый вариант — отдельной строкой, без пояснений."
                ),
                note="Малая выборка: проще заметить, какие варианты повторяются.",
            ),
            Variant(
                id="names-medium",
                complexity="medium",
                text=(
                    "Придумай 5 вариантов названия для кофейни рядом с парком. "
                    "Каждый вариант — отдельной строкой, без пояснений."
                ),
                note="Чем выше температура, тем неожиданнее варианты — и тем выше риск бессмыслицы.",
            ),
            Variant(
                id="names-high",
                complexity="high",
                text=(
                    "Придумай 7 вариантов названия для кофейни рядом с парком в разных стилях: "
                    "два природных, два ироничных, два минималистичных и один на английском. "
                    "Каждый вариант — отдельной строкой, без пояснений."
                ),
                note="Жёсткие рамки стилей: видно, держит ли модель инструкцию при разбросе.",
            ),
        ),
    ),
    Task(
        id="puzzle",
        label="Головоломка",
        kind="single-answer",
        variants=(
            Variant(
                id="puzzle-low",
                complexity="low",
                text=(
                    "Есть 9 одинаковых на вид монет, одна из них фальшивая и легче остальных. "
                    "Есть чашечные весы без гирь. За какое минимальное число взвешиваний можно "
                    "гарантированно найти фальшивую монету?"
                ),
                reference="2 взвешивания",
                note="Классическая разминка: деление на три группы.",
            ),
            Variant(
                id="puzzle-medium",
                complexity="medium",
                text=(
                    "Есть 12 одинаковых на вид монет, одна из них фальшивая: она легче или тяжелее "
                    "настоящей, но неизвестно, в какую сторону. Есть чашечные весы без гирь. "
                    "За какое минимальное число взвешиваний можно гарантированно найти фальшивую "
                    "монету и определить, легче она или тяжелее? Ответь числом и коротко объясни."
                ),
                reference="3 взвешивания",
                note="Известная головоломка: при высокой температуре рассуждение часто разваливается.",
            ),
            Variant(
                id="puzzle-high",
                complexity="high",
                text=(
                    "Четыре человека должны перейти мост ночью с одним фонариком. Одновременно "
                    "идут не больше двух, фонарик обратно кто-то должен возвращать. Скорости: "
                    "1, 2, 5 и 10 минут на переход. За какое минимальное время все окажутся на "
                    "другой стороне? Ответь числом минут и приведи порядок переходов."
                ),
                reference="17 минут",
                note="Самая тяжёлая: нужно найти неочевидную оптимальную стратегию.",
            ),
        ),
    ),
]


TASKS_BY_ID: dict[str, Task] = {task.id: task for task in TASKS}
DEFAULT_TASK_ID = "arithmetic"


def find_variant(task_id: str, variant_id: str) -> tuple[Task, Variant] | None:
    """Найти пару «тип задачи + вариант» по идентификаторам."""
    task = TASKS_BY_ID.get(task_id)
    if task is None:
        return None
    variant = task.variant(variant_id) or task.default_variant
    return task, variant
