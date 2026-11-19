"""Страница урока 13: визуализация состояния задачи и чат."""

from __future__ import annotations

import html
import re
import time
import uuid
from typing import Any

import httpx
import streamlit as st
from streamlit.components.v1 import html as components_html

from common import LESSON_13_API

NO_CACHE = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
GOTASK_RE = re.compile(r"^/gotask(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
TEST_GOAL = (
    "Найди 5 самых значимых событий 1969 года в мировой истории. "
    "Для каждого укажи дату, событие и 1–2 предложения о том, почему оно значимо. "
    "Используй интернет для проверки фактов; результат — краткий список без ссылок."
)
TEST_PLAN = (
    "1. Найти в интернете 5 значимых событий 1969 года и проверить даты.\n"
    "2. Для каждого события кратко объяснить значимость по независимым источникам.\n"
    "3. Сформировать итоговый список из 5 пунктов без ссылок."
)
LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)", re.IGNORECASE)
BARE_URL_RE = re.compile(r"https?://[^\s)<>\]]+|www\.[^\s)<>\]]+", re.IGNORECASE)


def _clip(text: str, limit: int = 12_000) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + "…"


def _display_text(text: str) -> str:
    """Скрыть URL и markdown-ссылки в ответах ассистента."""
    text = LINK_RE.sub(r"\1", text)
    text = BARE_URL_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


STAGES = [
    ("planning", "Планирование", "План и его утверждение"),
    ("execution", "Реализация", "Выполнение работ"),
    ("validation", "Валидация", "Проверка результата"),
    ("done", "Готово", "Задача завершена"),
]
STAGE_INDEX = {stage: index for index, (stage, _label, _hint) in enumerate(STAGES)}
ACTION_LABELS = {
    "submit_plan": "Отправить план",
    "approve_plan": "Утвердить план",
    "start_execution": "Начать реализацию",
    "complete_execution": "Завершить реализацию",
    "start_validation": "Начать валидацию",
    "pass_validation": "Валидация пройдена",
    "fail_validation": "Валидация не пройдена",
    "finish": "Завершить задачу",
    "rework": "Вернуть в реализацию",
    "pause": "Пауза",
    "resume": "Продолжить",
}
ACTION_HINTS = {
    "submit_plan": "Опишите план; утверждение будет отдельным шагом.",
    "approve_plan": "План должен быть утверждён до реализации.",
    "start_execution": "Доступно только после утверждения плана.",
    "complete_execution": "Отметьте, что реализация действительно завершена.",
    "start_validation": "Валидация начинается после завершения реализации.",
    "pass_validation": "Зафиксируйте успешную проверку результата.",
    "fail_validation": "Зафиксируйте проблему; потребуется доработка.",
    "finish": "Завершение доступно только после успешной валидации.",
    "rework": "Флаги реализации и валидации будут сброшены.",
    "pause": "Состояние и контекст сохранятся.",
    "resume": "Продолжите с того же шага.",
}


ACTION_SUCCESS = {
    "approve_plan": "План утверждён, реализация начата. Шаги выполняются автоматически; после них начнётся валидация.",
    "start_execution": "Реализация начата. Шаги выполняются автоматически; после них начнётся валидация.",
    "complete_execution": "Реализация завершена. Валидация начнётся автоматически через 10 секунд.",
    "start_validation": "Валидация начата. Итог — `/pass` или `/fail`.",
    "pass_validation": "Валидация пройдена. Задача автоматически переведена в статус «Готово».",
    "fail_validation": "Валидация не пройдена. Задачу можно доработать командой `/rework`.",
    "finish": "Задача завершена.",
    "rework": "Задача возвращена в реализацию.",
    "pause": "Задача поставлена на паузу. Продолжение — `/resume`.",
    "resume": "Задача продолжена.",
}


ACTION_COMMANDS = {
    "approve_plan": "/approve",
    "start_execution": "/start",
    "start_validation": "/validate",
    "pass_validation": "/pass",
    "fail_validation": "/fail",
    "rework": "/rework",
    "pause": "/pause",
    "resume": "/resume",
}
COMMAND_ACTIONS = {command: action for action, command in ACTION_COMMANDS.items()}


def _command_action(text: str) -> str | None:
    normalized = text.strip().lower()
    if normalized in COMMAND_ACTIONS:
        return COMMAND_ACTIONS[normalized]
    return None


def _session_id() -> str:
    session = st.session_state.get("l13_session_id")
    if not session:
        query = st.query_params.get("l13_session")
        if isinstance(query, list):
            query = query[0] if query else None
        session = str(query or "").strip() or uuid.uuid4().hex
        st.session_state["l13_session_id"] = session
        st.query_params["l13_session"] = session
    return session


def _headers() -> dict[str, str]:
    return {**NO_CACHE, "X-Session-Id": _session_id()}


