"""Вкладка «Сохранение контекста» — урок 07.

Диалог хранится в SQLite на стороне API. Streamlit только перерисовывает
историю и отправляет новый ход; при перезагрузке страницы контекст остаётся.
"""

from __future__ import annotations

import re
import secrets
from html import escape as html_escape

import httpx
import streamlit as st

from common import CONTEXT_API, model_sidebar, selectable_models

SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

#: человекочитаемое действие вместо технического описания инструмента
TOOL_ACTIONS = {
    "calculator": "выполняет вычисление",
    "current_time": "уточняет текущее время",
    "text_stats": "анализирует текст",
    "currency_rates": "получает курсы валют",
    "unit_converter": "переводит единицы измерения",
    "date_diff": "считает разницу дат",
    "number_base": "переводит систему счисления",
    "number_stats": "считает статистику чисел",
    "text_hash": "считает хеш текста",
}


@st.cache_data(ttl=15, show_spinner=False)
def load_backend() -> dict:
    result: dict = {
        "health": None,
        "models": [],
        "providers": [],
        "sessions": [],
        "tools": [],
        "error": None,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{CONTEXT_API}/api/health").json()
            result["models"] = client.get(f"{CONTEXT_API}/api/models").json()
            result["providers"] = client.get(f"{CONTEXT_API}/api/providers/status").json()
            result["sessions"] = client.get(f"{CONTEXT_API}/api/sessions").json()
            result["tools"] = client.get(f"{CONTEXT_API}/api/tools").json()
    except Exception as exc:  # noqa: BLE001 - показываем в интерфейсе
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _query_session() -> str:
    raw = st.query_params.get("session")
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    return raw if isinstance(raw, str) and SESSION_RE.fullmatch(raw) else ""


def _new_session() -> str:
    return f"ctx-{secrets.token_hex(5)}"


def _plural(number: int, one: str, few: str, many: str) -> str:
    value = abs(number)
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def _session_label(item: dict) -> str:
    """Человекочитаемое имя: номер диалога + тема + размер."""
    number = int(item.get("number") or 0)
    title = " ".join(str(item.get("title") or "").split())
    if len(title) > 54:
        title = title[:51].rstrip() + "…"
    if number:
        label = f"Диалог {number}"
        if title:
            label += f" · {title}"
    else:
        label = "Новый диалог"
    count = int(item.get("message_count") or 0)
    if count:
        label += f" · {count} сообщ."
    return label


def _fetch_session(session_id: str) -> dict | None:
    with httpx.Client(timeout=15.0) as client:
        response = client.get(f"{CONTEXT_API}/api/sessions/{session_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _tool_name(call: dict) -> str:
    function = call.get("function") or {}
    return str(function.get("name") or call.get("name") or "tool")


def _render_history(
    messages: list[dict],
    labels: dict[str, str],
    descriptions: dict[str, str],
) -> None:
    """Показать реплики и факты вызова инструментов без JSON."""
    for item in messages:
        role = item.get("role")
        content = item.get("content") or ""
        if role == "tool":
            # аргументы и JSON-результат в интерфейсе не показываем,
            # но отмечаем, что результат сохранён в контексте
            name = item.get("name") or "tool"
            st.markdown(
                f'<div class="ctx-tool-note">💾 результат «{labels.get(name, name)}» сохранён</div>',
                unsafe_allow_html=True,
            )
            continue

        calls = item.get("tool_calls") or []
        if role == "assistant" and calls:
            with st.chat_message("assistant"):
                if content:
                    st.markdown(content)
                for call in calls:
                    name = _tool_name(call)
                    label = labels.get(name, name)
                    action = TOOL_ACTIONS.get(name, descriptions.get(name) or "вызов инструмента")
                    st.markdown(f"🔧 **{label}** — {action} · 💾")
            continue

        with st.chat_message(role or "assistant"):
            st.markdown(
                f"{content} <span class='ctx-saved'>💾 сохранено</span>",
                unsafe_allow_html=True,
            )


def _last_turn(messages: list[dict]) -> list[dict]:
    start = 0
    for index, item in enumerate(messages):
        if item.get("role") == "user":
            start = index
    return messages[start:]


def _render_summary(
    messages: list[dict],
    labels: dict[str, str],
    descriptions: dict[str, str],
) -> None:
    """Итог последнего хода: текст, действия и инструменты без JSON."""
    turn = _last_turn(messages)
    if not turn:
        return

    final = next(
        (
            item.get("content")
            for item in reversed(turn)
            if item.get("role") == "assistant" and item.get("content")
        ),
        "",
    )
    calls: list[str] = []
    for item in turn:
        for call in item.get("tool_calls") or []:
            calls.append(_tool_name(call))

    st.markdown("#### Итог")
    if final:
        st.markdown(f"**Результат:** {final}")
    if calls:
        st.markdown("**Действия агента:**")
        for index, name in enumerate(calls, 1):
            label = labels.get(name, name)
            action = TOOL_ACTIONS.get(name, descriptions.get(name) or "вызов инструмента")
            st.markdown(f"{index}. {label} — {action}")
        counts: dict[str, int] = {}
        for name in calls:
            counts[name] = counts.get(name, 0) + 1
        st.markdown(
            "**Использованные инструменты:** "
            + ", ".join(
                f"{labels.get(name, name)} ×{count}"
                for name, count in counts.items()
            )
        )
    else:
        st.caption("Инструменты не использовались.")


def _render_context_note(data: dict) -> None:
    context = data.get("context") or {}
    if not context:
        return
    st.caption(
        f"В контекст ушло: {context.get('included_messages', 0)} сообщ. "
        f"· отброшено: {context.get('dropped_messages', 0)} "
        f"· {context.get('chars', 0)} символов"
        + (
            f" · прошлых бесед: {context.get('past_sessions', 0)}"
            if context.get("past_sessions")
            else ""
        )
    )


def _new_session_click() -> None:
    fresh = _new_session()
    st.session_state["ctx_session"] = fresh
    st.session_state["ctx_session_pick"] = fresh
    st.session_state["ctx_last"] = None


def render() -> None:
    st.markdown(
        """<style>
        [data-testid="stChatMessage"] {
            padding: .32rem .55rem !important;
            margin: 0 0 .28rem 0 !important;
            border-radius: .45rem !important;
        }
        [data-testid="stChatMessage"] [data-testid="stChatMessageAvatar"] {
            width: 1.35rem !important;
            height: 1.35rem !important;
            min-width: 1.35rem !important;
            margin-top: .1rem !important;
        }
        [data-testid="stChatMessage"] [data-testid="stChatMessageContent"] {
            gap: 0 !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p {
            margin: 0 0 .16rem 0 !important;
            font-size: .9rem !important;
            line-height: 1.34 !important;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] ul,
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] ol {
            margin: .1rem 0 .15rem 1.1rem !important;
        }
        .ctx-saved {
            font-size: .62rem; opacity: .42; white-space: nowrap;
            margin-left: .35rem; font-weight: 400;
        }
        .ctx-tool-note {
            font-size: .64rem; opacity: .42; margin: .05rem 0 .25rem 1.6rem;
        }
        .ctx-stats-row {
            display: flex; justify-content: flex-end; align-items: center;
            gap: .9rem; flex-wrap: wrap; font-size: .68rem; opacity: .62;
            margin: -.15rem 0 .45rem 0; text-align: right;
        }
        .ctx-stats-row span { white-space: nowrap; }
        .ctx-stats-row b { font-size: .78rem; opacity: .95; font-weight: 600; }
        .ctx-stats-row .sep { opacity: .28; }
        </style>""",
        unsafe_allow_html=True,
    )
    backend = load_backend()
    models = selectable_models(backend["models"])

    sessions = list(backend["sessions"] or [])
    latest_session = sessions[0]["id"] if sessions else ""
    # При первом открытии раздела показываем последний сохранённый диалог.
    if "ctx_session" not in st.session_state:
        st.session_state["ctx_session"] = latest_session or _query_session() or _new_session()
    if not models:
        st.error("API урока 07 недоступен или не вернул модели")
        if backend["error"]:
            st.caption(backend["error"])
        return

    models_by_id = {item["id"]: item for item in models}
    session_id = st.session_state["ctx_session"]
    st.query_params["session"] = session_id

    with st.sidebar:
        st.markdown("#### Контекст")
        sessions = list(backend["sessions"] or [])
        if not any(item["id"] == session_id for item in sessions):
            sessions.insert(0, {"id": session_id, "title": "", "message_count": 0})
        by_id = {item["id"]: item for item in sessions}
        options = [session_id] + [item["id"] for item in sessions if item["id"] != session_id]
        picked = st.selectbox(
            "Сессия",
            options=options,
            index=options.index(session_id),
            format_func=lambda value: _session_label(by_id[value]),
            key="ctx_session_pick",
            help="Выберите сохранённый диалог; имя содержит уникальный суффикс",
        )
        if picked != session_id:
            st.session_state["ctx_session"] = picked
            st.session_state["ctx_last"] = None
            st.query_params["session"] = picked
            session_id = picked

        if st.button("Новая сессия", use_container_width=True, on_click=_new_session_click):
            st.rerun()

        if st.button("Очистить историю", use_container_width=True):
            try:
                with httpx.Client(timeout=15.0) as client:
                    response = client.post(f"{CONTEXT_API}/api/sessions/{session_id}/clear")
                if response.status_code not in (200, 404):
                    response.raise_for_status()
                st.session_state["ctx_last"] = None
                load_backend.clear()
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Не удалось очистить: {exc}")

        with st.popover("🗑  Удалить все контексты", use_container_width=True):
            st.warning("Будут удалены все диалоги и история инструментов из базы.")
            if st.button("Подтвердить удаление", type="primary", use_container_width=True):
                try:
                    with httpx.Client(timeout=15.0) as client:
                        response = client.delete(f"{CONTEXT_API}/api/sessions")
                    if response.status_code != 200:
                        response.raise_for_status()
                    st.session_state["ctx_last"] = None
                    load_backend.clear()
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Не удалось удалить контексты: {exc}")

        past_sessions = [
            item for item in (backend["sessions"] or [])
            if item["id"] != session_id
        ]
        past_keys = {
            item["id"]: f"ctx_past::{item['id']}" for item in past_sessions
        }
        use_all_past = bool(st.session_state.get("ctx_use_all"))
        chosen_past = (
            len(past_sessions)
            if use_all_past
            else sum(1 for key in past_keys.values() if st.session_state.get(key))
        )
        selected_past: list[str] = []
        with st.popover(
            f"🗂  Контекст прошлых бесед · {chosen_past}/{len(past_sessions)}  ▾",
            use_container_width=True,
        ):
            if not past_sessions:
                st.caption("Прошлых бесед пока нет.")
            else:
                st.caption(
                    "Можно отметить несколько диалогов или взять все сразу."
                )
                st.checkbox(
                    "Использовать все прошлые сессии",
                    key="ctx_use_all",
                    help="В контекст попадут все сохранённые диалоги, кроме текущего",
                )
                if st.session_state.get("ctx_use_all"):
                    selected_past = [item["id"] for item in past_sessions]
                    st.caption("Выбраны все прошлые диалоги.")
                else:
                    for item in past_sessions:
                        label = _session_label(item)
                        if st.checkbox(label, key=past_keys[item["id"]]):
                            selected_past.append(item["id"])
        st.caption(f"Сохранённых диалогов: {len(backend['sessions'] or [])}")

        st.divider()
        controls = model_sidebar(
            models,
            backend["providers"],
            st.session_state.get("ui_model"),
            prefix="ctx",
            temperature_default=0.2,
            max_tokens_default=800,
            model_key="ui_model",
        )
        max_messages = st.slider(
            "Сообщений в контексте",
            min_value=2,
            max_value=500,
            value=20,
            step=1,
            key="ctx_max_messages",
            help="Сколько последних сообщений отправлять модели; максимум 500",
        )
        max_steps = st.slider(
            "Максимум шагов",
            min_value=1,
            max_value=10,
            value=6,
            key="ctx_max_steps",
            help="Сколько раз агент может вызвать инструмент",
        )

        # Тот же вид выбора инструментов, что в уроке 06: поповер и чекбоксы.
        tool_map = {
            item["name"]: item.get("label") or item["name"]
            for item in (backend["tools"] or [])
        }
        for name in tool_map:
            key = f"ctx_tool::{name}"
            if key not in st.session_state:
                st.session_state[key] = True
        chosen = sum(1 for name in tool_map if st.session_state[f"ctx_tool::{name}"])
        selected_tools: list[str] = []
        st.caption(f"Выбрано инструментов: {chosen} из {len(tool_map)}")

        def _select_all_tools() -> None:
            for name in tool_map:
                st.session_state[f"ctx_tool::{name}"] = True

        with st.popover(
            f"🧰  Инструменты агента · {chosen}/{len(tool_map)}  ▾",
            use_container_width=True,
        ):
            st.caption(f"Выбрано: {chosen} из {len(tool_map)}")
            for name, label in tool_map.items():
                if st.checkbox(label, key=f"ctx_tool::{name}"):
                    selected_tools.append(name)
            if not selected_tools:
                st.caption(
                    "0/9: для новых запросов инструменты выключены. "
                    "Старые вызовы в истории не выполняются повторно."
                )
            if chosen < len(tool_map):
                st.button(
                    "Выбрать все",
                    use_container_width=True,
                    on_click=_select_all_tools,
                )

    detail = None
    error = None
    try:
        detail = _fetch_session(session_id)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    messages = (detail or {}).get("messages") or []
    title = (detail or {}).get("title") or "Новый диалог"

    model_label = (models_by_id.get(controls["model"]["id"]) or {}).get("label", "—")
    dialogs_count = (backend["health"] or {}).get("sessions", "—")
    current_session = next(
        (item for item in (backend["sessions"] or []) if item["id"] == session_id),
        {"id": session_id, "title": (detail or {}).get("title") or "", "message_count": len(messages)},
    )
    session_label = _session_label(current_session)
    stats = (
        f'<div class="ctx-stats-row">'
        f'<span>Сообщений <b>{len(messages)}</b></span>'
        f'<span class="sep">·</span>'
        f'<span>Сессия <b>{html_escape(session_label)}</b></span>'
        f'<span class="sep">·</span>'
        f'<span>Модель <b>{html_escape(str(model_label))}</b></span>'
        f'<span class="sep">·</span>'
        f'<span>Диалогов в базе <b>{html_escape(str(dialogs_count))}</b></span>'
        f'</div>'
    )
    st.markdown(stats, unsafe_allow_html=True)
    st.markdown("## Сохранение контекста и инструментов")
    st.caption(
        "В SQLite сохраняются реплики, вызовы инструментов и их результаты. "
        "После перезагрузки агент загружает историю и продолжает диалог."
    )

    if selected_past:
        count = len(selected_past)
        st.caption(
            f"Дополнительный контекст: {count} прошлых "
            f"{_plural(count, 'диалог', 'диалога', 'диалогов')}."
        )

    if error:
        st.error(f"API урока 07 недоступен: {error}")
    elif detail is None:
        st.info("Для этой сессии ещё нет сохранённых сообщений.")
    else:
        st.caption(f"Тема: {title}")

    labels = {
        item["name"]: item.get("label") or item["name"]
        for item in (backend["tools"] or [])
    }
    descriptions = {
        item["name"]: item.get("description") or ""
        for item in (backend["tools"] or [])
    }
    if messages:
        _render_history(messages, labels, descriptions)
        _render_summary(messages, labels, descriptions)
    else:
        st.info("Напиши первое сообщение — оно сразу попадёт в сохранённый контекст.")

    last = st.session_state.get("ctx_last")
    if last:
        with st.expander("Последний запрос: окно контекста", expanded=False):
            _render_context_note(last)
            steps = last.get("steps") or []
            if steps:
                st.caption(
                    "Вызванные инструменты: "
                    + " → ".join(
                        f"{step.get('label') or step.get('tool')} ×{sum(1 for s in steps if s.get('tool') == step.get('tool'))}"
                        for step in steps
                    )
                )
            usage = last.get("usage") or {}
            if usage:
                st.caption(
                    "Токены: "
                    f"запрос {usage.get('prompt_tokens', 0)} · "
                    f"ответ {usage.get('completion_tokens', 0)} · "
                    f"всего {usage.get('total_tokens', 0)}"
                )

    prompt = st.chat_input("Сообщение агенту…")
    if prompt:
        payload = {
            "session_id": session_id,
            "prompt": prompt,
            "model": controls["model"]["id"],
            "temperature": controls["temperature"],
            "reasoning": controls["reasoning"],
            "max_tokens": controls["max_tokens"],
            "max_messages": max_messages,
            "tools": selected_tools,
            "max_steps": max_steps,
            "context_sessions": selected_past,
        }
        try:
            with st.spinner("Модель отвечает…"):
                with httpx.Client(timeout=180.0) as client:
                    response = client.post(f"{CONTEXT_API}/api/chat", json=payload)
            if response.status_code != 200:
                st.error(f"API {response.status_code}: {response.text[:500]}")
            else:
                st.session_state["ctx_last"] = response.json()
                load_backend.clear()
                st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Не удалось отправить запрос: {exc}")
