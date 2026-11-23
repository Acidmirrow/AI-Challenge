"""Страница урока 11: модель памяти ассистента."""

from __future__ import annotations

from html import escape

import httpx
import streamlit as st

from common import LESSON_11_API

SESSION_ID = "demo"
DEMO_OWNER = "demo-check"
DEMO_SESSION = "demo-check"


NO_CACHE_HEADERS = {"Cache-Control": "no-cache", "Pragma": "no-cache"}


def _get(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30.0, headers=NO_CACHE_HEADERS) as client:
        response = client.get(f"{LESSON_11_API}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: dict) -> dict:
    with httpx.Client(timeout=120.0, headers=NO_CACHE_HEADERS) as client:
        response = client.post(f"{LESSON_11_API}{path}", json=payload)
    response.raise_for_status()
    return response.json()


def _delete(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30.0, headers=NO_CACHE_HEADERS) as client:
        response = client.delete(f"{LESSON_11_API}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _plural(value: int, one: str, few: str, many: str) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def _short(text: str, limit: int = 56) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _default_prompt(state: dict, retrieved: list[dict] | None = None) -> str:
    """Промт по умолчанию: виден в поле ввода, но не отправляется сам."""
    short = state.get("short_term") or {}
    messages = short.get("messages") or []
    last_user = next(
        (item["content"] for item in reversed(messages) if item["role"] == "user"),
        "—",
    )
    working = state.get("working") or {}
    long_term = state.get("long_term") or {}
    grouped: dict[str, list[dict]] = {}
    for item in retrieved or []:
        grouped.setdefault(item.get("section", ""), []).append(item)
    profile = grouped.get("profile") or (long_term.get("profile") or [])
    decisions = grouped.get("decisions") or (long_term.get("decisions") or [])
    knowledge = grouped.get("knowledge") or (long_term.get("knowledge") or [])

    def keys(items: list[dict]) -> str:
        return ", ".join(item["key"] for item in items[:2]) or "—"

    return (
        "Ответь с опорой на все три слоя памяти.\n"
        f"Краткосрочная: {short.get('count', 0)} сообщений; последний запрос: {_short(last_user, 80)}.\n"
        f"Рабочая: {_short(working.get('title') or 'задача не задана', 60)}; "
        f"статус: {_short(working.get('status') or '—', 40)}; "
        f"следующий шаг: {_short(working.get('next_step') or '—', 60)}.\n"
        f"Долговременная: профиль — {keys(profile)}; решения — {keys(decisions)}; "
        f"знания — {keys(knowledge)}.\n"
        "Сначала перечисли, какие сведения из какого слоя используешь, затем ответь."
    )


def _render_prompt_breakdown(context: dict, state: dict) -> None:
    """Компактно показать, что реально попало в prompt и сколько это токенов."""
    layers = context.get("layers") or {}
    short = state.get("short_term") or {}
    short_messages = short.get("messages") or []
    window = int(context.get("short_window") or short.get("prompt_window") or 8)
    recent = short_messages[-window:]
    working = state.get("working") or {}
    working_items = [
        f"{label}: {_short(working[field], 42)}"
        for field, label in (
            ("title", "Задача"),
            ("goal", "Цель"),
            ("status", "Статус"),
            ("next_step", "Следующий шаг"),
            ("constraints", "Ограничения"),
        )
        if working.get(field)
    ]
    retrieved = context.get("retrieved") or []
    long_text = ", ".join(
        f"{item['section']}/{item['key']}" for item in retrieved[:5]
    )
    if len(retrieved) > 5:
        long_text += f" и ещё {len(retrieved) - 5}"

    rows = [
        {
            "Слой": "Краткосрочная",
            "Что попало": _short(
                "; ".join(item["content"] for item in recent) or "пусто", 90
            ),
            "Токены": layers.get("short_term", {}).get("tokens", 0),
        },
        {
            "Слой": "Рабочая",
            "Что попало": _short("; ".join(working_items) or "пусто", 90),
            "Токены": layers.get("working", {}).get("tokens", 0),
        },
        {
            "Слой": "Долговременная",
            "Что попало": _short(long_text or "пусто", 90),
            "Токены": layers.get("long_term", {}).get("tokens", 0),
        },
    ]
    with st.expander("🧩 Что попало в промт", expanded=True):
        request_tokens = int(context.get("request_tokens") or context.get("total_tokens") or 0)
        response_tokens = int(context.get("response_tokens") or 0)
        st.markdown(
            f"**Промт запроса:** {_num(request_tokens)} токенов · "
            f"**Промт ответа:** {_num(response_tokens)} токенов"
        )
        st.table(rows)
        st.caption(
            f"Всего в контексте ~{_num(context.get('total_tokens', 0))} токенов · "
            f"долговременная: {len(retrieved)} из "
            f"{layers.get('long_term', {}).get('available', len(retrieved))} записей."
        )


def _card(label: str, subtitle: str, value: str, hint: str, css: str) -> str:
    return f"""
    <div class="mem-card {css}">
      <div class="mem-card-top"><span>{escape(label)}</span><b>{escape(value)}</b></div>
      <div class="mem-card-sub">{escape(subtitle)}</div>
      <div class="mem-card-hint">{escape(hint)}</div>
    </div>
    """


def _refresh() -> None:
    st.rerun()


def _invalidate() -> None:
    """Сбросить локальные снимки, чтобы экран перечитал состояние из API."""
    for key in ("l11_last_context", "l11_last_state"):
        st.session_state.pop(key, None)
    # Не трогаем widget key после его создания — просим пересобрать промт
    # на следующем rerun.
    st.session_state["l11_reset_message"] = True


def _snapshot(parts: list[str], empty: str = "пусто") -> None:
    text = " · ".join(part for part in parts if part) or empty
    st.caption(f"Сейчас в памяти: {_short(text, 220)}")


def _render_storage_info() -> None:
    st.info(
        "**Где хранятся слои памяти**\n\n"
        "- **Краткосрочная** — SQLite-таблица `short_term`: `owner_id` + `session_id`, "
        "TTL 24 ч, лимит 24 сообщения, в промт — последние 8.\n"
        "- **Рабочая** — SQLite-таблица `working`: `owner_id` + `session_id`, TTL 72 ч.\n"
        "- **Долговременная** — SQLite-таблица `long_term` + FTS5 `long_term_fts`; "
        "история изменений — `long_term_history`, поля `source`, `confidence`, `importance`.\n"
        "- **Промт** не хранится: собирается при каждом запросе из трёх слоёв.\n\n"
        "Все таблицы — в `/srv/data/memory.db`; в Docker это bind-mount `Lesson 11/app/data`."
    )


def _render_cards(state: dict) -> None:
    short = state["short_term"]
    working_count = sum(
        1
        for field in ("title", "goal", "status", "next_step", "constraints")
        if state["working"].get(field)
    )
    long_count = state["long_term"]["count"]
    st.html(
        '<div class="mem-grid">'
        + _card(
            "Краткосрочная",
            "Текущий диалог",
            f"{short['count']} / {short['limit']}",
            f"в запрос уходят последние {short['prompt_window']}",
            "mem-short",
        )
        + _card(
            "Рабочая",
            "Данные текущей задачи",
            str(working_count),
            "цель, статус, следующий шаг, ограничения",
            "mem-working",
        )
        + _card(
            "Долговременная",
            "Профиль, решения, знания",
            str(long_count),
            "переживает перезапуск и очистку диалога",
            "mem-long",
        )
        + "</div>"
    )


def _render_short(state: dict) -> None:
    short = state["short_term"]
    st.markdown("#### Краткосрочная память")
    st.caption(
        f"Лимит — {short['limit']} сообщения. В контекст модели уходят последние "
        f"{short['prompt_window']}."
    )
    if short["messages"]:
        tail = [
            f"{'🧑' if item['role'] == 'user' else '🤖'} {_short(item['content'], 52)}"
            for item in short["messages"][-2:]
        ]
        unit = "сообщение" if short["count"] == 1 else "сообщений"
        _snapshot([f"{short['count']} {unit}", *tail])
    else:
        _snapshot([])
    with st.container(height=330, border=True):
        if not short["messages"]:
            st.info("Пока пусто. Напишите сообщение — оно станет частью текущего диалога.")
        for item in short["messages"]:
            with st.chat_message(
                item["role"], avatar="🧑" if item["role"] == "user" else "🤖"
            ):
                st.markdown(item["content"])
                if item["role"] == "assistant" and (
                    item.get("prompt_tokens") or item.get("completion_tokens")
                ):
                    st.caption(
                        f"Промт запроса: {_num(int(item.get('prompt_tokens') or 0))} токенов · "
                        f"Промт ответа: {_num(int(item.get('completion_tokens') or 0))} токенов · "
                        f"{item['created_at'].replace('T', ' ')[:16]}"
                    )
                else:
                    st.caption(
                        f"Реплика: {_num(item['tokens'])} токенов · "
                        f"{item['created_at'].replace('T', ' ')[:16]}"
                    )

    last_context = st.session_state.get("l11_last_context")
    if last_context:
        _render_prompt_breakdown(
            last_context, st.session_state.get("l11_last_state") or state
        )

    try:
        initial_context = _get(
            "/api/context", params={"session_id": SESSION_ID, "owner_id": "demo"}
        )
    except Exception:  # noqa: BLE001
        initial_context = {}
    retrieved = initial_context.get("retrieved") or []

    if st.session_state.pop("l11_reset_message", False):
        st.session_state["l11_message"] = _default_prompt(state, retrieved)
    if "l11_message" not in st.session_state:
        st.session_state["l11_message"] = _default_prompt(state, retrieved)

    with st.form("l11_chat_form", clear_on_submit=False):
        message = st.text_area(
            "Сообщение ассистенту",
            height=150,
            key="l11_message",
            placeholder="Например: что ты помнишь о текущей задаче?",
            help="Промт предзаполнен по трём слоям памяти, но не отправляется автоматически.",
        )
        send_col, enrich_col = st.columns(2)
        submitted = send_col.form_submit_button("Отправить", use_container_width=True)
        enrich_short = enrich_col.form_submit_button(
            "Обогатить краткосрочную", use_container_width=True
        )
    st.caption(
        "«Отправить» — запрос к модели; «Обогатить краткосрочную» — сохранить "
        "реплику в текущий диалог без вызова модели."
    )
    if submitted and message.strip():
        with st.spinner("Ассистент собирает три слоя памяти…"):
            try:
                result = _post(
                    "/api/chat",
                    {"session_id": SESSION_ID, "message": message.strip()},
                )
                st.session_state["l11_last_context"] = result.get("context") or {}
                st.session_state["l11_last_state"] = result.get("state") or state
                st.session_state["l11_reset_message"] = True
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Не удалось получить ответ: {type(exc).__name__}: {exc}")
    if enrich_short and message.strip():
        try:
            _post(
                "/api/message",
                {
                    "session_id": SESSION_ID,
                    "role": "user",
                    "content": message.strip(),
                },
            )
            _invalidate()
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Не удалось сохранить реплику: {type(exc).__name__}: {exc}")

    if st.button("Вернуть дефолтный промт", key="l11_default_prompt"):
        st.session_state["l11_reset_message"] = True
        st.rerun()

    if st.button("Сбросить краткосрочную память", key="l11_clear_short"):
        _invalidate()
        _delete("/api/short-term", params={"session_id": SESSION_ID})
        _refresh()


def _render_working(state: dict) -> None:
    task = state["working"]
    st.markdown("#### Рабочая память")
    st.caption(
        "Данные текущей задачи. Они не являются профилем пользователя и "
        "очищаются отдельно от долговременной памяти."
    )
    _snapshot(
        [
            f"задача «{_short(task.get('title'), 48)}»" if task.get("title") else "",
            f"статус «{_short(task.get('status'), 32)}»" if task.get("status") else "",
            f"шаг: {_short(task.get('next_step'), 48)}" if task.get("next_step") else "",
        ]
    )
    statuses = ["Не начата", "В работе", "Почти готово", "Заблокирована", "Готово"]
    if task.get("status") and task["status"] not in statuses:
        statuses.append(task["status"])
    with st.form("l11_working_form"):
        title = st.text_input("Задача", value=task.get("title", ""), key="l11_w_title")
        goal = st.text_area("Цель", value=task.get("goal", ""), key="l11_w_goal")
        col_status, col_next = st.columns(2)
        with col_status:
            status = st.selectbox(
                "Статус",
                options=statuses,
                index=statuses.index(task.get("status") or "Не начата"),
                key="l11_w_status",
            )
        with col_next:
            next_step = st.text_input(
                "Следующий шаг", value=task.get("next_step", ""), key="l11_w_next"
            )
        constraints = st.text_area(
            "Ограничения", value=task.get("constraints", ""), key="l11_w_constraints"
        )
        saved = st.form_submit_button("Обогатить рабочую память", use_container_width=True)
    if saved:
        _post(
            "/api/working",
            {
                "session_id": SESSION_ID,
                "title": title,
                "goal": goal,
                "status": status,
                "next_step": next_step,
                "constraints": constraints,
            },
        )
        _invalidate()
        _refresh()

    if task.get("updated_at"):
        st.caption(f"Обновлено: {task['updated_at']}")
    if st.button("Сбросить рабочую память", key="l11_clear_working"):
        _invalidate()
        _delete("/api/working", params={"session_id": SESSION_ID})
        _refresh()


def _long_table(items: list[dict]) -> None:
    if not items:
        st.caption("Раздел пока пуст.")
        return
    st.dataframe(
        [
            {
                "Ключ": item["key"],
                "Значение": item["value"],
                "Источник": item["source"],
                "Уверенность": f"{float(item.get('confidence', 0.5)):.1f}",
                "Обновлено": item["updated_at"],
            }
            for item in items
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_long(state: dict) -> None:
    long_term = state["long_term"]
    st.markdown("#### Долговременная память")
    st.caption(
        "Устойчивые факты, решения и знания. Эти записи сохраняются в SQLite "
        "и не удаляются при очистке краткосрочной или рабочей памяти."
    )
    labels = {"profile": "Профиль", "decisions": "Решения", "knowledge": "Знания"}
    def keys(items: list[dict], limit: int = 3) -> str:
        names = [item["key"] for item in items[:limit]]
        more = f" +{len(items) - limit}" if len(items) > limit else ""
        return f" ({', '.join(names)}{more})" if names else ""

    _snapshot(
        [
            f"профиль {len(long_term.get('profile') or [])}"
            + keys(long_term.get("profile") or []),
            f"решения {len(long_term.get('decisions') or [])}"
            + keys(long_term.get("decisions") or []),
            f"знания {len(long_term.get('knowledge') or [])}"
            + keys(long_term.get("knowledge") or []),
            f"всего {long_term.get('count', 0)}",
        ]
    )
    tabs = st.tabs([labels[key] for key in labels])
    for tab, section in zip(tabs, labels):
        with tab:
            _long_table(long_term.get(section) or [])

    st.markdown("##### Добавить или обновить запись")
    with st.form("l11_long_form", clear_on_submit=True):
        section = st.selectbox(
            "Раздел",
            options=list(labels),
            format_func=lambda value: labels[value],
            key="l11_long_section",
        )
        key = st.text_input("Ключ", placeholder="Например: Город", key="l11_long_key")
        value = st.text_area(
            "Значение",
            placeholder="Например: Москва",
            key="l11_long_value",
        )
        source = st.text_input(
            "Источник", value="пользователь", key="l11_long_source"
        )
        confidence = st.slider(
            "Уверенность",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.1,
            key="l11_long_confidence",
            help="Насколько факту можно доверять: 1.0 — подтверждён пользователем.",
        )
        submitted = st.form_submit_button("Обогатить долговременную память", use_container_width=True)
    if submitted:
        if not key.strip() or not value.strip():
            st.warning("Заполните ключ и значение.")
        else:
            _post(
                "/api/long-term",
                {
                    "section": section,
                    "key": key.strip(),
                    "value": value.strip(),
                    "source": source.strip() or "пользователь",
                    "confidence": float(confidence),
                },
            )
            _invalidate()
            _refresh()

    all_items = long_term["items"]
    if all_items:
        choices = {
            f"{labels[item['section']]} · {item['key']}": item["id"]
            for item in all_items
        }
        selected = st.selectbox(
            "Удалить запись", options=list(choices), key="l11_long_delete"
        )
        if st.button("Удалить выбранную запись", key="l11_long_delete_button"):
            _delete(f"/api/long-term/{choices[selected]}")
            _invalidate()
            _refresh()


def _demo_seed() -> dict:
    """Заполнить изолированную демо-сессию всеми тремя слоями."""
    _post(
        "/api/chat/reset",
        {"session_id": DEMO_SESSION, "owner_id": DEMO_OWNER},
    )
    records = [
        ("profile", "Имя", "Борис", "демо-сценарий", 0.95),
        ("profile", "Роль", "Разработчик", "демо-сценарий", 0.9),
        ("decisions", "Провайдер", "OpenCode Go", "демо-сценарий", 0.95),
        ("knowledge", "Проект", "AI Challenge", "демо-сценарий", 0.9),
    ]
    for section, key, value, source, confidence in records:
        _post(
            "/api/long-term",
            {
                "owner_id": DEMO_OWNER,
                "section": section,
                "key": key,
                "value": value,
                "source": source,
                "confidence": confidence,
            },
        )
    _post(
        "/api/working",
        {
            "session_id": DEMO_SESSION,
            "owner_id": DEMO_OWNER,
            "title": "Наглядная проверка памяти",
            "goal": "Показать вклад краткосрочной, рабочей и долговременной памяти",
            "status": "В работе",
            "next_step": "Задать вопрос по всем трём слоям",
            "constraints": "Не смешивать демо-данные с основной сессией",
        },
    )
    _post(
        "/api/message",
        {
            "session_id": DEMO_SESSION,
            "owner_id": DEMO_OWNER,
            "role": "user",
            "content": "Мы готовим наглядную проверку трёх слоёв памяти.",
        },
    )
    _post(
        "/api/message",
        {
            "session_id": DEMO_SESSION,
            "owner_id": DEMO_OWNER,
            "role": "assistant",
            "content": "Понял: покажу профиль, текущую задачу и последние сообщения.",
        },
    )
    return _get(
        "/api/state",
        params={"session_id": DEMO_SESSION, "owner_id": DEMO_OWNER},
    )


def _demo_ask(question: str) -> dict:
    return _post(
        "/api/chat",
        {
            "session_id": DEMO_SESSION,
            "owner_id": DEMO_OWNER,
            "message": question,
        },
    )


def _html_demo_table(rows: list[dict]) -> None:
    headers = list(rows[0]) if rows else []
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row.get(header, '')))}</td>" for header in headers) + "</tr>"
        for row in rows
    )
    st.markdown(
        f'<table class="demo-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>',
        unsafe_allow_html=True,
    )