def _request(method: str, path: str, payload: dict | None = None) -> Any:
    with httpx.Client(timeout=180.0, headers=_headers()) as client:
        response = client.request(method, f"{LESSON_13_API}{path}", json=payload)
    if response.status_code >= 400:
        hint = None
        try:
            data = response.json()
            message = data.get("message") or data.get("detail") or response.text
            code = data.get("code")
            hint = data.get("hint")
        except Exception:  # noqa: BLE001
            message, code = response.text, None
        text = f"{code + ': ' if code else ''}{message}"
        if hint:
            text += f"\n\nКак исправить: {hint}"
        raise RuntimeError(text)
    return response.json()


def _get_task() -> dict | None:
    try:
        return _request("GET", "/api/task")
    except RuntimeError as exc:
        if "task_not_found" in str(exc):
            return None
        raise


def _load_history() -> None:
    if "l13_messages" in st.session_state:
        return
    try:
        data = _request("GET", "/api/chat/history")
    except RuntimeError:
        st.session_state["l13_messages"] = []
        return
    loaded: list[dict[str, Any]] = []
    for item in data.get("messages") or []:
        message: dict[str, Any] = {
            "role": item.get("role") or "assistant",
            "content": item.get("content") or "",
        }
        for key in ("questions", "sources", "search_note", "plan", "kind"):
            if item.get(key):
                message[key] = item[key]
        if message["content"]:
            loaded.append(message)
    st.session_state["l13_messages"] = loaded


def _persist_message(role: str, content: str, meta: dict | None = None) -> None:
    try:
        _request(
            "POST",
            "/api/chat/message",
            {"role": role, "content": content, "meta": meta},
        )
    except RuntimeError:
        pass


def _apply(
    action: str,
    version: int,
    *,
    plan_text: str | None = None,
    reason: str | None = None,
) -> None:
    label = ACTION_LABELS.get(action, action)
    try:
        with st.spinner(f"Применяю действие «{label}»…"):
            if action == "pause":
                _request("POST", "/api/task/pause", {"version": version})
            elif action == "resume":
                _request("POST", "/api/task/resume", {"version": version})
            elif action == "approve_plan":
                approved = _request(
                    "POST",
                    "/api/task/transition",
                    {"action": "approve_plan", "version": version},
                )
                # Утверждение плана сразу запускает реализацию.
                _request(
                    "POST",
                    "/api/task/transition",
                    {
                        "action": "start_execution",
                        "version": approved["version"],
                    },
                )
            else:
                payload: dict[str, Any] = {"action": action, "version": version}
                if plan_text is not None:
                    payload["plan_text"] = plan_text
                if reason:
                    payload["reason"] = reason
                _request("POST", "/api/task/transition", payload)
    except RuntimeError as exc:
        error_text = f"Действие «{label}» не выполнено: {exc}"
        messages = st.session_state.setdefault("l13_messages", [])
        messages.append({"role": "assistant", "content": error_text})
        st.session_state["l13_messages"] = messages
        _persist_message("assistant", error_text)
        st.session_state["l13_blocking_error"] = error_text
        st.rerun()
    st.session_state.pop("l13_blocking_error", None)
    notice = ACTION_SUCCESS.get(action, f"Действие «{label}» выполнено")
    messages = st.session_state.setdefault("l13_messages", [])
    messages.append({"role": "assistant", "content": notice})
    st.session_state["l13_messages"] = messages
    _persist_message("assistant", notice)
    st.session_state["l13_notice"] = notice
    st.rerun()


def _flash() -> None:
    message = st.session_state.pop("l13_flash", None)
    if message:
        st.error(message)
    blocking = st.session_state.pop("l13_blocking_error", None)
    if blocking:
        st.error(f"Ошибка выполнения задачи: {blocking}")
    notice = st.session_state.pop("l13_notice", None)
    if notice:
        st.success(f"Выполнено: {notice}")


def _stepper_html(task: dict[str, Any]) -> str:
    current = task["stage"]
    current_index = STAGE_INDEX.get(current, 0)
    paused = task.get("paused")
    cells: list[str] = []
    for index, (stage, label, hint) in enumerate(STAGES):
        if current == "done" or index < current_index:
            status, mark = "done", "✓"
        elif index == current_index:
            status, mark = "active", str(index + 1)
        else:
            status, mark = "future", str(index + 1)
        if paused and index == current_index:
            status = "paused"
            mark = "Ⅱ"
        cells.append(
            f'<div class="l13-step {status}">'
            f'<div class="l13-circle">{mark}</div>'
            f'<div class="l13-label">{html.escape(label)}</div>'
            f'<div class="l13-hint">{html.escape(hint)}</div>'
            "</div>"
        )
    return (
        '<div class="l13-stepper">'
        + "".join(cells)
        + "</div>"
        + _STEPPER_CSS
    )


