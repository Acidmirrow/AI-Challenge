"""Генератор уникального демо-диалога для урока 10.

30 общих сообщений (ствол), затем три независимые ветки по 10–15 сообщений.
Ствол и ветки генерируются заново при каждом запросе, поэтому контекст не
кэшируется между генерациями.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from typing import Any

from .tokenizer import count_tokens

TOPICS = (
    {
        "name": "Городская оранжерея «Верде»",
        "kind": "оранжерея",
        "location": "Москва, ул. Ботаническая, 7",
        "constraint": "уровень шума не выше 40 дБ",
        "metric": "12 000 посетителей в месяц",
        "risk": "задержка поставки стекла",
        "acceptance": "проверка климата и полива",
    },
    {
        "name": "Кинофестиваль «Северный кадр»",
        "kind": "фестиваль",
        "location": "Санкт-Петербург, наб. реки Мойки, 12",
        "constraint": "не более 600 гостей одновременно",
        "metric": "48 показов за четыре дня",
        "risk": "перенос одного из показов",
        "acceptance": "проверка звука и расписания",
    },
    {
        "name": "Логистический хаб «Орбита»",
        "kind": "хаб",
        "location": "Казань, ул. Складская, 4",
        "constraint": "приёмка не более 20 машин в час",
        "metric": "1 800 отправлений в сутки",
        "risk": "перегрузка зоны разгрузки",
        "acceptance": "тест маршрутов и весового контроля",
    },
    {
        "name": "Миграция CRM «Атлас»",
        "kind": "миграция",
        "location": "удалённая команда, офис в Москве",
        "constraint": "простой не более 4 часов",
        "metric": "99,9% успешных запросов",
        "risk": "потеря исторических сделок",
        "acceptance": "сверка 100% контрольных записей",
    },
    {
        "name": "Ресторан «Тёплый цех»",
        "kind": "ресторан",
        "location": "Екатеринбург, ул. Малышева, 21",
        "constraint": "открытие не раньше 10:00",
        "metric": "90 посадочных мест",
        "risk": "задержка согласования вентиляции",
        "acceptance": "проверка кухни и вентиляции",
    },
    {
        "name": "Экспедиция «Полюс-12»",
        "kind": "экспедиция",
        "location": "Мурманская область, база «Северная»",
        "constraint": "связь только два раза в сутки",
        "metric": "12 участников и 6 дней",
        "risk": "ухудшение погоды",
        "acceptance": "проверка снаряжения и связи",
    },
)

PEOPLE = ("Анна Ветрова", "Илья Соколов", "Мария Лебедева", "Артём Крылов", "Ольга Миронова")

CONTRACTORS = (
    "ООО «Контур-Сервис»",
    "ООО «Северная сборка»",
    "ООО «МостПроект»",
    "ООО «Атлас-Интеграция»",
    "ООО «Тёплый контур»",
)

BRANCH_SPECS = (
    {
        "id": "parallel",
        "label": "Ускорение: параллельные работы",
        "description": "Проектирование и закупка идут одновременно, срок сокращается.",
        "questions": (
            "Переключаемся на ветку «{label}». Какие работы запускаем параллельно?",
            "Кого добавляем на монтаж, чтобы ускорить этап?",
            "Где возможна рассинхронизация поставок?",
            "Какой новый срок и дополнительный бюджет у ускоренной ветки?",
            "Кто согласует дополнительный резерв?",
            "Как поймём, что ускорение сработало?",
            "Сформируй итог ветки «{label}».",
        ),
        "budget_delta": (150_000, 600_000),
        "days_delta": -42,
        "change": "запустить проектирование и закупку параллельно",
        "added": "вторая бригада на монтаже",
        "removed": "последовательное согласование этапов",
        "risk": "рассинхронизация поставок",
        "metric": "сократить срок на шесть недель",
        "decision": "согласовать дополнительный резерв и поставщика",
    },
    {
        "id": "saving",
        "label": "Экономия: сокращение бюджета",
        "description": "Часть работ переносится на следующий этап, бюджет уменьшается.",
        "questions": (
            "Переходим в ветку «{label}». Какие работы сокращаем в первую очередь?",
            "Что переносим на следующий этап ради экономии?",
            "Где экономия создаёт риск нехватки резерва?",
            "Какая новая смета и срок после сокращения?",
            "Кто утверждает перечень необязательных работ?",
            "Как проверим, что бюджет действительно удержан?",
            "Подведи итог экономной ветки «{label}».",
        ),
        "budget_delta": (-750_000, -200_000),
        "days_delta": 30,
        "change": "сократить первый этап и перенести необязательные работы",
        "added": "ручной контроль вместо части автоматики",
        "removed": "второй контур резервирования",
        "risk": "нехватка резерва при сбое",
        "metric": "удержать бюджет в пределах новой сметы",
        "decision": "зафиксировать перечень необязательных работ",
    },
    {
        "id": "pilot",
        "label": "Пилот: один участок",
        "description": "Сначала запускается один участок, остальные — после проверки.",
        "questions": (
            "Запускаем ветку «{label}». На каком участке начинаем пилот?",
            "Какие работы входят в пилотный контур?",
            "Что может не показать пилот на одном участке?",
            "Какие метрики и срок у пилотного запуска?",
            "Кто отвечает за критерий расширения пилота?",
            "Как фиксируем решение о масштабировании?",
            "Собери итог пилотной ветки «{label}».",
        ),
        "budget_delta": (-500_000, 100_000),
        "days_delta": 14,
        "change": "запустить пилот на одном участке",
        "added": "отдельный контур наблюдения за метриками",
        "removed": "одновременный запуск всех участков",
        "risk": "пилот не покажет эффект на масштабе",
        "metric": "подтвердить метрику на одном участке",
        "decision": "определить критерий расширения пилота",
    },
)

FACT_KEYS = (
    "Проект",
    "Код",
    "Бюджет",
    "Срок",
    "Локация",
    "Ответственный",
    "Ограничение",
    "Метрика",
    "Этапы",
    "Подрядчик",
    "Договор",
    "Риск",
    "Резерв",
    "Отчётность",
    "Периодичность",
    "Приёмка",
    "Гарантия",
)


def _money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def _summary(facts: dict[str, str], keys: tuple[str, ...]) -> str:
    parts = [f"{key}: {facts[key]}" for key in keys if facts.get(key)]
    return "; ".join(parts) + "."


def _make_branch(
    rng: random.Random,
    facts: dict[str, str],
    spec: dict[str, Any],
    *,
    start_id: int,
    budget: int,
    deadline: date,
    reserve: int,
    lead: str,
) -> dict[str, Any]:
    branch_budget = budget + rng.randrange(*spec["budget_delta"])
    branch_deadline = (deadline + timedelta(days=spec["days_delta"])).isoformat()
    branch_reserve = max(50_000, reserve + rng.randrange(-80_000, 160_000))
    branch_lead = lead if rng.random() < 0.5 else rng.choice(PEOPLE)
    branch = {
        "id": spec["id"],
        "label": spec["label"],
        "description": spec["description"],
        "messages": [],
        "summaries": [],
        "facts_seed": {
            "Ветка": spec["label"],
            "Бюджет ветки": _money(branch_budget),
            "Срок ветки": branch_deadline,
            "Риск ветки": spec["risk"],
            "Метрика ветки": spec["metric"],
        },
        "checkpoints": [],
    }

    questions = [question.format(label=spec["label"]) for question in spec["questions"]]
    pairs = (
        ("user", questions[0]),
        (
            "assistant",
            f"Ветка: {spec['change']}; бюджет: {_money(branch_budget)}; "
            f"срок: {branch_deadline}.",
        ),
        ("user", questions[1]),
        (
            "assistant",
            f"Добавляем: {spec['added']}; исключаем: {spec['removed']}.",
        ),
        ("user", questions[2]),
        (
            "assistant",
            f"Риск: {spec['risk']}; резерв: {_money(branch_reserve)}; "
            "контроль: еженедельная проверка.",
        ),
        ("user", questions[3]),
        (
            "assistant",
            f"Метрика: {spec['metric']}; ответственный: {branch_lead}; "
            "отчётность: каждый вторник.",
        ),
        ("user", questions[4]),
        (
            "assistant",
            f"Решение: {spec['decision']}; зависимость: {facts['Подрядчик']}.",
        ),
        ("user", questions[5]),
        (
            "assistant",
            f"Проверка: {spec['metric']}; контроль: {spec['decision']}.",
        ),
        ("user", questions[6]),
        (
            "assistant",
            f"Итог: {spec['label']}, бюджет {_money(branch_budget)}, "
            f"срок {branch_deadline}, риск «{spec['risk']}».",
        ),
    )
    count = rng.choice((10, 12, 14))
    for index, (role, content) in enumerate(pairs[:count], 1):
        branch["messages"].append(
            {
                "id": start_id + index - 1,
                "role": role,
                "content": content,
                "tokens": count_tokens(content),
            }
        )
    summary_content = (
        f"Ветка {spec['label']}: {spec['change']}; бюджет {_money(branch_budget)}; "
        f"срок {branch_deadline}; риск {spec['risk']}; метрика {spec['metric']}; "
        f"решение {spec['decision']}."
    )
    branch["checkpoints"] = [
        {"id": f"{spec['id']}-start", "message_id": start_id, "label": "начало ветки"},
        {
            "id": f"{spec['id']}-end",
            "message_id": start_id + len(branch["messages"]) - 1,
            "label": "конец ветки",
        },
    ]
    branch["summaries"].append(
        {
            "id": 4,
            "from_id": start_id,
            "to_id": start_id + len(branch["messages"]) - 1,
            "content": summary_content,
            "tokens": count_tokens(summary_content),
        }
    )
    return branch


def generate_dialogue(seed: int | None = None) -> dict[str, Any]:
    rng = random.Random(seed)
    topic = rng.choice(TOPICS)
    code = f"PRJ-{rng.randint(100, 999)}-{rng.choice('ABCDEFGH')}"
    budget = rng.randrange(2_400_000, 9_600_000, 50_000)
    deadline = date(2027, 1, 1) + timedelta(days=rng.randint(60, 540))
    lead_date = deadline - timedelta(days=rng.randint(45, 120))
    middle_date = deadline - timedelta(days=rng.randint(15, 40))
    reserve = rng.randrange(80_000, 400_000, 10_000)
    lead = rng.choice(PEOPLE)
    contractor = rng.choice(CONTRACTORS)
    facts = {
        "Проект": topic["name"],
        "Бюджет": _money(budget),
        "Срок": deadline.isoformat(),
        "Локация": topic["location"],
        "Ответственный": lead,
        "Ограничение": topic["constraint"],
        "Метрика": topic["metric"],
        "Этапы": f"{lead_date.isoformat()} — проектирование, {middle_date.isoformat()} — основной этап, {deadline.isoformat()} — сдача",
        "Подрядчик": contractor,
        "Договор": f"фиксированная смета, аванс 30% — {_money(int(budget * 0.3))}",
        "Риск": topic["risk"],
        "Резерв": _money(reserve),
        "Отчётность": "еженедельный отчёт и демо в конце этапа",
        "Периодичность": "каждый вторник в 10:00",
        "Приёмка": topic["acceptance"],
        "Гарантия": "24 месяца",
    }

    pairs = (
        ("user", f"Собери вводные по проекту «{topic['name']}»."),
        ("assistant", f"Проект: {facts['Проект']}."),
        ("user", "Какой бюджет и срок?"),
        ("assistant", f"Бюджет: {facts['Бюджет']}; Срок: {facts['Срок']}."),
        ("user", "Кто отвечает и где площадка?"),
        (
            "assistant",
            f"Ответственный: {facts['Ответственный']}; Локация: {facts['Локация']}.",
        ),
        ("user", "Какие ограничения и целевой показатель?"),
        (
            "assistant",
            f"Ограничение: {facts['Ограничение']}; Метрика: {facts['Метрика']}.",
        ),
        ("user", "Назови контрольные этапы."),
        ("assistant", f"Этапы: {facts['Этапы']}."),
        ("user", "Кто подрядчик и какой договор?"),
        (
            "assistant",
            f"Подрядчик: {facts['Подрядчик']}; Договор: {facts['Договор']}.",
        ),
        ("user", "Какие риски и резерв?"),
        ("assistant", f"Риск: {facts['Риск']}; Резерв: {facts['Резерв']}."),
        ("user", "Как построена отчётность?"),
        (
            "assistant",
            f"Отчётность: {facts['Отчётность']}; Периодичность: {facts['Периодичность']}.",
        ),
        ("user", "Как будет проходить приёмка?"),
        (
            "assistant",
            f"Приёмка: {facts['Приёмка']}; Гарантия: {facts['Гарантия']}.",
        ),
        ("user", "Что проверить на площадке в первую очередь?"),
        (
            "assistant",
            f"Проверка: {facts['Приёмка']}; Доступ: согласовать пропуска за сутки.",
        ),
        ("user", "Сформируй краткую сводку."),
        (
            "assistant",
            f"Сводка: проект {facts['Проект']}, бюджет {facts['Бюджет']}, "
            f"срок {facts['Срок']}, ответственный {facts['Ответственный']}.",
        ),
        ("user", "Что важнее всего не сорвать?"),
        (
            "assistant",
            f"Главное: {facts['Риск']}; резерв {facts['Резерв']}, "
            f"приёмка {facts['Приёмка']}.",
        ),
        ("user", "Спасибо, достаточно."),
    )

    messages = [
        {
            "id": index,
            "role": role,
            "content": content,
            "tokens": count_tokens(content),
        }
        for index, (role, content) in enumerate(pairs, 1)
    ]
    summaries = [
        {
            "id": 1,
            "from_id": 1,
            "to_id": 10,
            "content": _summary(
                facts,
                ("Проект", "Бюджет", "Срок", "Локация", "Ответственный", "Ограничение", "Метрика"),
            ),
            "tokens": 0,
        },
        {
            "id": 2,
            "from_id": 11,
            "to_id": 20,
            "content": _summary(
                facts,
                ("Этапы", "Подрядчик", "Договор", "Риск", "Резерв", "Отчётность", "Приёмка", "Гарантия"),
            ),
            "tokens": 0,
        },
        {
            "id": 3,
            "from_id": 21,
            "to_id": len(messages),
            "content": _summary(
                facts,
                ("Проект", "Бюджет", "Срок", "Ответственный", "Риск", "Резерв", "Приёмка"),
            ),
            "tokens": 0,
        },
    ]
    for summary in summaries:
        summary["tokens"] = count_tokens(summary["content"])

    start_id = len(messages) + 1
    branches = [
        _make_branch(
            rng,
            facts,
            spec,
            start_id=start_id,
            budget=budget,
            deadline=deadline,
            reserve=reserve,
            lead=lead,
        )
        for spec in BRANCH_SPECS
    ]

    trunk_hash = hashlib.sha256(
        "\n".join(item["content"] for item in messages).encode("utf-8")
    ).hexdigest()[:12]
    checkpoints = [
        {"id": "start", "message_id": 1, "label": "старт"},
        {"id": "cp-10", "message_id": 10, "label": "checkpoint 10"},
        {"id": "cp-20", "message_id": 20, "label": "checkpoint 20"},
        {"id": "branch-point", "message_id": len(messages), "label": "точка ветвления"},
    ]

    return {
        "title": topic["name"],
        "code": code,
        "topic": topic["kind"],
        "trunk_count": len(messages),
        "branch_point": len(messages),
        "trunk_hash": trunk_hash,
        "checkpoints": checkpoints,
        "messages": messages,
        "summaries": summaries,
        "branches": branches,
        "facts_seed": facts,
    }
