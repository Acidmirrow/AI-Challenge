"""Проверка профилей урока 12.

Вопросы генерируются на лету и нигде не кешируются. Один вопрос можно задать
всем профилям, либо прогнать серию из 10 случайных вопросов с разными профилями.
Итоговый анализ выполняет только Pro-модель OpenCode Go.
"""

from __future__ import annotations

import random
import re
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from .context import build_context
from .llm import PRO_MODEL, chat_with_usage as model_chat

ChatFn = Callable[..., tuple[str, str, dict[str, Any]]]

TOPICS = [
    "HTTP API",
    "SQL-индексы",
    "контейнеры Docker",
    "очереди сообщений",
    "кеширование",
    "аутентификация",
    "тестирование",
    "CI/CD",
    "микросервисы",
    "работа с логами",
    "REST и JSON",
    "фоновые задачи",
    "хранение файлов",
    "мониторинг",
    "деплой в облако",
    "работа с Git",
]

ROLE_TOPICS: tuple[tuple[tuple[str, ...], list[str]], ...] = (
    (
        ("продакт", "product", "менеджер продукта"),
        [
            "приоритизация бэклога",
            "метрики продукта",
            "исследование пользователей",
            "MVP",
            "A/B-тест",
            "roadmap",
            "требования к фиче",
            "unit-экономика",
            "запуск фичи",
        ],
    ),
    (
        ("дизайн", "design", "ux", "ui"),
        [
            "UX-исследование",
            "дизайн-система",
            "прототипирование",
            "юзабилити-тестирование",
            "доступность интерфейса",
            "пользовательские сценарии",
            "визуальная иерархия",
            "макеты",
            "дизайн-ревью",
        ],
    ),
    (
        ("аналит", "analyst", "data"),
        [
            "SQL-запросы",
            "метрики и дашборды",
            "качество данных",
            "A/B-тест",
            "когортный анализ",
            "воронка",
            "регрессия",
            "ETL",
        ],
    ),
    (
        ("разработ", "developer", "инженер", "программист", "devops"),
        [
            "HTTP API",
            "SQL-индексы",
            "контейнеры Docker",
            "очереди сообщений",
            "кеширование",
            "аутентификация",
            "тестирование",
            "CI/CD",
            "микросервисы",
            "логирование",
            "фоновые задачи",
            "мониторинг",
            "деплой в облако",
        ],
    ),
    (
        ("студент", "student", "учащ"),
        [
            "учебный проект",
            "выбор технологии",
            "план обучения",
            "портфолио",
            "разбор ошибок",
            "подготовка к собеседованию",
            "практика по Git",
        ],
    ),
)


def topics_for_role(role: str) -> list[str]:
    """Подобрать темы, соответствующие специализации профиля."""
    normalized = _clean(role, 200).lower()
    for keywords, topics in ROLE_TOPICS:
        if any(keyword in normalized for keyword in keywords):
            return topics
    return TOPICS


TASKS = [
    "Объясни тему «{topic}» так, чтобы было понятно человеку с моим профилем.",
    "Составь план изучения темы «{topic}» на одну неделю.",
    "Сравни два подхода к теме «{topic}» и порекомендуй один.",
    "Напиши короткую инструкцию по теме «{topic}».",
    "Какие ошибки чаще всего допускают при работе с темой «{topic}»?",
    "Предложи практическое задание по теме «{topic}».",
    "Как объяснить тему «{topic}» коллеге за пять минут?",
    "Дай чек-лист по теме «{topic}».",
    "С чего начать проект, связанный с темой «{topic}»?",
    "Как проверить, что тема «{topic}» внедрена правильно?",
]


def _clean(value: str, limit: int = 2_000) -> str:
    return " ".join(str(value or "").split())[:limit]