_STEPPER_CSS = """
<style>
.l13-stepper {
  display: flex;
  align-items: stretch;
  gap: 0;
  padding: 18px 12px 14px;
  border: 1px solid rgba(128, 128, 128, .22);
  border-radius: 18px;
  background: rgba(128, 128, 128, .06);
  margin: 6px 0 16px;
}
.l13-step {
  flex: 1;
  min-width: 0;
  text-align: center;
  position: relative;
  padding: 0 6px;
}
.l13-step:not(:last-child)::after {
  content: "";
  position: absolute;
  top: 17px;
  left: calc(50% + 22px);
  width: calc(100% - 44px);
  height: 2px;
  background: rgba(128, 128, 128, .28);
}
.l13-step.done:not(:last-child)::after { background: #22c55e; }
.l13-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 15px;
  border: 2px solid rgba(128, 128, 128, .3);
  background: rgba(128, 128, 128, .12);
  color: inherit;
  position: relative;
  z-index: 1;
}
.l13-step.done .l13-circle { background: #22c55e; border-color: #22c55e; color: white; }
.l13-step.active .l13-circle { background: #2563eb; border-color: #2563eb; color: white; box-shadow: 0 0 0 5px rgba(37, 99, 235, .18); }
.l13-step.paused .l13-circle { background: #f59e0b; border-color: #f59e0b; color: white; box-shadow: 0 0 0 5px rgba(245, 158, 11, .18); }
.l13-label { margin-top: 9px; font-weight: 700; font-size: 14px; }
.l13-hint { margin-top: 3px; font-size: 11px; opacity: .65; line-height: 1.25; }
.l13-step.future .l13-label, .l13-step.future .l13-hint { opacity: .5; }
</style>
"""


def _badge(label: str, value: bool | str, tone: str = "neutral") -> str:
    if isinstance(value, bool):
        text = "✓" if value else "—"
        tone = "ok" if value else "muted"
    else:
        text = html.escape(str(value))
    return f'<span class="l13-badge {tone}">{html.escape(label)}: {text}</span>'


def _state_html(task: dict[str, Any]) -> str:
    flags = [
        _badge("План", task.get("plan_approved", False)),
        _badge("Реализация", task.get("execution_complete", False)),
        _badge("Валидация", task.get("validation_passed", False)),
    ]
    if task.get("validation_failed"):
        flags.append(_badge("Брак", True, "bad"))
    if task.get("done"):
        flags.append(_badge("Готово", True))
    if task.get("paused"):
        flags.append(_badge("Пауза", "активна", "warn"))
    return (
        '<div class="l13-flags">'
        + "".join(flags)
        + "</div>"
        + """
<style>
.l13-flags { display: flex; flex-wrap: wrap; gap: 7px; margin: 4px 0 12px; }
.l13-badge {
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid rgba(128,128,128,.25); border-radius: 999px;
  padding: 4px 10px; font-size: 12px; font-weight: 600;
}
.l13-badge.ok { background: rgba(34,197,94,.12); border-color: rgba(34,197,94,.35); }
.l13-badge.warn { background: rgba(245,158,11,.14); border-color: rgba(245,158,11,.4); }
.l13-badge.bad { background: rgba(239,68,68,.12); border-color: rgba(239,68,68,.35); }
.l13-badge.muted { opacity: .65; }
</style>
"""
    )


def _history(task: dict[str, Any]) -> None:
    try:
        items = _request("GET", "/api/task/history").get("items", [])
    except RuntimeError as exc:
        st.caption(f"История недоступна: {exc}")
        return
    with st.expander("История переходов и отказов", expanded=False):
        if not items:
            st.caption("Событий пока нет.")
            return
        for item in reversed(items):
            mark = "✓" if item["success"] else "✕"
            action = ACTION_LABELS.get(item["action"], item["action"])
            stage = f'{item["from_stage"]} → {item["to_stage"]}'
            line = f"{mark} **{action}** · {stage} · v{item['version_before']}→{item['version_after']}"
            if item.get("error_code"):
                line += f" · `{item['error_code']}`"
            st.markdown(line)


def _validation_timer_state(task: dict[str, Any]) -> None:
    """Явный интерактивный отсчёт перед автоматическим запуском валидации."""
    key = f"{task.get('task_id')}:{task.get('version')}"
    if st.session_state.get("l13_validation_key") != key:
        st.session_state["l13_validation_key"] = key
        st.session_state["l13_validation_deadline"] = time.time() + 10


@st.fragment(run_every=1)
def _validation_timer(task: dict[str, Any]) -> None:
    if (
        task.get("stage") != "execution"
        or not task.get("execution_complete")
        or task.get("paused")
    ):
        return
    _validation_timer_state(task)
    deadline = float(st.session_state.get("l13_validation_deadline") or 0)
    remaining = max(0, int(round(deadline - time.time())))
    st.markdown("#### Валидация")
    st.progress(min(1.0, (10 - remaining) / 10))
    if remaining > 0:
        st.warning(
            "Реализация завершена. Валидация начнётся автоматически "
            f"через **{remaining}** сек. Можно запустить раньше."
        )
        if st.button(
            "▶ Запустить валидацию сейчас",
            key="l13_validate_now",
            type="primary",
        ):
            st.session_state.pop("l13_validation_key", None)
            st.session_state.pop("l13_validation_deadline", None)
            _apply("start_validation", int(task["version"]))
    else:
        st.info("Отсчёт завершён. Запускаю валидацию…")
        st.session_state.pop("l13_validation_key", None)
        st.session_state.pop("l13_validation_deadline", None)
        _apply("start_validation", int(task["version"]))


