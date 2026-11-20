"""API урока 15: обновление памяти, конфликты и очистка задачи."""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .llm import DEFAULT_MODEL, LLMError, chat_with_usage as model_chat
from .memory import FACT_POLICIES, MemoryStore

TITLE = "Устаревание и конфликты памяти"
app = FastAPI(
    title="Memory Aging Lab",
    version="0.1.0",
    description="Урок 15: обновление фактов, конфликты и очистка рабочей памяти.",
)

_store: MemoryStore | None = None


def get_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore(
            Path(os.getenv("MEMORY_DB_PATH", "/srv/data/lesson15.db"))
        )
    return _store


SYSTEM_PROMPT = """Ты ассистент с обновляемой памятью.
В контексте — только АКТУАЛЬНЫЕ значения долговременной памяти.
Никогда не называй старые значения из истории как действующие и не упоминай
их даже в формулировке «ранее было»: в ответе должно быть только актуальное
значение и, при необходимости, факт его обновления без старого текста.
Если актуальное значение изменилось, используй только последнее.
Отвечай по-русски кратко; сначала факт, потом пояснение.
Не выдумывай значения, которых нет в памяти.
"""


def build_prompt(facts: list, question: str) -> tuple[str, list[dict[str, str]]]:
    lines = [SYSTEM_PROMPT, "", "АКТУАЛЬНАЯ ДОЛГОВРЕМЕННАЯ ПАМЯТЬ:"]
    for item in facts:
        lines.append(
            f"- {item.key} «{item.title}»: {item.value} "
            f"(записано {item.updated_at})"
        )
    messages = [
        {"role": "system", "content": "\n".join(lines)},
        {"role": "user", "content": question},
    ]
    return "\n".join(lines), messages


def deterministic_answer(question: str, facts: list) -> str:
    by_key = {item.key: item.value for item in facts}
    q = question.lower()
    if "срок" in q:
        return f"Актуальный срок: {by_key.get('deadline', 'не задан')}."
    if "sms" in q or "смс" in q:
        return f"Актуальное требование SMS: {by_key.get('sms_requirement', 'не задано')}."
    if "подход" in q:
        return f"Актуальный подход: {by_key.get('approach', 'не задан')}."
    if "версия" in q or "версии" in q:
        return f"Актуальная версия: {by_key.get('version', 'не задана')}."
    if "статус" in q:
        return f"Актуальный статус: {by_key.get('status', 'не задан')}."
    return "Актуальная память: " + "; ".join(
        f"{item.title} — {item.value}" for item in facts
    )


def generate_answer(question: str, facts: list) -> tuple[str, str, str]:
    prompt, messages = build_prompt(facts, question)
    try:
        answer, model, _ = model_chat(
            messages,
            model=DEFAULT_MODEL,
            max_tokens=900,
            temperature=0.2,
        )
        if not answer or "Модель сейчас недоступна" in answer:
            return deterministic_answer(question, facts), "fallback", prompt
        return answer, model, prompt
    except LLMError:
        return deterministic_answer(question, facts), "fallback", prompt


def _session(header: str | None) -> str:
    return (header or "").strip() or "demo"


def _extract_updates(text: str) -> list[tuple[str, str, str]]:
    """Вернуть (key, value, reason) из явной команды или естественной фразы."""
    raw = text.strip()
    first_line = raw.splitlines()[0] if raw else ""
    command = re.match(r"^!fact\s+([a-z_]+)\s*=\s*(.+)$", first_line, re.IGNORECASE)
    if command:
        return [(command.group(1).lower(), command.group(2).strip(), "явная команда")]
    lower = raw.lower()
    updates: list[tuple[str, str, str]] = []
    if "срок" in lower:
        match = re.search(
            r"срок[^.!?\n]*?(?:на|до|—|–|-)\s*([^.!?\n]+)",
            raw,
            re.IGNORECASE,
        )
        if match:
            updates.append(("deadline", match.group(1).strip(" .:—–-"), "срок изменён в диалоге"))
    if "sms" in lower or "смс" in lower:
        if any(word in lower for word in ("отмен", "не нуж", "не обяза", "убира")):
            updates.append(("sms_requirement", "отменено", "требование отменено"))
    if "подход" in lower:
        match = re.search(
            r"(?:выбрали|выбираем|теперь|используем)\s+(?:другой\s+)?подход[^.!?\n]*?(?:[:—–-]\s*)?([^.!?\n]+)",
            raw,
            re.IGNORECASE,
        )
        if match:
            updates.append(("approach", match.group(1).strip(" .:—–-"), "подход изменён"))
    if "версия" in lower or "версии" in lower:
        match = re.search(r"верси\w*\s+(?:теперь\s+)?(v?\d+(?:\.\d+)*)", raw, re.IGNORECASE)
        if match:
            updates.append(("version", match.group(1), "версия изменена"))
    if "статус" in lower:
        match = re.search(
            r"статус[^.!?\n]*?(?:[:—–-]|теперь|стал[а]?)\s*([^.!?\n]+)",
            raw,
            re.IGNORECASE,
        )
        if match:
            updates.append(("status", match.group(1).strip(" .:—–-"), "статус изменён"))
    if lower.startswith("!decision "):
        decision = raw[len("!decision "):].split("\n", 1)[0].strip()
        updates.append(("decisions", decision, "принято решение"))
    return updates


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8_000)
    session_id: str = Field(default="demo", max_length=80)


class StartRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2_000)
    session_id: str = Field(default="demo", max_length=80)


class CompleteRequest(BaseModel):
    session_id: str = Field(default="demo", max_length=80)


@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "lesson": 15,
        "title": TITLE,
        "model": DEFAULT_MODEL,
        "facts": len(get_store().facts()),
    }


@app.get("/api/state")
async def state(session_id: str = "demo") -> dict:
    return get_store().state(session_id)


@app.get("/api/policies")
async def policies() -> dict:
    return {
        "items": [item.to_dict() for item in FACT_POLICIES],
        "working_lifetime": "до завершения задачи",
        "facts_lifetime": "долговременно, с временем записи",
    }


@app.post("/api/task/start")
async def start_task(payload: StartRequest) -> dict:
    store = get_store()
    working = store.set_working(payload.session_id, payload.goal, "в работе", "Следующий шаг")
    return {"working": working, "state": store.state(payload.session_id)}


@app.post("/api/task/complete")
async def complete_task(payload: CompleteRequest) -> dict:
    store = get_store()
    cleared = store.clear_working(payload.session_id)
    return {
        "cleared": cleared,
        "long_term_preserved": len(store.facts()),
        "state": store.state(payload.session_id),
    }


@app.get("/api/prompt")
async def prompt(session_id: str = "demo") -> dict:
    store = get_store()
    current = store.prompt_block()
    return {
        "prompt": f"{SYSTEM_PROMPT}\n\n{current}",
        "old_values": store.old_values(),
        "old_values_in_prompt": store.prompt_old_values(),
    }


def _ask(
    store: MemoryStore,
    session_id: str,
    question: str,
    user_text: str | None = None,
) -> dict[str, Any]:
    facts = store.facts()
    answer, model, prompt_text = generate_answer(question, facts)
    stale = store.stale_in_answer(answer)
    old_in_prompt = store.prompt_old_values()
    store.record_audit(session_id, question, answer, stale, old_in_prompt)
    store.append_short(session_id, "user", user_text or question)
    store.append_short(session_id, "assistant", answer)
    return {
        "answer": answer,
        "model": model,
        "prompt": prompt_text,
        "stale_values": stale,
        "stale_count": len(stale),
        "old_values_in_prompt": old_in_prompt,
        "facts": [item.to_dict() for item in facts],
    }


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict:
    store = get_store()
    updates = _extract_updates(payload.message)
    changes = []
    for key, value, reason in updates:
        try:
            changes.append(store.update(key, value, reason=reason))
        except (KeyError, ValueError) as exc:
            changes.append({"key": key, "error": str(exc)})
    if not store.working(payload.session_id):
        store.set_working(payload.session_id, payload.message[:500], "в работе")
    result = await run_in_threadpool(_ask, store, payload.session_id, payload.message)
    result["changes"] = changes
    result["state"] = store.state(payload.session_id)
    return result


SCENARIO: tuple[dict[str, str], ...] = (
    {
        "key": "deadline",
        "value": "30 ноября",
        "question": "Какой срок проекта?",
        "reason": "срок сдвинулся",
    },
    {
        "key": "sms_requirement",
        "value": "отменено",
        "question": "Обязательны ли SMS-уведомления?",
        "reason": "требование отменили",
    },
    {
        "key": "approach",
        "value": "Автоматическая проверка",
        "question": "Какой подход выбран?",
        "reason": "выбрали другой подход",
    },
    {
        "key": "version",
        "value": "v2",
        "question": "Какая версия проекта?",
        "reason": "версия обновлена",
    },
)