def generate_question(
    session_id: str = "",
    seed: str | None = None,
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """Сгенерировать новый вопрос; вопрос и его id не кешируются."""
    token = secrets.token_hex(6)
    rng = random.Random(seed or token)
    template = rng.choice(TASKS)
    topic = rng.choice(topics or TOPICS)
    question = template.format(topic=topic)
    return {
        "question": question,
        "question_id": f"q-{token}",
        "session_id": _clean(session_id, 80) or "default",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
    }


def _profile_payload(store: Any, profile: dict[str, Any]) -> dict[str, Any]:
    state = store.get(profile["owner_id"])
    return {
        "owner_id": profile["owner_id"],
        "name": state["profile"].get("name") or profile["owner_id"],
        "role": state["profile"].get("role") or profile.get("role") or "",
        "city": state["profile"].get("city") or "",
        "preferences": state["preference_map"],
    }


MAX_ANSWER_TOKENS = 1_600
MAX_ANALYSIS_TOKENS = 2_500


def _is_incomplete(answer: str, usage: dict[str, Any]) -> bool:
    """Признаки обрыва: лимит токенов, открытый code fence или незавершённая фраза."""
    if (usage or {}).get("finish_reason") in {"length", "max_tokens"}:
        return True
    text = (answer or "").rstrip()
    if not text:
        return True
    if text.count("```") % 2:
        return True
    if re.search(r"<[a-zA-Z][^>]*$", text):
        return True
    tail = text[-80:]
    return bool(
        re.search(
            r"(?:^|\s)(?:и|или|в|на|с|по|для|что|как|к|из|от|до|—|-|:)\s*$",
            tail,
            flags=re.IGNORECASE,
        )
    )


def _merge_usage(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first = first or {}
    second = second or {}
    return {
        **second,
        "prompt_tokens": int(first.get("prompt_tokens") or 0)
        + int(second.get("prompt_tokens") or 0),
        "completion_tokens": int(first.get("completion_tokens") or 0)
        + int(second.get("completion_tokens") or 0),
        "total_tokens": int(first.get("total_tokens") or 0)
        + int(second.get("total_tokens") or 0),
        "estimated": bool(first.get("estimated") or second.get("estimated")),
        "finish_reason": second.get("finish_reason") or first.get("finish_reason"),
    }


def _complete_answer(
    messages: list[dict[str, Any]], chat_fn: ChatFn
) -> tuple[str, str, dict[str, Any]]:
    """Запросить ответ и при обрыве дописать его продолжением."""
    answer, model, usage = chat_fn(messages, max_tokens=MAX_ANSWER_TOKENS)
    for _ in range(2):
        if model == "fallback" or not _is_incomplete(answer, usage):
            break
        continuation_messages = messages + [
            {"role": "assistant", "content": answer},
            {
                "role": "user",
                "content": (
                    "Ответ оборвался. Продолжи ровно с места обрыва, не повторяй начало. "
                    "Заверши мысль, закрой все блоки кода и поставь финальную точку."
                ),
            },
        ]
        extra, extra_model, extra_usage = chat_fn(
            continuation_messages, max_tokens=MAX_ANSWER_TOKENS
        )
        if extra_model == "fallback" or not extra.strip():
            break
        answer = answer.rstrip() + "\n" + extra.lstrip()
        model = extra_model
        usage = _merge_usage(usage, extra_usage)
    return answer, model, usage


def _needs_code(profile_state: dict[str, Any]) -> bool:
    code = (profile_state.get("preference_map", {}).get("code_examples") or "").strip().lower()
    return code.startswith("с пример")


def _has_code(answer: str) -> bool:
    return bool(re.search(r"```|<code>|<[a-zA-Z][^>]*>", answer or ""))


def _ensure_code_example(
    messages: list[dict[str, Any]],
    answer: str,
    profile_state: dict[str, Any],
    chat_fn: ChatFn,
    model: str,
    usage: dict[str, Any],
) -> tuple[str, str, dict[str, Any], bool]:
    """Если профиль требует код, а его нет — попросить полный ответ с примером."""
    if not _needs_code(profile_state):
        return answer, model, usage, True
    if _has_code(answer):
        return answer, model, usage, True
    repair_messages = messages + [
        {"role": "assistant", "content": answer},
        {
            "role": "user",
            "content": (
                "Перепиши полный ответ заново и обязательно добавь один уместный "
                "фрагмент кода в блоке ```. Не сокращай содержательную часть."
            ),
        },
    ]
    revised, revised_model, revised_usage = chat_fn(
        repair_messages, max_tokens=MAX_ANSWER_TOKENS
    )
    if revised_model != "fallback" and _has_code(revised):
        return (
            revised,
            revised_model,
            _merge_usage(usage, revised_usage),
            True,
        )
    return answer, model, usage, False


EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
INFORMAL_RE = re.compile(
    r"\b(?:ты|тебе|тебя|твой|твоя|твои|твоё|начни|сделай|покажи|держи|смотри|давай)\b",
    flags=re.IGNORECASE,
)
FORMAL_RE = re.compile(
    r"\b(?:вы|вам|вас|ваш|ваша|ваши|ваше|сделайте|покажите)\b",
    flags=re.IGNORECASE,
)


def _check_code(value: str, answer: str) -> bool | None:
    normalized = (value or "").lower()
    if "пример" not in normalized:
        return None
    if "без" in normalized:
        return not _has_code(answer)
    if normalized.startswith("с пример") or "с пример" in normalized:
        return _has_code(answer)
    return None


def _check_emoji(value: str, answer: str) -> bool | None:
    normalized = (value or "").lower()
    if "emoji" not in normalized and "эмодзи" not in normalized:
        return None
    has = bool(EMOJI_RE.search(answer or ""))
    if "без" in normalized:
        return not has
    if normalized.startswith("с ") or " с " in f" {normalized} ":
        return has
    return None


def _check_style(value: str, answer: str) -> bool | None:
    normalized = (value or "").lower()
    informal = bool(INFORMAL_RE.search(answer or ""))
    formal = bool(FORMAL_RE.search(answer or ""))
    if "формаль" in normalized:
        return not informal
    if "неформаль" in normalized or "на ты" in normalized or "«ты»" in normalized:
        return informal or formal
    return None


def _check_format(value: str, answer: str) -> bool | None:
    normalized = (value or "").lower()
    text = answer or ""
    if "таблиц" in normalized:
        return text.count("|") >= 4
    if "спис" in normalized:
        return bool(re.search(r"(?m)^\s*(?:[-*]|\d+[.)])\s+\S", text))
    if "пошаг" in normalized:
        return bool(re.search(r"\bшаг\s*\d|\bstep\s*\d", text, flags=re.IGNORECASE))
    if "кратк" in normalized:
        return len(text) <= 2_200
    return None


def audit_answer(answer: str, preferences: dict[str, Any]) -> dict[str, Any]:
    """Эвристически проверить, соблюдены ли заявленные предпочтения."""
    checks: dict[str, dict[str, Any]] = {}
    for key, checker in (
        ("style", _check_style),
        ("format", _check_format),
        ("code_examples", _check_code),
        ("emoji", _check_emoji),
    ):
        value = (preferences or {}).get(key) or ""
        result = checker(value, answer)
        if result is None:
            continue
        checks[key] = {"value": value, "passed": bool(result)}
    passed = sum(1 for item in checks.values() if item["passed"])
    return {
        "checks": checks,
        "checked": len(checks),
        "passed": passed,
        "compliant": bool(checks) and passed == len(checks),
        "violations": [key for key, item in checks.items() if not item["passed"]],
    }


def summarize_audit(results: list[dict[str, Any]]) -> dict[str, Any]:
    audited = [item for item in results if (item.get("audit") or {}).get("checked")]
    checked = sum(int((item.get("audit") or {}).get("checked") or 0) for item in audited)
    passed = sum(int((item.get("audit") or {}).get("passed") or 0) for item in audited)
    compliant = sum(1 for item in audited if (item.get("audit") or {}).get("compliant"))
    first = next(
        (
            index
            for index, item in enumerate(results, start=1)
            if (item.get("audit") or {}).get("checked")
            and not (item.get("audit") or {}).get("compliant")
        ),
        None,
    )
    return {
        "answers": len(audited),
        "compliant_answers": compliant,
        "checked": checked,
        "passed": passed,
        "first_violation": first,
    }


def _stability(store: Any, before_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    after = store.list_profiles()
    before_count = len(before_profiles)
    after_count = len(after)
    before_prefs = sum(int(item.get("preferences") or 0) for item in before_profiles)
    after_prefs = sum(int(item.get("preferences") or 0) for item in after)
    return {
        "profiles_before": before_count,
        "profiles_after": after_count,
        "preferences_before": before_prefs,
        "preferences_after": after_prefs,
        "unchanged": before_count == after_count and before_prefs == after_prefs,
    }


def _answer_one(
    store: Any,
    profile: dict[str, Any],
    question: str,
    chat_fn: ChatFn,
) -> dict[str, Any]:
    state = store.get(profile["owner_id"])
    role = (state["profile"].get("role") or "").strip()
    prompt_question = question
    if role:
        prompt_question = (
            f"{question}\n\n"
            "Ответь компактно: не более 7–9 предложений или 5–7 пунктов, без длинных "
            "вступлений и повторов. Заверши мысль и закрой блоки кода.\n\n"
            f"Моя специализация: {role}. Ответь с учётом этой роли; "
            "если вопрос выходит за её границы, прямо скажи об этом и не выдумывай."
        )
    built = build_context(state, [{"role": "user", "content": prompt_question}])
    answer, model, usage = _complete_answer(built["messages"], chat_fn)
    # Один ретрай на случай временного сбоя провайдера в параллельной серии.
    if model == "fallback":
        time.sleep(0.8)
        answer, model, usage = _complete_answer(built["messages"], chat_fn)
    answer, model, usage, code_ok = _ensure_code_example(
        built["messages"], answer, state, chat_fn, model, usage
    )
    return {
        **_profile_payload(store, profile),
        "question": question,
        "answer": answer,
        "model": model,
        "usage": usage,
        "request_tokens": int(usage.get("prompt_tokens") or built["total_tokens"]),
        "response_tokens": int(usage.get("completion_tokens") or 0),
        "finish_reason": usage.get("finish_reason"),
        "code_ok": code_ok,
        "audit": audit_answer(answer, state["preference_map"]),
    }


def _parallel_answers(
    store: Any,
    profiles: list[dict[str, Any]],
    question: str,
    chat_fn: ChatFn,
) -> list[dict[str, Any]]:
    workers = max(1, min(6, len(profiles)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_answer_one, store, profile, question, chat_fn)
            for profile in profiles
        ]
        return [future.result() for future in futures]


def answer_all(store: Any, question: str, chat_fn: ChatFn = model_chat) -> dict[str, Any]:
    """Задать один вопрос всем внесённым профилям."""
    question = _clean(question)
    if not question:
        raise ValueError("Вопрос не может быть пустым")
    profiles = store.list_profiles()
    if not profiles:
        raise ValueError("Нет ни одного профиля")
    items = _parallel_answers(store, profiles, question, chat_fn)
    return {
        "question": question,
        "profiles_count": len(items),
        "results": items,
        "failed": sum(1 for item in items if item.get("model") == "fallback"),
        "code_missing": sum(1 for item in items if item.get("code_ok") is False),
        "audit": summarize_audit(items),
        "stability": _stability(store, profiles),
        "cached": False,
    }


def random_questions(
    profiles: list[dict[str, Any]], count: int = 10
) -> list[dict[str, Any]]:
    """Сгенерировать до 10 уникальных вопросов и назначить разные профили."""
    if not profiles:
        raise ValueError("Нет ни одного профиля")
    count = max(1, min(int(count), 10))
    rng = random.Random(secrets.token_hex(8))
    shuffled = profiles[:]
    rng.shuffle(shuffled)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index in range(count):
        profile = shuffled[index % len(shuffled)]
        role_topics = topics_for_role(profile.get("role") or "")
        question = ""
        question_id = ""
        for _ in range(12):
            candidate = generate_question(f"batch-{index}", topics=role_topics)
            if candidate["question"] not in seen:
                question = candidate["question"]
                question_id = candidate["question_id"]
                break
        if not question:
            candidate = generate_question(f"batch-{index}", topics=role_topics)
            question = candidate["question"] + f" (вариант {index + 1})"
            question_id = candidate["question_id"]
        seen.add(question)
        items.append(
            {"question": question, "question_id": question_id, "profile": profile}
        )
    return items


def answer_batch(
    store: Any,
    count: int = 10,
    chat_fn: ChatFn = model_chat,
) -> dict[str, Any]:
    """Ответы на серию случайных вопросов; каждый вопрос задаётся своему профилю."""
    profiles = store.list_profiles()
    if not profiles:
        raise ValueError("Нет ни одного профиля")
    questions = random_questions(profiles, count)
    workers = max(1, min(4, len(questions)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _answer_one,
                store,
                item["profile"],
                item["question"],
                chat_fn,
            )
            for item in questions
        ]
        results = [future.result() for future in futures]
        for item, result in zip(questions, results):
            result["question_id"] = item["question_id"]
    return {
        "count": len(results),
        "profiles_count": len({item["owner_id"] for item in results}),
        "failed": sum(1 for item in results if item.get("model") == "fallback"),
        "code_missing": sum(1 for item in results if item.get("code_ok") is False),
        "results": results,
        "audit": summarize_audit(results),
        "stability": _stability(store, profiles),
        "cached": False,
    }


def _analysis_prompt(items: list[dict[str, Any]]) -> str:
    lines = [
        "Ниже ответы разных профилей на вопросы проверки персонализации.",
        "Оцени, насколько каждый ответ соответствует профилю пользователя:",
        "стилю (формальный/неформальный), формату, примерам кода и emoji,",
        "а также соответствию ответа специализации (роли) профиля.",
        "Отдельно отметь случаи, где профиль вышел за пределы своей роли или должен был сказать, что вопрос вне компетенции.",
        "Найди удачные и проблемные места, а также дай 3 рекомендации по улучшению профилей.",
        "Не придумывай данные, которых нет в ответах. Пиши по-русски, структурированно.",
        "Дай компактный анализ: выводы по профилям, 1–2 сильные стороны и 3 рекомендации, без длинных вступлений.",
        "",
    ]
    for index, item in enumerate(items, start=1):
        prefs = item.get("preferences") or {}
        lines.extend(
            [
                f"### {index}. {item.get('name') or item.get('owner_id')}",
                f"Вопрос: {_clean(item.get('question', ''), 500)}",
                f"Стиль: {prefs.get('style', '—')}; формат: {prefs.get('format', '—')}; "
                f"код: {prefs.get('code_examples', '—')}; emoji: {prefs.get('emoji', '—')}",
                f"Ответ: {_clean(item.get('answer', ''), 700)}",
                "",
            ]
        )
    return "\n".join(lines)


def analyze_results(
    items: list[dict[str, Any]],
    chat_fn: ChatFn = model_chat,
) -> dict[str, Any]:
    """Проанализировать результаты строго Pro-моделью OpenCode Go."""
    if not items:
        raise ValueError("Нет результатов для анализа")
    messages = [
        {
            "role": "system",
            "content": (
                "Ты методист по персонализации AI-ассистентов. "
                "Анализируй только предоставленные ответы и не выдумывай факты."
            ),
        },
        {"role": "user", "content": _analysis_prompt(items)},
    ]
    analysis = ""
    model = "fallback"
    usage: dict[str, Any] = {}
    # Pro-модель иногда отвечает временной ошибкой в длинной серии — даём два ретрая.
    for attempt in range(3):
        analysis, model, usage = chat_fn(
            messages, model=PRO_MODEL, max_tokens=MAX_ANALYSIS_TOKENS, temperature=0.2
        )
        if model != "fallback":
            break
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return {
        "analysis": analysis,
        "model": model,
        "requested_model": PRO_MODEL,
        "usage": usage,
        "request_tokens": int(usage.get("prompt_tokens") or 0),
        "response_tokens": int(usage.get("completion_tokens") or 0),
        "cached": False,
    }