def _validation_notice(task: dict[str, Any]) -> None:
    if task.get("stage") == "validation" and not task.get("done"):
        st.info(
            "Валидация идёт. Ожидается ваше решение: "
            "`/pass` — пройдена, `/fail` — не пройдена."
        )


def _execution(task: dict[str, Any]) -> None:
    steps = task.get("steps") or []
    if not steps:
        try:
            steps = _request("GET", "/api/task/steps").get("steps") or []
        except RuntimeError:
            steps = []
    if not steps:
        return
    done = sum(1 for step in steps if step.get("status") == "done")
    total = len(steps)
    st.markdown("#### Реализация по плану")
    st.progress(done / total if total else 0.0)
    st.caption(f"Выполнено шагов: **{done} из {total}**")
    labels = {
        "pending": "ожидает",
        "running": "выполняется",
        "done": "готово",
        "failed": "ошибка",
    }
    for step in steps:
        status = step.get("status") or "pending"
        title = f"{step.get('index')}. {step.get('title')}"
        with st.expander(f"{title} · {labels.get(status, status)}", expanded=False):
            result = step.get("result")
            if result:
                st.caption("Рассуждение и результат шага")
                st.markdown(_display_text(result))
            else:
                st.caption("Результата пока нет.")
    if (
        task.get("stage") == "execution"
        and not task.get("execution_complete")
        and not task.get("paused")
    ):
        pending = next(
            (step for step in steps if step.get("status") in {"pending", "failed"}),
            None,
        )
        if pending:
            if st.session_state.get("l13_auto_paused"):
                st.button(
                    "▶ Продолжить автовыполнение",
                    on_click=_resume_auto,
                    key="l13_auto_resume",
                )
            else:
                st.button(
                    "⏸ Остановить автовыполнение",
                    on_click=_pause_auto,
                    key="l13_auto_pause",
                )
            st.info("Следующий шаг выполняется автоматически.")
        elif done == total:
            st.success("Все шаги выполнены. Перехожу к валидации.")
    elif task.get("paused") and task.get("stage") == "execution":
        st.caption("Автовыполнение приостановлено вместе с задачей. Продолжите командой `/resume`.")


def _actions(task: dict[str, Any]) -> None:
    if not task.get("plan_text"):
        st.caption(
            "План формируется в чате: ответьте на вопросы ассистента, "
            "после этого план появится здесь."
        )
    elif task.get("expected_action") == "approve_plan":
        st.caption("Утверждение плана — командой `/approve` в чате.")
    if task.get("stage") == "done":
        st.caption(
            "Жизненный цикл завершён. Новая задача — `/gotask <цель>` в чате."
        )
    elif task.get("paused"):
        st.caption("Задача на паузе. Продолжите командой `/resume` в чате.")