@app.post("/api/scenario")
async def scenario(session_id: str = "demo") -> dict:
    store = get_store()
    if not store.working(session_id):
        store.set_working(session_id, "Демонстрация изменения фактов", "в работе")
    steps = []
    for item in SCENARIO:
        change = store.update(item["key"], item["value"], reason=item["reason"])
        asked = _ask(store, session_id, item["question"])
        steps.append(
            {
                **item,
                "change": change,
                "answer": asked["answer"],
                "stale_values": asked["stale_values"],
                "stale_count": asked["stale_count"],
                "old_values_in_prompt": asked["old_values_in_prompt"],
                "prompt": asked["prompt"],
            }
        )
    return {
        "steps": steps,
        "stale_answers": sum(1 for step in steps if step["stale_count"]),
        "stale_mentions": sum(step["stale_count"] for step in steps),
        "old_values_in_prompt": sum(
            1 for step in steps if step["old_values_in_prompt"]
        ),
        "state": store.state(session_id),
    }


class AppendScenarioRequest(BaseModel):
    mode: Literal["unique", "duplicate"] = "unique"
    session_id: str | None = Field(default=None, max_length=80)


def _append_count(value: str) -> int:
    return sum(1 for line in value.splitlines() if line.strip())


@app.post("/api/append-scenario")
async def append_scenario(
    payload: AppendScenarioRequest | None = None,
    session_id: str = "demo",
) -> dict:
    """Добавить уникальное или повторяющееся значение в append-факт."""
    store = get_store()
    mode = (payload.mode if payload else "unique")
    session = (payload.session_id if payload and payload.session_id else session_id)
    decisions = store.fact("decisions")
    current = decisions.value if decisions else ""
    existing = []
    for line in current.splitlines():
        item = line.strip()
        if item.startswith("- "):
            item = item[2:].strip()
        if item:
            existing.append(item)
    if mode == "duplicate":
        value = existing[0] if existing else "Выбрали SQLite для хранения"
        reason = "проверка дубликата"
    else:
        value = f"Уникальное решение {uuid.uuid4().hex[:8]}"
        reason = "уникальное добавление"
    change = store.update("decisions", value, reason=reason)
    after = store.fact("decisions")
    history = store.fact("change_history")
    return {
        "mode": mode,
        "value": value,
        "change": change,
        "added": 1 if change.get("changed") else 0,
        "skipped": 1 if change.get("skipped") else 0,
        "message": change.get("message") or (
            f"Добавлено: {value}" if change.get("changed") else "Значение уже есть"
        ),
        "decisions_count": _append_count(after.value if after else ""),
        "history_count": _append_count(history.value if history else ""),
        "decisions": after.value if after else "",
        "history": history.value if history else "",
        "state": store.state(session),
    }


def _dialog_message(kind: str, key: str, value: str, question: str) -> str:
    if kind == "replace":
        return f"!fact {key} = {value}\n{question}"
    if kind in {"append", "duplicate"}:
        return f"!decision {value}\n{question}"
    return question


def _update_message(kind: str, change: dict[str, Any], value: str) -> str:
    if kind == "probe":
        return "Изменений нет: только проверка актуального значения."
    if change.get("skipped"):
        return (
            f"Добавление пропущено: «{value}» уже есть в факте "
            f"«{change.get('title') or change.get('key')}»."
        )
    if not change.get("changed"):
        return (
            f"Без изменений: «{change.get('title') or change.get('key')}» "
            f"уже равно «{change.get('new_value')}»; перезапись не выполнена."
        )
    if kind == "replace":
        return (
            f"Реально перезаписано: «{change.get('title') or change.get('key')}» "
            f"{change.get('old_value')} → {change.get('new_value')}."
        )
    return (
        f"Реально добавлено в «{change.get('title') or change.get('key')}»: "
        f"«{value}»."
    )