def _prompt_preview(text: str, limit: int = 700) -> str:
    """Компактный, но реальный фрагмент system prompt для показа."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:180].rstrip()
    tail = text[-(limit - 180):].lstrip()
    return f"{head}\n…\n{tail}"


def _demo_trace(result: dict, caption: str) -> None:
    """Показать, что именно каждый слой дал в prompt и ответ."""
    context = result.get("context") or {}
    state = result.get("state") or {}
    layers = context.get("layers") or {}
    short_messages = (state.get("short_term") or {}).get("messages") or []
    working = state.get("working") or {}
    retrieved = context.get("retrieved") or []
    window = int(context.get("short_window") or 8)
    recent = short_messages[-window:]

    working_items = [
        f"{label}: {working[field]}"
        for field, label in (
            ("title", "Задача"),
            ("goal", "Цель"),
            ("status", "Статус"),
            ("next_step", "Следующий шаг"),
            ("constraints", "Ограничения"),
        )
        if working.get(field)
    ]
    long_keys: dict[str, list[str]] = {}
    for item in retrieved:
        long_keys.setdefault(item.get("section", ""), []).append(item["key"])

    def section_text() -> str:
        parts = []
        for section, label in (
            ("profile", "профиль"),
            ("decisions", "решения"),
            ("knowledge", "знания"),
        ):
            names = long_keys.get(section) or []
            if names:
                parts.append(f"{label}: {', '.join(names[:3])}")
        return "; ".join(parts) or "—"

    showcase = st.query_params.get("showcase") == "1"
    width = 70 if showcase else 100
    rows = [
        {
            "Слой": "Краткосрочная",
            "Статус": "есть" if recent else "пусто",
            "Что попало": _short(
                "; ".join(
                    f"{'пользователь' if item['role'] == 'user' else 'ассистент'}: {item['content']}"
                    for item in recent[-3:]
                )
                or "—",
                width,
            ),
            "Токены": layers.get("short_term", {}).get("tokens", 0),
        },
        {
            "Слой": "Рабочая",
            "Статус": "есть" if working_items else "пусто",
            "Что попало": _short("; ".join(working_items) or "—", width),
            "Токены": layers.get("working", {}).get("tokens", 0),
        },
        {
            "Слой": "Долговременная",
            "Статус": "есть" if retrieved else "пусто",
            "Что попало": _short(section_text(), width),
            "Токены": layers.get("long_term", {}).get("tokens", 0),
        },
    ]
    st.markdown(f"##### {caption}")
    st.caption(
        f"Промт запроса: {_num(int(result.get('request_tokens') or 0))} токенов · "
        f"Промт ответа: {_num(int(result.get('response_tokens') or 0))} токенов"
    )
    if showcase:
        _html_demo_table(rows)
    else:
        st.table(rows)

    question = result.get("question") or "—"
    answer = result.get("answer") or "—"
    prompt = context.get("system_prompt") or "—"
    if showcase:
        chat_col, prompt_col = st.columns([1.0, 1.1])
        with chat_col:
            st.markdown("**Чат**")
            with st.chat_message("user", avatar="🧑"):
                st.markdown(question)
            if len(answer) > 420:
                answer = answer[:420].rsplit(" ", 1)[0] + " …"
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(answer)
            st.caption("Ответ получен от модели")
        with prompt_col:
            st.markdown("**Промт отправлен**")
            st.code(_prompt_preview(prompt), language="text")
    else:
        with st.chat_message("user", avatar="🧑"):
            st.markdown(question)
        with st.expander("Промт, который отправлен", expanded=False):
            st.code(prompt, language="text")
        with st.chat_message("assistant", avatar="🤖"):
            st.markdown(answer)


def _demo_clear_long() -> int:
    """Удалить все долговременные записи только демо-владельца."""
    state = _get(
        "/api/state",
        params={"session_id": DEMO_SESSION, "owner_id": DEMO_OWNER},
    )
    items = (state.get("long_term") or {}).get("items") or []
    for item in items:
        _delete(f"/api/long-term/{item['id']}", params={"owner_id": DEMO_OWNER})
    return len(items)


def _layer_counts(result: dict) -> tuple[int, int, int]:
    layers = (result.get("context") or {}).get("layers") or {}
    short = int((layers.get("short_term") or {}).get("count") or 0)
    working = int((layers.get("working") or {}).get("count") or 0)
    long_term = int((layers.get("long_term") or {}).get("count") or 0)
    return short, working, long_term


def _run_ablation(question: str) -> list[dict]:
    """По очереди удалить каждый слой и задать тот же вопрос."""
    variants = []
    for key, label in (
        ("short", "Без краткосрочной"),
        ("working", "Без рабочей"),
        ("long", "Без долговременной"),
    ):
        _demo_seed()
        if key == "short":
            _delete(
                "/api/short-term",
                params={"session_id": DEMO_SESSION, "owner_id": DEMO_OWNER},
            )
        elif key == "working":
            _delete(
                "/api/working",
                params={"session_id": DEMO_SESSION, "owner_id": DEMO_OWNER},
            )
        else:
            _demo_clear_long()
        variants.append({"key": key, "label": label, "result": _demo_ask(question)})
    return variants


def _render_ablation(baseline: dict, variants: list[dict]) -> None:
    st.markdown("### Шаг 3 · Удаление слоёв по одному")
    st.caption(
        "Шаг выполняется сразу после первого: для каждого слоя демо-сессия "
        "восстанавливается, удаляется только он и задаётся тот же вопрос. "
        "Так видно отдельный вклад краткосрочной, рабочей и долговременной памяти."
    )

    base_req = int(baseline.get("request_tokens") or 0)
    base_resp = int(baseline.get("response_tokens") or 0)
    rows = [
        {
            "Вариант": "Все три слоя",
            "Удалён": "—",
            "Осталось К/Р/Д": "%d / %d / %d" % _layer_counts(baseline),
            "Запрос": base_req,
            "Δ запроса": "—",
            "Ответ": base_resp,
            "Δ ответа": "—",
        }
    ]
    effects = {
        "short": "Пропадает история диалога: ответ не знает предыдущих реплик и договорённостей; текущий вопрос остаётся.",
        "working": "Пропадает задача, цель, статус и следующий шаг: ответ не знает, что делается сейчас.",
        "long": "Пропадают профиль, решения и знания: ответ не знает пользователя, проект и принятые решения.",
    }
    for item in variants:
        result = item["result"]
        req = int(result.get("request_tokens") or 0)
        resp = int(result.get("response_tokens") or 0)
        rows.append(
            {
                "Вариант": item["label"],
                "Удалён": {
                    "short": "краткосрочная",
                    "working": "рабочая",
                    "long": "долговременная",
                }[item["key"]],
                "Осталось К/Р/Д": "%d / %d / %d" % _layer_counts(result),
                "Запрос": req,
                "Δ запроса": f"{req - base_req:+d}",
                "Ответ": resp,
                "Δ ответа": f"{resp - base_resp:+d}",
            }
        )

    st.success("Анализ удаления выполнен: каждый слой проверен отдельно.")
    st.table(rows)
    st.markdown("#### На что влияет удаление слоя")
    for item in variants:
        st.markdown(f"- **{item['label']}** — {effects[item['key']]}")
    st.caption(
        "К/Р/Д — сколько записей осталось в краткосрочной / рабочей / долговременной "
        "памяти после удаления. Δ — разница с вариантом «Все три слоя»."
    )
    for item in variants:
        with st.expander(f"Ответ модели: {item['label']}", expanded=False):
            answer = (item["result"].get("answer") or "—").strip()
            if len(answer) > 900:
                answer = answer[:900].rsplit(" ", 1)[0] + " …"
            st.markdown(answer)


def _render_demo(state: dict) -> None:
    showcase = st.query_params.get("showcase") == "1"
    if showcase:
        st.markdown("## Проверка памяти: три слоя")
        st.caption(
            "Изолированная демо-сессия: все три слоя → вопрос → поочерёдное удаление "
            "краткосрочной, рабочей и долговременной памяти."
        )
    else:
        st.markdown("#### Наглядная проверка трёх слоёв")
        st.caption(
            "Демо использует отдельного владельца `demo-check`, поэтому не смешивается "
            "с основной сессией `demo`. Сначала вопрос при всех трёх слоях, затем "
            "поочерёдное удаление каждого слоя и сравнение ответов."
        )
    if st.button(
        "▶ Запустить последовательную проверку",
        type="primary",
        use_container_width=True,
        key="l11_run_demo",
    ):
        with st.spinner("Заполняю слои, задаю вопрос и поочерёдно удаляю слои…"):
            try:
                question = (
                    "Кратко: что ты знаешь обо мне, какая сейчас задача и о чём мы говорили? "
                    "Ответь тремя пунктами: «Долговременная: …», «Рабочая: …», "
                    "«Краткосрочная: …»."
                )
                _demo_seed()
                first = _demo_ask(question)
                variants = _run_ablation(question)
                st.session_state["l11_demo_result"] = {
                    "first": first,
                    "variants": variants,
                }
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Проверка не запустилась: {type(exc).__name__}: {exc}")

    result = st.session_state.get("l11_demo_result")
    if not result:
        return

    st.success("Шаги 1 и 3 выполнены последовательно.")
    _demo_trace(result["first"], "Шаг 1 · Вопрос при всех трёх слоях")
    st.info("Переходим к шагу 3: удаляем каждый слой по очереди и сравниваем ответы.")
    _render_ablation(result["first"], result["variants"])


def _render_context(state: dict) -> None:
    st.markdown("#### Что реально уходит модели")
    st.caption(
        "Один system prompt собирается из долговременной и рабочей памяти, "
        "а затем к нему добавляются последние сообщения краткосрочной."
    )
    try:
        last_user = next(
            (
                item["content"]
                for item in reversed(state["short_term"]["messages"])
                if item["role"] == "user"
            ),
            "",
        )
        params = {"session_id": SESSION_ID, "owner_id": "demo"}
        if last_user:
            params["q"] = last_user
        context = _get("/api/context", params=params)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось собрать контекст: {type(exc).__name__}: {exc}")
        return

    layers = context["layers"]
    retrieved_count = layers["long_term"]["count"]
    available = layers["long_term"].get("available", retrieved_count)
    st.caption(
        f"Релевантная выборка долговременной памяти: {retrieved_count} из {available}. "
        "Профиль добавляется всегда; остальное — по запросу, confidence и свежести."
    )
    st.markdown(
        f"Краткосрочная: **{_num(layers['short_term']['count'])}** · "
        f"рабочая: **{_num(layers['working']['count'])}** полей · "
        f"долговременная: **{_num(retrieved_count)}** из **{_num(available)}** записей · "
        f"токенов: **{_num(context['total_tokens'])}**"
    )
    with st.expander("System prompt с тремя слоями памяти", expanded=True):
        st.code(context["system_prompt"], language="text")

    st.markdown("##### Сообщения, которые уйдут вместе с контекстом")
    dialogue = context["messages"][1:]
    if not dialogue:
        st.info("Сообщений пока нет.")
    for item in dialogue:
        with st.chat_message(
            item["role"], avatar="🧑" if item["role"] == "user" else "🤖"
        ):
            st.markdown(item["content"])
    st.button("Обновить контекст", key="l11_refresh_context", on_click=_refresh)


def render() -> None:
    showcase = st.query_params.get("showcase") == "1"
    st.markdown(
        """
        <style>
        .mem-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: .6rem; margin: .4rem 0 .9rem 0; }
        .mem-card { border: 1px solid rgba(128,128,128,.24); border-radius: .6rem;
                    padding: .7rem .8rem; background: rgba(128,128,128,.045); }
        .mem-card-top { display: flex; justify-content: space-between; gap: .5rem;
                        align-items: baseline; font-size: .88rem; font-weight: 600; }
        .mem-card-top b { font-size: 1.25rem; color: #ffb268; }
        .mem-card-sub { font-size: .76rem; opacity: .7; margin-top: .1rem; }
        .mem-card-hint { font-size: .7rem; opacity: .45; margin-top: .35rem; line-height: 1.35; }
        .mem-short { border-left: 3px solid #6ea8fe; }
        .mem-working { border-left: 3px solid #ffb268; }
        .mem-long { border-left: 3px solid #9b8cff; }
        .demo-table { width: 100%; border-collapse: collapse; margin: .35rem 0 .8rem;
                      font-size: .92rem; }
        .demo-table th { text-align: left; font-size: .76rem; text-transform: uppercase;
                         letter-spacing: .04em; opacity: .55; padding: .45rem .55rem;
                         border-bottom: 1px solid rgba(128,128,128,.3); }
        .demo-table td { padding: .55rem .55rem; border-bottom: 1px solid rgba(128,128,128,.16);
                         vertical-align: top; }
        .demo-table td:first-child { font-weight: 600; white-space: nowrap; }
        .demo-table td:last-child { text-align: right; white-space: nowrap; }
        /* Режим показа: только сценарий проверки, без навигации и лишнего текста. */
        body:has([data-testid="stSidebar"]) .l11-showcase [data-testid="stSidebar"],
        .l11-showcase [data-testid="stSidebar"],
        .l11-showcase [data-testid="stHeader"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if showcase:
        st.markdown('<div class="l11-showcase"></div>', unsafe_allow_html=True)
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"], [data-testid="stHeader"] { display: none !important; }
            .block-container { max-width: 1360px; padding-top: .9rem; }
            body { zoom: 1.08; }
            .stMarkdown, .stChatMessage { font-size: 1.06rem; }
            [data-testid="stMetricValue"] { font-size: 1.9rem; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.title("Урок 11 · Модель памяти ассистента")
        st.caption(
            "Три слоя памяти: краткосрочная — текущий диалог; рабочая — данные текущей "
            "задачи; долговременная — профиль, решения и знания."
        )
    try:
        state = _get("/api/state", params={"session_id": SESSION_ID})
    except Exception as exc:  # noqa: BLE001
        st.error(f"API урока 11 недоступен: {type(exc).__name__}: {exc}")
        return

    if showcase:
        _render_storage_info()
        _render_demo(state)
        return
    _render_cards(state)
    _render_storage_info()

    with st.sidebar:
        st.divider()
        st.markdown("### Урок 11")
        st.caption("Модель памяти · сессия `demo`")
        st.caption(
            f"Краткосрочная: {state['short_term']['count']} / "
            f"{state['short_term']['limit']}\n\n"
            f"Рабочая: {sum(1 for f in ('title', 'goal', 'status', 'next_step', 'constraints') if state['working'].get(f))}\n\n"
            f"Долговременная: {state['long_term']['count']}"
        )
        if st.button("Сбросить диалог и задачу", use_container_width=True):
            _post("/api/chat/reset", {"session_id": SESSION_ID})
            _invalidate()
            _refresh()
        st.caption("Долговременная память при сбросе сохраняется.")

    tabs = st.tabs(
        [
            "💬 Краткосрочная",
            "🗂 Рабочая",
            "🧠 Долговременная",
            "🔍 Контекст",
            "🧪 Проверка",
        ]
    )
    with tabs[0]:
        _render_short(state)
    with tabs[1]:
        _render_working(state)
    with tabs[2]:
        _render_long(state)
    with tabs[3]:
        _render_context(state)
    with tabs[4]:
        _render_demo(state)