def _clarification_message(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") == "error":
        return {
            "role": "assistant",
            "content": result.get("message")
            or "Не удалось получить уточнения. Повторите запрос.",
        }
    if result.get("status") == "plan":
        plan = result.get("plan") or ""
        return {
            "role": "assistant",
            "content": (
                "План сформирован и передан в блок «План задачи» выше. "
                "Проверьте его и отправьте `/approve`."
            ),
            "plan": plan,
        }
    questions = result.get("questions") or []
    return {
        "role": "assistant",
        "content": "Нужно уточнить перед планом:",
        "questions": questions,
        "kind": "question",
    }


def _start_approval_countdown(task: dict[str, Any], text: str) -> None:
    st.session_state["l13_approval_deadline"] = time.time() + 10
    st.session_state["l13_approval_version"] = int(task["version"])
    messages = st.session_state.setdefault("l13_messages", [])
    messages.append({"role": "user", "content": text})
    messages.append(
        {
            "role": "assistant",
            "content": "⏳ Утверждение плана начнётся через 10 секунд. Отсчёт пошёл.",
        }
    )
    st.session_state["l13_messages"] = messages
    _persist_message("user", text)
    _persist_message(
        "assistant", "⏳ Утверждение плана начнётся через 10 секунд. Отсчёт пошёл."
    )
    st.rerun()


def _run_approval_countdown(task: dict[str, Any]) -> None:
    deadline = st.session_state.get("l13_approval_deadline")
    version = st.session_state.get("l13_approval_version")
    if not deadline or version is None:
        return
    if task.get("expected_action") != "approve_plan":
        st.session_state.pop("l13_approval_deadline", None)
        st.session_state.pop("l13_approval_version", None)
        return
    placeholder = st.empty()
    while True:
        remaining = max(0, int(round(deadline - time.time())))
        if remaining <= 0:
            break
        placeholder.warning(
            f"⏳ Утверждение плана и запуск реализации через **{remaining}** сек…"
        )
        time.sleep(1)
    placeholder.success("Отсчёт завершён. Утверждаю план и запускаю реализацию.")
    st.session_state.pop("l13_approval_deadline", None)
    st.session_state.pop("l13_approval_version", None)
    _apply("approve_plan", int(version))


def _create_test_task() -> None:
    try:
        created = _request("POST", "/api/task", {"goal": TEST_GOAL})
        planned = _request(
            "POST",
            "/api/task/transition",
            {
                "action": "submit_plan",
                "version": int(created["version"]),
                "plan_text": TEST_PLAN,
                "reason": "Тестовое задание",
            },
        )
    except RuntimeError as exc:
        st.session_state["l13_blocking_error"] = f"Тестовое задание не запущено: {exc}"
        st.rerun()
        return
    messages = [
        {"role": "user", "content": TEST_GOAL},
        {
            "role": "assistant",
            "content": (
                "Тестовое задание создано. План из 3 шагов сформирован "
                "и ожидает утверждения."
            ),
        },
    ]
    st.session_state["l13_messages"] = messages
    st.session_state["l13_notice"] = "Тестовое задание создано: план ожидает утверждения"
    st.session_state["l13_scroll_input"] = True
    _persist_message("user", TEST_GOAL)
    _persist_message("assistant", messages[1]["content"])
    st.rerun()


def _create_task(goal: str) -> None:
    """Поставить задачу и сразу получить первый ответ ассистента."""
    goal = goal.strip()
    if not goal:
        st.warning("После `/gotask` укажите цель задачи.")
        return
    try:
        created = _request("POST", "/api/task", {"goal": goal})
    except RuntimeError as exc:
        st.session_state["l13_blocking_error"] = str(exc)
        st.rerun()
        return

    previous = st.session_state.get("l13_messages") or []
    context: list[dict[str, Any]] = []
    for item in previous[-20:]:
        content = item.get("content") or ""
        if item.get("questions"):
            content = (
                content
                + "\n"
                + "\n".join(
                    f"{number}. {question}"
                    for number, question in enumerate(item["questions"], 1)
                )
            )
        if content:
            context.append(
                {"role": item.get("role", "assistant"), "content": _clip(content)}
            )
    context.append({"role": "user", "content": goal})
    # В новый чат переносим только сообщения пользователя: они содержат
    # описанный до /gotask план. Старые ответы ассистента не показываем,
    # чтобы не смешивать их с новым состоянием задачи.
    previous_user = [
        item for item in previous[-20:] if item.get("role") == "user"
    ]
    messages: list[dict[str, Any]] = [
        *previous_user,
        {"role": "user", "content": goal},
    ]
    for item in previous_user:
        content = item.get("content") or ""
        if content:
            _persist_message("user", content)
    with st.spinner("Ассистент уточняет детали задачи с учётом чата…"):
        try:
            result = _request(
                "POST",
                "/api/task/clarify",
                {"history": context},
            )
        except RuntimeError as exc:
            messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "Задача создана, но получить уточняющие вопросы не удалось. "
                        f"Ошибка: {exc}"
                    ),
                }
            )
            st.session_state["l13_flash"] = f"Ошибка уточнений после /gotask: {exc}"
        else:
            messages.append(_clarification_message(result))
    st.session_state["l13_messages"] = messages
    st.session_state["l13_notice"] = "Задача поставлена"
    st.session_state["l13_scroll_input"] = True
    st.rerun()


def _agent_log() -> None:
    """Журнал действий агента: чат, поиск, переходы и ошибки."""
    if st.button("Обновить лог", key="l13_log_refresh"):
        st.rerun()
    try:
        items = _request("GET", "/api/task/log").get("items", [])
    except RuntimeError as exc:
        st.error(f"Лог недоступен: {exc}")
        return
    if not items:
        st.info("Событий пока нет.")
        return
    for item in items:
        level = item.get("level") or "info"
        when = str(item.get("created_at") or "")[:19].replace("T", " ")
        text = _display_text(
            f"`{when}` · **{item.get('kind', 'event')}** · {item.get('message', '')}"
        )
        if level == "error":
            st.error(text)
        elif level == "warning":
            st.warning(text)
        else:
            st.markdown(text)
        # Служебные JSON-детали в интерфейсе не показываем: только
        # человекочитаемое сообщение события.


