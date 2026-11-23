"""Страница урока 15: обновление памяти, конфликты и очистка."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import streamlit as st

from common import LESSON_15_API

NO_CACHE = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
POLICY_LABELS = {"replace": "перезапись", "append": "накопление"}


def _session_id() -> str:
    value = st.session_state.get("l15_session_id")
    if not value:
        query = st.query_params.get("l15_session")
        if isinstance(query, list):
            query = query[0] if query else None
        value = str(query or "").strip() or uuid.uuid4().hex
        st.session_state["l15_session_id"] = value
    return value


def _request(method: str, path: str, payload: dict | None = None) -> Any:
    headers = {"X-Session-Id": _session_id(), **NO_CACHE}
    with httpx.Client(timeout=180.0, headers=headers) as client:
        response = client.request(method, f"{LESSON_15_API}{path}", json=payload)
    if response.status_code >= 400:
        try:
            data = response.json()
            message = data.get("message") or data.get("detail") or response.text
            hint = data.get("hint")
        except Exception:  # noqa: BLE001
            message, hint = response.text, None
        text = str(message)
        if hint:
            text += f"\n\nКак исправить: {hint}"
        raise RuntimeError(text)
    return response.json()


def _state() -> dict[str, Any]:
    try:
        return _request("GET", f"/api/state?session_id={_session_id()}")
    except RuntimeError as exc:
        st.error(f"Не удалось загрузить память: {exc}")
        return {}


def _messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    return state.get("short_term") or []


def _facts_table(facts: list[dict[str, Any]]) -> None:
    if not facts:
        st.info("Фактов пока нет.")
        return
    st.dataframe(
        [
            {
                "Ключ": item.get("key"),
                "Факт": item.get("title"),
                "Актуальное значение": _numbered_value(
                    str(item.get("value") or ""), str(item.get("policy") or "")
                ),
                "Политика": POLICY_LABELS.get(
                    str(item.get("policy") or ""), str(item.get("policy") or "")
                ),
                "Записан": str(item.get("updated_at") or "")[:19].replace("T", " "),
            }
            for item in facts
        ],
        use_container_width=True,
        hide_index=True,
    )


def _chat(state: dict[str, Any]) -> None:
    st.markdown("#### Чат с актуальной памятью")
    st.caption(
        "Можно менять факты явно (`!fact deadline = 30 ноября`) или фразой "
        "«Срок сдвинулся на 30 ноября». После каждого вопроса агент получает "
        "только текущие значения."
    )
    with st.container(height=360, border=True):
        messages = _messages(state)
        if not messages:
            st.info("Напишите вопрос или измените факт.")
        for item in messages:
            role = item.get("role", "assistant")
            with st.chat_message(role, avatar="🧑" if role == "user" else "🧠"):
                st.markdown(item.get("content") or "")
    with st.form("l15_chat_form", clear_on_submit=True):
        text = st.text_input(
            "Сообщение",
            placeholder="Например: Срок сдвинулся на 30 ноября",
            label_visibility="collapsed",
            key="l15_prompt",
        )
        sent = st.form_submit_button("Отправить", type="primary")
    if sent:
        try:
            result = _request(
                "POST",
                "/api/chat",
                {"message": text, "session_id": _session_id()},
            )
        except RuntimeError as exc:
            st.error(f"Ошибка: {exc}")
        else:
            st.session_state["l15_last"] = result
            st.rerun()


def _quick_updates() -> None:
    st.markdown("#### Изменить факт")
    examples = [
        ("!fact deadline = 30 ноября", "Срок"),
        ("!fact sms_requirement = отменено", "Требование SMS"),
        ("!fact approach = Автоматическая проверка", "Подход"),
        ("!fact version = v2", "Версия"),
        ("!fact status = на проверке", "Статус"),
        ("!decision Добавили автоматическую проверку", "Новое решение"),
    ]
    for command, label in examples:
        if st.button(label, key=f"l15_update::{command}", use_container_width=True):
            try:
                _request(
                    "POST",
                    "/api/chat",
                    {"message": command, "session_id": _session_id()},
                )
            except RuntimeError as exc:
                st.error(f"Не удалось изменить факт: {exc}")
            else:
                st.rerun()


def _scenario() -> None:
    st.markdown("#### Сценарий: 4 изменения в диалоге")
    st.caption(
        "Меняются срок, SMS-требование, подход и версия. После каждого изменения "
        "агент получает актуальную память и отвечает на вопрос."
    )
    if st.button("▶ Провести 4 изменения и 4 вопроса", type="primary", key="l15_run_scenario"):
        with st.spinner("Меняю факты и запрашиваю агента…"):
            try:
                st.session_state["l15_scenario_result"] = _request(
                    "POST", f"/api/scenario?session_id={_session_id()}", {}
                )
            except RuntimeError as exc:
                st.error(f"Сценарий не выполнен: {exc}")
    result = st.session_state.get("l15_scenario_result")
    if result:
        a, b, c = st.columns(3)
        a.metric("Устаревших ответов", result.get("stale_answers", 0))
        b.metric("Упоминаний старых значений", result.get("stale_mentions", 0))
        c.metric("Старых значений в промпте", result.get("old_values_in_prompt", 0))
        if result.get("stale_answers"):
            st.error("Агент хотя бы раз назвал устаревшее значение.")
        else:
            st.success("Агент не назвал ни одного устаревшего значения.")
        rows = []
        for step in result.get("steps", []):
            rows.append(
                {
                    "Факт": step.get("key"),
                    "Было": _dialog_cells(step)[0],
                    "Стало": _dialog_cells(step)[1],
                    "Операция": step.get("mutation") or "",
                    "Вопрос": step.get("question"),
                    "Ответ": step.get("answer"),
                    "Устаревшие": ", ".join(step.get("stale_values") or []) or "—",
                    "Старое в промпте": bool(step.get("old_values_in_prompt")),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.markdown("#### История конфликтов")
        history = (result.get("state") or {}).get("history") or []
        if history:
            st.dataframe(
                [
                    {
                        "Когда": str(item.get("changed_at") or "")[:19].replace("T", " "),
                        "Факт": item.get("title"),
                        "Было": _history_cells(item)[0],
                        "Стало": _history_cells(item)[1],
                        "Тип": POLICY_LABELS.get(
                            str(item.get("change_type") or ""),
                            str(item.get("change_type") or ""),
                        ),
                        "Причина": item.get("reason"),
                    }
                    for item in history
                ],
                use_container_width=True,
                hide_index=True,
            )


def _history_cells(item: dict[str, Any]) -> tuple[str, str]:
    if item.get("change_type") == "append":
        new_value = str(item.get("new_value") or "")
        added = new_value.splitlines()[-1].lstrip("- ").strip() if new_value else ""
        return "—", f"+ {added}"
    return str(item.get("old_value") or ""), str(item.get("new_value") or "")


def _numbered_value(value: str, policy: str) -> str:
    if policy != "append":
        return value
    lines = []
    for line in (value or "").splitlines():
        item = line.strip()
        if item.startswith("- "):
            item = item[2:].strip()
        if item:
            lines.append(item)
    return "\n".join(f"{index}. {item}" for index, item in enumerate(lines, start=1))


def _append_scenario() -> None:
    st.markdown("#### Сценарии добавления: политика `append`")
    st.caption(
        "Уникальное значение увеличивает число записей. Повторяющееся значение "
        "не добавляется — появится уведомление."
    )
    left, right = st.columns(2)
    with left:
        if st.button(
            "➕ Добавить уникальное значение",
            type="primary",
            key="l15_append_unique",
        ):
            try:
                st.session_state["l15_append_result"] = _request(
                    "POST",
                    f"/api/append-scenario?session_id={_session_id()}",
                    {"mode": "unique", "session_id": _session_id()},
                )
            except RuntimeError as exc:
                st.error(f"Добавление не выполнено: {exc}")
            else:
                st.rerun()
    with right:
        if st.button(
            "↩ Добавить повторяющееся значение",
            key="l15_append_duplicate",
        ):
            try:
                st.session_state["l15_append_result"] = _request(
                    "POST",
                    f"/api/append-scenario?session_id={_session_id()}",
                    {"mode": "duplicate", "session_id": _session_id()},
                )
            except RuntimeError as exc:
                st.error(f"Проверка дубликата не выполнена: {exc}")
            else:
                st.rerun()
    result = st.session_state.get("l15_append_result")
    if result:
        a, b, c, d = st.columns(4)
        a.metric("Добавлено сейчас", result.get("added", 0))
        b.metric("Пропущено", result.get("skipped", 0))
        c.metric("Всего решений", result.get("decisions_count", 0))
        d.metric("Всего аудита", result.get("history_count", 0))
        if result.get("added"):
            st.success(result.get("message") or "Значение добавлено.")
        else:
            st.warning(result.get("message") or "Значение уже есть; не добавлено.")
        st.markdown("#### Добавленные элементы")
        status = "добавлено" if result.get("added") else "пропущено"
        st.dataframe(
            [
                {
                    "№": 1,
                    "Факт": "decisions",
                    "Добавлено": _numbered_value(
                        result.get("decisions") or "", "append"
                    ).splitlines()[-1]
                    if result.get("added")
                    else result.get("value"),
                    "Статус": status,
                }
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Показать накопленные значения", expanded=False):
            st.markdown("**Решения**")
            st.code(_numbered_value(result.get("decisions") or "", "append"), language="text")
            st.markdown("**История изменений**")
            st.code(_numbered_value(result.get("history") or "", "append"), language="text")

def _dialog_cells(step: dict[str, Any]) -> tuple[str, str]:
    change = step.get("change") or {}
    kind = step.get("kind")
    if kind == "replace":
        if not change.get("changed"):
            return "—", "без изменений (значение уже актуально)"
        return str(change.get("old_value") or ""), str(change.get("new_value") or "")
    if kind == "append":
        if change.get("skipped"):
            return "—", "пропущено"
        return "—", f"+ {step.get('value') or ''}"
    if kind == "duplicate":
        return "—", "не добавлено (дубликат)"
    return str(change.get("old_value") or ""), "без изменений"


def _dialog_scenario() -> None:
    st.markdown("#### Тестовый диалог: конфликты + добавления")
    st.caption(
        "Смешанный сценарий: срок и подход перезаписываются, решения "
        "накапливаются, повторяющееся решение пропускается, после каждого "
        "шага агент получает актуальную память."
    )
    if st.button(
        "▶ Провести тестовый диалог",
        type="primary",
        key="l15_run_dialog",
    ):
        with st.spinner("Выполняю 9 шагов диалога…"):
            try:
                st.session_state["l15_dialog_result"] = _request(
                    "POST", f"/api/dialog-scenario?session_id={_session_id()}", {}
                )
            except RuntimeError as exc:
                st.error(f"Тестовый диалог не выполнен: {exc}")
    result = st.session_state.get("l15_dialog_result")
    if result:
        a, b, c, d, e = st.columns(5)
        a.metric("Перезаписано фактов", result.get("facts_overwritten", 0))
        b.metric("Добавлено фактов", result.get("facts_added", 0))
        c.metric("Дубликатов пропущено", result.get("skipped", 0))
        d.metric("Устаревших ответов", result.get("stale_answers", 0))
        e.metric("Старых в промпте", result.get("old_values_in_prompt", 0))
        if result.get("probe_stale"):
            st.warning(
                "Провокация сработала: агент назвал устаревшее значение — "
                + ", ".join(result.get("probe_stale_values") or [])
            )
        else:
            st.success(
                "Провокация не сработала: агент не назвал устаревшее значение; "
                "в промпте только актуальные значения."
            )
        st.dataframe(
            [
                {
                    "№": step.get("step"),
                    "Тип": step.get("kind"),
                    "Факт": step.get("key"),
                    "Было": _dialog_cells(step)[0],
                    "Стало": _dialog_cells(step)[1],
                    "Операция": step.get("mutation") or "",
                    "Вопрос": step.get("question"),
                    "Ответ": step.get("answer"),
                    "Устаревшие": ", ".join(step.get("stale_values") or []) or "—",
                    "Старое в промпте": bool(step.get("old_values_in_prompt")),
                }
                for step in result.get("steps", [])
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Диалог и изменения памяти", expanded=True):
            for step in result.get("steps", []):
                with st.chat_message("user", avatar="🧑"):
                    st.markdown(step.get("user_message") or step.get("question") or "")
                st.caption(
                    "⚙️ "
                    + (step.get("mutation") or "изменение памяти")
                    + " · "
                    + (
                        "применено"
                        if step.get("change", {}).get("changed")
                        else "пропущено"
                    )
                )
                with st.chat_message("assistant", avatar="🧠"):
                    st.markdown(step.get("answer") or "")


def _rules(state: dict[str, Any]) -> None:
    st.markdown("#### Правила долговременной памяти")
    st.dataframe(
        [
            {
                "Ключ": item.get("key"),
                "Факт": item.get("title"),
                "Правило": POLICY_LABELS.get(
                    str(item.get("policy") or ""), str(item.get("policy") or "")
                ),
                "Категория": item.get("category"),
                "Описание": item.get("description"),
            }
            for item in state.get("policies") or []
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### Проверка промпта")
    if st.button("Показать актуальный промпт", key="l15_show_prompt"):
        try:
            prompt = _request("GET", f"/api/prompt?session_id={_session_id()}")
        except RuntimeError as exc:
            st.error(f"Промпт недоступен: {exc}")
        else:
            st.code(prompt.get("prompt") or "", language="text")
            old = prompt.get("old_values_in_prompt") or []
            if old:
                st.error("В промпте найдены устаревшие значения: " + ", ".join(old))
            else:
                st.success("Устаревших значений в промпте нет.")
    st.markdown("#### Очистка рабочей памяти")
    st.caption(
        "Завершение задачи удаляет краткосрочную и рабочую память; "
        "долговременные факты сохраняются."
    )
    if st.button("✅ Завершить задачу", key="l15_complete", type="primary"):
        try:
            result = _request(
                "POST",
                "/api/task/complete",
                {"session_id": _session_id()},
            )
        except RuntimeError as exc:
            st.error(f"Не удалось завершить задачу: {exc}")
        else:
            st.session_state["l15_cleared"] = result
            st.rerun()
    cleared = st.session_state.get("l15_cleared")
    if cleared:
        a, b, c = st.columns(3)
        a.metric("Рабочая память", (cleared.get("cleared") or {}).get("working", 0))
        b.metric("Краткосрочная", (cleared.get("cleared") or {}).get("short_term", 0))
        c.metric("Долговременных фактов", cleared.get("long_term_preserved", 0))
        st.success("Задача завершена: рабочая память очищена, факты сохранены.")


def _sidebar() -> None:
    with st.sidebar:
        st.markdown("### Память")
        if st.button("Сбросить всё к стартовым фактам", key="l15_reset"):
            try:
                _request("POST", "/api/reset", {})
            except RuntimeError as exc:
                st.error(f"Сброс не удался: {exc}")
            else:
                for key in ("l15_scenario_result", "l15_append_result", "l15_dialog_result", "l15_last", "l15_cleared"):
                    st.session_state.pop(key, None)
                st.rerun()


def render() -> None:
    _sidebar()
    st.title("Устаревание и конфликты памяти")
    st.caption(
        "Факты не только пополняются, но и обновляются: новое значение заменяет "
        "старое, конфликт фиксируется в логе, рабочая память очищается после задачи."
    )
    state = _state()
    sections = [
        "Проверка памяти",
        "Сценарий конфликтов",
        "Сценарии добавления",
        "Тестовый диалог",
        "Правила и очистка",
    ]
    selected = st.segmented_control(
        "Раздел",
        sections,
        default=sections[0],
        key="l15_active_section",
        label_visibility="collapsed",
    ) or sections[0]
    if selected == sections[0]:
        left, right = st.columns([1.15, 1])
        with left:
            st.markdown("#### Актуальные факты")
            _facts_table(state.get("facts") or [])
            st.caption(
                "У каждого факта есть время записи. Перезапись и накопление "
                "работают по правилам."
            )
            st.markdown("#### Последние конфликты")
            history = (state.get("history") or [])[:8]
            if history:
                st.dataframe(
                    [
                        {
                            "Факт": item.get("title"),
                            "Было": _history_cells(item)[0],
                            "Стало": _history_cells(item)[1],
                            "Тип": item.get("change_type"),
                        }
                        for item in history
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.caption("Конфликтов пока нет.")
        with right:
            _chat(state)
            _quick_updates()
    elif selected == sections[1]:
        _scenario()
    elif selected == sections[2]:
        _append_scenario()
    elif selected == sections[3]:
        _dialog_scenario()
    else:
        _rules(state)