DIALOG_SCENARIO = (
    ("replace", "deadline", "30 ноября", "Какой срок проекта?"),
    ("probe", "deadline", "", "Что было раньше в сроке и что стало сейчас? Назови оба значения."),
    ("append", "decisions", "Выбрали автоматическую проверку", "Какие решения приняты?"),
    ("replace", "approach", "Автоматическая проверка", "Какой подход выбран?"),
    ("duplicate", "decisions", "", "Сколько решений сейчас в памяти?"),
    ("replace", "sms_requirement", "отменено", "Нужны ли SMS-уведомления?"),
    ("replace", "status", "на проверке", "Какой статус проекта?"),
    ("replace", "version", "v2", "Какая версия проекта?"),
    ("append", "decisions", "Добавили проверку конфликтов", "Какие решения приняты?"),
)


def _decision_items(value: str) -> list[str]:
    items = []
    for line in (value or "").splitlines():
        item = line.strip()
        if item.startswith("- "):
            item = item[2:].strip()
        if item:
            items.append(item)
    return items


@app.post("/api/dialog-scenario")
async def dialog_scenario(session_id: str = "demo") -> dict:
    """Смешанный диалог: replace, append, duplicate и проверка утечки старых значений."""
    store = get_store()
    if not store.working(session_id):
        store.set_working(session_id, "Тестовый диалог конфликтов и добавлений", "в работе")
    steps = []
    for index, (kind, key, value, question) in enumerate(DIALOG_SCENARIO, start=1):
        chosen = value
        if kind == "duplicate":
            items = _decision_items(
                store.fact("decisions").value if store.fact("decisions") else ""
            )
            chosen = items[0] if items else "Выбрали SQLite для хранения"
        user_text = _dialog_message(kind, key, chosen, question)
        if kind == "probe":
            current = store.fact(key)
            change = {
                "key": key,
                "title": current.title if current else key,
                "old_value": current.value if current else "",
                "new_value": current.value if current else "",
                "policy": current.policy if current else "replace",
                "changed": False,
                "skipped": False,
                "updated_at": current.updated_at if current else "",
            }
        else:
            updates = _extract_updates(user_text)
            if not updates:
                raise ValueError(f"Не удалось разобрать действие шага {index}: {user_text}")
            applied = []
            for update_key, update_value, reason in updates:
                applied.append(
                    store.update(
                        update_key,
                        update_value,
                        reason=f"тестовый диалог, шаг {index} ({kind}): {reason}",
                    )
                )
            change = applied[0]
        update_message = _update_message(kind, change, chosen)
        asked = _ask(store, session_id, question, user_text=user_text)
        steps.append(
            {
                "step": index,
                "kind": kind,
                "key": key,
                "value": chosen,
                "change": change,
                "mutation": update_message,
                "update_message": update_message,
                "user_message": user_text,
                "question": question,
                "answer": asked["answer"],
                "stale_values": asked["stale_values"],
                "stale_count": asked["stale_count"],
                "old_values_in_prompt": asked["old_values_in_prompt"],
            }
        )

    replacements = sum(
        1 for step in steps if step["kind"] == "replace" and step["change"].get("changed")
    )
    appended = sum(
        1 for step in steps if step["kind"] == "append" and step["change"].get("changed")
    )
    skipped = sum(
        1 for step in steps if step["kind"] == "duplicate" and step["change"].get("skipped")
    )
    probe = next((step for step in steps if step["kind"] == "probe"), None)
    return {
        "steps": steps,
        "replacements": replacements,
        "facts_overwritten": replacements,
        "appended": appended,
        "facts_added": appended,
        "skipped": skipped,
        "stale_answers": sum(1 for step in steps if step["stale_count"]),
        "stale_mentions": sum(step["stale_count"] for step in steps),
        "old_values_in_prompt": sum(1 for step in steps if step["old_values_in_prompt"]),
        "probe_attempted": probe is not None,
        "probe_stale": bool(probe and probe["stale_count"]),
        "probe_stale_values": probe["stale_values"] if probe else [],
        "state": store.state(session_id),
    }




@app.post("/api/reset")
async def reset() -> dict:
    store = get_store()
    path = store.path
    path.unlink(missing_ok=True)
    for suffix in ("-shm", "-wal"):
        Path(str(path) + suffix).unlink(missing_ok=True)
    global _store
    _store = None
    return {"reset": True}


@app.get("/api/audits")
async def audits(session_id: str = "demo") -> dict:
    store = get_store()
    return {
        "items": store.audits(session_id),
        "stats": store.stale_stats(session_id),
    }