def _task_summary(task: dict[str, Any]) -> None:
    st.markdown(_stepper_html(task), unsafe_allow_html=True)
    st.progress(
        min(
            1.0,
            (STAGE_INDEX.get(task["stage"], 0) + (1 if task["stage"] == "done" else 0))
            / 3,
        )
    )
    st.markdown(_state_html(task), unsafe_allow_html=True)

    left, right = st.columns([1.4, 1])
    with left:
        st.caption("Текущий шаг")
        st.markdown(f"### {task['current_step']}")
        expected = task.get("expected_action_label") or task.get("expected_action")
        st.caption(f"Ожидаемое действие: **{expected}**")
    with right:
        st.caption("Версия состояния")
        st.markdown(f"### v{task['version']}")
        if task.get("done"):
            status = "завершена"
        elif task.get("paused"):
            status = "на паузе"
        else:
            status = "активна"
        st.caption(f"Задача {status}. Переходы проверяет сервер.")

    st.caption(
        f"Цель: {task['goal']}"
        + (" · План сохранён" if task.get("plan_text") else "")
    )


def _task_plan(task: dict[str, Any]) -> None:
    if task.get("plan_text"):
        with st.expander("План задачи (передаётся в следующие этапы)", expanded=False):
            st.markdown(_display_text(task["plan_text"]))


def _task_details(task: dict[str, Any]) -> None:
    _history(task)
    if task.get("stage") == "done":
        st.caption(
            "Новая задача ставится командой `/gotask <цель>` в поле чата ниже."
        )


def _task_panel(task: dict[str, Any]) -> None:
    _task_summary(task)
    _task_details(task)


def _handle_message(text: str, task: dict[str, Any] | None, web_search: bool) -> None:
    messages = st.session_state.setdefault("l13_messages", [])

    gotask = GOTASK_RE.match(text)
    if gotask:
        _create_task(gotask.group(1) or "")
        return

    command_action = _command_action(text)
    if task is not None and command_action in (task.get("available_actions") or []):
        if command_action == "approve_plan":
            _start_approval_countdown(task, text)
            return
        ack = (
            "Выполняю действие «"
            + ACTION_LABELS.get(command_action, command_action)
            + "». Управление задачей остаётся в этом чате."
        )
        messages.append({"role": "user", "content": text})
        messages.append({"role": "assistant", "content": ack})
        st.session_state["l13_messages"] = messages
        _persist_message("user", text)
        _persist_message("assistant", ack)
        _apply(command_action, task["version"])
        return
    if task is None and command_action:
        st.warning("Сначала поставьте задачу: `/gotask <цель>` в этом же поле.")
        return
    if (
        task is not None
        and command_action == "start_validation"
        and task.get("stage") == "validation"
    ):
        st.info("Валидация уже идёт. Зафиксируйте итог: `/pass` или `/fail`.")
        return
    if task is not None and command_action:
        st.warning(
            "Действие «"
            + ACTION_LABELS.get(command_action, command_action)
            + "» сейчас недоступно. Ожидается: "
            + (task.get("expected_action_label") or "другое действие")
            + "."
        )
        return

    if task is not None and not task.get("plan_text"):
        clarify_history = []
        for item in messages:
            content = item.get("content") or ""
            if item.get("questions"):
                content = (
                    content
                    + "\n"
                    + "\n".join(
                        f"{number}. {question}"
                        for number, question in enumerate(item["questions"], 1)
                    )
                )
            if content:
                clarify_history.append(
                    {"role": item["role"], "content": _clip(content)}
                )
        clarify_history.append({"role": "user", "content": text})
        with st.spinner("Ассистент проверяет, достаточно ли данных для плана…"):
            try:
                result = _request(
                    "POST",
                    "/api/task/clarify",
                    {"history": clarify_history},
                )
            except RuntimeError as exc:
                st.error(f"Не удалось получить уточнения: {exc}")
                return
        messages.append({"role": "user", "content": text})
        messages.append(_clarification_message(result))
        st.session_state["l13_scroll_input"] = True
        st.rerun()

    history = [
        {"role": item["role"], "content": _clip(item["content"])}
        for item in messages[-12:]
        if item.get("content")
    ]
    with st.spinner("Ассистент отвечает…"):
        try:
            result = _request(
                "POST",
                "/api/chat",
                {
                    "message": text,
                    "history": history,
                    "web_search": web_search,
                },
            )
        except RuntimeError as exc:
            st.error(f"Не удалось получить ответ: {exc}")
            return
    search = result.get("web_search") or {}
    sources = search.get("results") or []
    note = None
    if web_search and not sources:
        note = "Интернет был включён, но источники получить не удалось."
    messages.append({"role": "user", "content": text})
    messages.append(
        {
            "role": "assistant",
            "content": result["answer"],
            "sources": sources,
            "search_note": note,
        }
    )
    st.session_state["l13_messages"] = messages
    st.rerun()


def _pause_auto() -> None:
    st.session_state["l13_auto_paused"] = True


def _resume_auto() -> None:
    st.session_state["l13_auto_paused"] = False


def _auto_run(task: dict[str, Any] | None, web_search: bool = False) -> None:
    """Выполнить следующий шаг автоматически, без команды /step."""
    if task is None:
        return
    if task.get("stage") != "execution" or task.get("execution_complete"):
        return
    if task.get("paused") or st.session_state.get("l13_auto_paused"):
        return
    steps = task.get("steps") or []
    pending = next(
        (step for step in steps if step.get("status") in {"pending", "failed"}),
        None,
    )
    if pending is None:
        return
    messages = st.session_state.setdefault("l13_messages", [])
    started = (
        f"⏳ Шаг {pending.get('index')} выполняется."
    )
    messages.append({"role": "assistant", "content": started})
    st.session_state["l13_messages"] = messages
    _persist_message("assistant", started)
    with st.spinner(
        f"Автовыполнение: шаг {pending.get('index')} — {pending.get('title')}…"
    ):
        try:
            step_path = "/api/task/step"
            if web_search:
                step_path += "?web_search=true"
            result = _request("POST", step_path)
        except RuntimeError as exc:
            messages = st.session_state.setdefault("l13_messages", [])
            error_text = f"❌ Шаг {pending.get('index')} не выполнен: {exc}"
            messages.append({"role": "assistant", "content": error_text})
            st.session_state["l13_messages"] = messages
            _persist_message("assistant", error_text)
            st.session_state["l13_auto_paused"] = True
            st.error(error_text)
            st.rerun()
            return
    step = result.get("step") or {}
    content = f"✅ Шаг {step.get('index')} выполнен."
    messages = st.session_state.setdefault("l13_messages", [])
    messages.append({"role": "assistant", "content": content})
    st.session_state["l13_messages"] = messages
    _persist_message("assistant", content)
    st.rerun()


def _queue_message() -> None:
    value = str(st.session_state.get("l13_prompt") or "").strip()
    if value:
        st.session_state["l13_pending_message"] = value


EXPECTED_HINTS = {
    "approve_plan": "отправьте `/approve`.",
    "start_execution": "начните реализацию командой `/start`.",
    "complete_execution": "шаги выполняются автоматически; после них начнётся валидация.",
    "start_validation": "валидация начнётся автоматически через 10 секунд; можно запустить командой `/validate`.",
    "pass_validation | fail_validation": "зафиксируйте итог: `/pass` или `/fail`.",
    "rework": "верните задачу в реализацию командой `/rework`.",
    "none": "задача завершена; новая задача — `/gotask <цель>`.",
}


def _expected_text(task: dict[str, Any]) -> str:
    if task.get("paused"):
        return "Ожидается от вас: **продолжить задачу** — `/resume`."
    action = task.get("expected_action") or "none"
    label = task.get("expected_action_label") or action
    hint = EXPECTED_HINTS.get(action, "выполните доступное действие в этом чате.")
    if task.get("stage") == "planning" and not task.get("plan_text"):
        return (
            "Ожидается от вас: **ответить на уточняющие вопросы** — "
            "после этого план сформируется автоматически."
        )
    return f"Ожидается от вас: **{label}** — {hint}"


def _command_reference() -> None:
    with st.expander("📋 Все команды чата", expanded=False):
        st.markdown(
            """
| Команда | Действие |
|---|---|
| `/gotask <цель>` | поставить новую задачу |
| `/approve` | утвердить план; через 10 секунд запустится реализация |
| `/start` | начать реализацию |
| `/validate` | начать валидацию |
| `/pass` | валидация пройдена |
| `/fail` | валидация не пройдена |
| `/rework` | вернуть задачу в реализацию |
| `/pause` | поставить на паузу |
| `/resume` | продолжить задачу |
"""
        )
        st.caption(
            "`/step`, `/complete` и `/finish` не используются: шаги выполняются "
            "автоматически, после `/pass` задача сразу переходит в «Готово»."
        )


def _chat(task: dict[str, Any] | None, web_search: bool) -> None:
    pending = st.session_state.pop("l13_pending_message", None)
    if pending:
        _handle_message(pending, task, web_search)
        # Не выходим: предупреждение о недоступной команде не должно
        # скрывать сам чат и поле ввода.

    messages = st.session_state.setdefault("l13_messages", [])
    pending_questions = next(
        (item for item in reversed(messages) if item.get("questions")),
        None,
    )
    if (
        pending_questions
        and task is not None
        and task.get("stage") == "planning"
        and not task.get("plan_text")
    ):
        st.warning(
            "Ассистент ждёт ответы на уточняющие вопросы. "
            "План не будет сформирован, пока вы не ответите."
        )
    _command_reference()
    with st.container(height=430, border=True):
        if task is not None:
            st.info(_expected_text(task))
        if not messages:
            if task is None:
                st.info(
                    "Чат работает без задачи. Чтобы включить визуализацию "
                    "жизненного цикла, отправьте `/gotask <цель>`."
                )
            else:
                st.info("Задайте вопрос по задаче. Ассистент видит текущее состояние.")
        for item in messages:
            with st.chat_message(
                item["role"],
                avatar="🧑" if item["role"] == "user" else "🤖",
            ):
                if item.get("questions"):
                    st.warning(item.get("content") or "Нужно уточнить перед планом:")
                    for number, question in enumerate(item["questions"], start=1):
                        st.markdown(f"**{number}.** {question}")
                    st.caption("Ответьте в поле ниже — план сформируется после ответов.")
                else:
                    st.markdown(
                        _display_text(item["content"])
                        if item["role"] == "assistant"
                        else item["content"]
                    )
                if item.get("search_note"):
                    st.caption(item["search_note"])

    if st.session_state.pop("l13_scroll_input", False):
        components_html(
            """
            <script>
            setTimeout(() => {
                const doc = window.parent.document;
                const input = doc.querySelector(
                    'input[aria-label="Сообщение или /gotask"]'
                );
                const main = doc.querySelector('[data-testid="stMain"]');
                if (main) main.scrollTop = main.scrollHeight;
                if (input) input.scrollIntoView({block: "center"});
            }, 700);
            </script>
            """,
            height=0,
        )

    st.caption(
        "Одно поле: обычный вопрос — чат; `/gotask <цель>` — постановка задачи."
    )
    with st.form("l13_chat_form", clear_on_submit=True):
        st.text_input(
            "Сообщение или /gotask",
            placeholder="Сообщение или /gotask Подготовить отчёт…",
            label_visibility="collapsed",
            key="l13_prompt",
        )
        st.form_submit_button("Отправить", type="primary", on_click=_queue_message)


def _clear_local_state() -> None:
    for key in (
        "l13_messages",
        "l13_pending_message",
        "l13_notice",
        "l13_flash",
        "l13_blocking_error",
        "l13_approval_deadline",
        "l13_approval_version",
        "l13_validation_key",
        "l13_validation_deadline",
        "l13_auto_paused",
        "l13_clear_confirm",
    ):
        st.session_state.pop(key, None)


def _sidebar_cleanup() -> None:
    with st.sidebar:
        st.divider()
        st.markdown("#### Урок 13 · данные")
        confirmed = st.checkbox(
            "Подтвердить очистку", key="l13_clear_confirm"
        )
        if st.button(
            "🧹 Очистить задачи",
            key="l13_clear_tasks",
            disabled=not confirmed,
            use_container_width=True,
        ):
            try:
                _request("DELETE", "/api/task")
            except RuntimeError as exc:
                st.error(f"Не удалось очистить задачи: {exc}")
            else:
                _clear_local_state()
                st.rerun()
        if st.button(
            "💬 Очистить чат",
            key="l13_clear_chat",
            disabled=not confirmed,
            use_container_width=True,
        ):
            try:
                _request("DELETE", "/api/chat/history")
            except RuntimeError as exc:
                st.error(f"Не удалось очистить чат: {exc}")
            else:
                st.session_state.pop("l13_messages", None)
                st.session_state.pop("l13_clear_confirm", None)
                st.rerun()
        st.caption("Действие необратимо; задачи и история удаляются из локальной БД.")


def render() -> None:
    _sidebar_cleanup()
    st.title("Состояние задачи (Task state machine)")
    st.caption(
        "Постановка задачи и чат — в одном поле. "
        "Команда `/gotask <цель>` включает визуализацию жизненного цикла."
    )
    _flash()

    web_search = st.toggle(
        "🌐 Разрешить агенту интернет",
        value=True,
        key="l13_web_search",
        help=(
            "Выключено — модель отвечает без сети. Включено — сервер ищет "
            "результаты поиска передаются модели без показа ссылок в ответе."
        ),
    )

    try:
        task = _get_task()
    except RuntimeError as exc:
        st.error(f"Не удалось загрузить состояние задачи: {exc}")
        task = None

    _load_history()

    tab_state, tab_log = st.tabs(["Состояние задачи", "Лог агента"])
    with tab_state:
        if task is None or task.get("done"):
            if st.button(
                "🧪 Тестовое задание: 5 событий 1969 года",
                type="secondary",
                key="l13_test_task",
            ):
                _create_test_task()
        else:
            st.caption(
                "Тестовое задание доступно после завершения текущей задачи."
            )
        if task is not None:
            _task_summary(task)
            _run_approval_countdown(task)
            _execution(task)
            _validation_timer(task)
            _validation_notice(task)
            _task_plan(task)
        else:
            st.info(
                "Задача не поставлена. Обычный чат работает без визуализации; "
                "для постановки задачи отправьте `/gotask <цель>`."
            )
        st.markdown("---")
        st.markdown("### Чат по задаче" if task is not None else "### Чат")
        _chat(task, web_search)
        if task is not None:
            _auto_run(task, web_search)
            st.markdown("---")
            _task_details(task)
    with tab_log:
        _agent_log()
