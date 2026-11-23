"""Страница урока 12: персонализация ассистента."""

from __future__ import annotations

import secrets

import httpx
import streamlit as st

from common import LESSON_12_API

DEFAULT_OWNER = "demo"
SESSION_ID = "demo"
NO_CACHE = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
PROFILE_LABELS = {
    "name": "Имя",
    "role": "Роль",
    "city": "Город",
    "language": "Язык",
    "timezone": "Часовой пояс",
}
PREFERENCE_LABELS = {
    "style": "Стиль общения",
    "format": "Формат ответа",
    "code_examples": "Примеры кода",
    "emoji": "Emoji",
    "constraints": "Ограничения",
}


def _get(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30.0, headers=NO_CACHE) as client:
        response = client.get(f"{LESSON_12_API}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _post(path: str, payload: dict, timeout: float = 180.0) -> dict:
    with httpx.Client(timeout=timeout, headers=NO_CACHE) as client:
        response = client.post(f"{LESSON_12_API}{path}", json=payload)
    response.raise_for_status()
    return response.json()


def _delete(path: str, params: dict | None = None) -> dict:
    with httpx.Client(timeout=30.0, headers=NO_CACHE) as client:
        response = client.delete(f"{LESSON_12_API}{path}", params=params)
    response.raise_for_status()
    return response.json()


def _short(text: str, limit: int = 120) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _owner() -> str:
    return st.session_state.get("l12_owner") or DEFAULT_OWNER


def _profile_label(profile: dict) -> str:
    name = profile.get("name") or profile.get("owner_id") or "Без имени"
    role = profile.get("role") or "профиль"
    return f"{name} · {role}"


def _audit_text(item: dict) -> str:
    audit = item.get("audit") or {}
    checks = audit.get("checks") or {}
    if not checks:
        return "Аудит: нет проверяемых предпочтений"
    parts = []
    for key, check in checks.items():
        label = PREFERENCE_LABELS.get(key, key)
        parts.append(f"{label}: {'✅' if check.get('passed') else '⚠️'}")
    return "Аудит: " + " · ".join(parts)


def _check_session() -> str:
    if "l12_check_session" not in st.session_state:
        st.session_state["l12_check_session"] = secrets.token_hex(8)
    return st.session_state["l12_check_session"]


def _clear_check_results() -> None:
    for key in (
        "l12_check_question",
        "l12_check_all",
        "l12_check_batch",
        "l12_check_analysis",
    ):
        st.session_state.pop(key, None)


def _render_sidebar() -> None:
    with st.sidebar:
        st.divider()
        st.markdown("### Профили урока 12")
        try:
            profiles = _get("/api/profiles").get("profiles") or []
        except Exception as exc:  # noqa: BLE001
            st.caption(f"Список профилей недоступен: {type(exc).__name__}")
            return
        ids = [item["owner_id"] for item in profiles]
        if not ids:
            st.warning("Профилей нет. Создайте профиль на вкладке «Профиль».")
            return
        if st.session_state.get("l12_owner") not in ids:
            st.session_state["l12_owner"] = (
                DEFAULT_OWNER if DEFAULT_OWNER in ids else ids[0]
            )
        current = _owner()
        labels = {item["owner_id"]: _profile_label(item) for item in profiles}

        selected = st.selectbox(
            "Текущий профиль",
            options=ids,
            index=ids.index(current),
            format_func=lambda owner_id: labels.get(owner_id, owner_id),
            key="l12_profile_switch",
        )
        if selected != current:
            st.session_state["l12_owner"] = selected
            st.session_state.pop("l12_last_result", None)
            _clear_check_results()
            st.rerun()

        st.caption(
            f"Профилей: **{len(ids)}** · текущий: `{current}`\n\n"
            "Профиль подключается к каждому запросу."
        )
        with st.expander("Удалить профиль"):
            if len(ids) <= 1:
                st.caption("Нельзя удалить единственный профиль.")
            else:
                confirmed = st.checkbox(
                    "Подтвердить удаление",
                    key=f"l12_delete_confirm_{current}",
                )
                if st.button(
                    "Удалить текущий профиль",
                    disabled=not confirmed,
                    key=f"l12_delete_button_{current}",
                ):
                    result = _delete("/api/profile", params={"owner_id": current})
                    remaining = result.get("profiles") or []
                    st.session_state["l12_owner"] = (
                        remaining[0]["owner_id"] if remaining else DEFAULT_OWNER
                    )
                    st.session_state.pop("l12_last_result", None)
                    _clear_check_results()
                    st.session_state["l12_notice"] = "Профиль удалён."
                    st.rerun()


def _profile_values(profile: dict) -> dict[str, str]:
    return {field: profile.get(field, "") or "" for field in PROFILE_LABELS}


def _render_profile_tab(state: dict) -> None:
    profile = state.get("profile") or {}
    owner = _owner()
    st.markdown("#### Профиль пользователя")
    st.info(
        "Профиль хранится в SQLite и добавляется в system prompt каждого запроса. "
        "Поля можно заполнить вручную или дать ассистенту сведения в чате."
    )
    values = _profile_values(profile)
    with st.form(f"l12_profile_form_{owner}"):
        left, right = st.columns(2)
        with left:
            name = st.text_input(
                "Имя", value=values["name"], key=f"l12_name_{owner}"
            )
            role = st.text_input(
                "Роль", value=values["role"], key=f"l12_role_{owner}"
            )
            city = st.text_input(
                "Город", value=values["city"], key=f"l12_city_{owner}"
            )
        with right:
            language = st.text_input(
                "Язык", value=values["language"], key=f"l12_language_{owner}"
            )
            timezone = st.text_input(
                "Часовой пояс", value=values["timezone"], key=f"l12_timezone_{owner}"
            )
        saved = st.form_submit_button("Сохранить профиль", use_container_width=True)
    if saved:
        _post(
            "/api/profile",
            {
                "owner_id": owner,
                "name": name,
                "role": role,
                "city": city,
                "language": language,
                "timezone": timezone,
            },
        )
        st.session_state["l12_notice"] = "Профиль сохранён и будет подключён к следующему запросу."
        st.rerun()

    if profile.get("updated_at"):
        st.caption(f"Обновлён: {profile['updated_at']}")
    st.caption(
        "Профиль не является инструкцией: ассистент использует его как данные о вас."
    )


def _render_preferences_tab(state: dict) -> None:
    preferences = state.get("preferences") or []
    owner = _owner()
    st.markdown("#### Предпочтения")
    st.caption(
        "Стиль, формат, примеры кода, emoji и ограничения. Эти значения попадают в каждый запрос; "
        "источник «диалог» означает автоматическое обновление из реплики."
    )
    if preferences:
        st.table(
            [
                {
                    "Предпочтение": PREFERENCE_LABELS.get(item["key"], item["key"]),
                    "Значение": item["value"],
                    "Источник": item.get("source", "—"),
                    "Уверенность": f"{float(item.get('confidence', 0.8)):.1f}",
                }
                for item in preferences
            ]
        )
    else:
        st.info("Предпочтения пока не заданы.")

    with st.form(f"l12_preference_form_{owner}"):
        key = st.selectbox(
            "Что настроить",
            options=list(PREFERENCE_LABELS),
            format_func=lambda value: PREFERENCE_LABELS[value],
            key=f"l12_pref_key_{owner}",
        )
        value = st.text_area(
            "Значение",
            placeholder="Например: кратко, списком, без emoji, обращение на «ты»",
            key=f"l12_pref_value_{owner}",
        )
        saved = st.form_submit_button("Сохранить предпочтение", use_container_width=True)
    if saved and value.strip():
        _post(
            "/api/preferences",
            {
                "owner_id": owner,
                "key": key,
                "value": value.strip(),
                "source": "пользователь",
                "confidence": 0.95,
            },
        )
        st.session_state["l12_notice"] = "Предпочтение сохранено."
        st.rerun()

    if preferences:
        choice = st.selectbox(
            "Удалить предпочтение",
            options=[item["key"] for item in preferences],
            format_func=lambda value: PREFERENCE_LABELS.get(value, value),
            key=f"l12_pref_delete_{owner}",
        )
        if st.button("Удалить выбранное", key=f"l12_pref_delete_button_{owner}"):
            _delete(f"/api/preferences/{choice}", params={"owner_id": owner})
            st.session_state["l12_notice"] = "Предпочтение удалено."
            st.rerun()


def _render_chat_tab(state: dict) -> None:
    owner = _owner()
    last_key = f"l12_last_result_{owner}"
    st.markdown("#### Чат с профилем")
    st.caption(
        "Каждое сообщение проходит через профиль: сначала обновляются факты, "
        "затем system prompt собирается заново и уходит модели."
    )
    try:
        context = _get(
            "/api/context",
            params={"owner_id": owner, "session_id": SESSION_ID},
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить контекст: {type(exc).__name__}: {exc}")
        return

    history = context.get("messages", [])[1:]
    with st.container(height=320, border=True):
        if not history:
            st.info("История пуста. Напишите сообщение — профиль подключится автоматически.")
        for item in history:
            with st.chat_message(
                item["role"], avatar="🧑" if item["role"] == "user" else "🤖"
            ):
                st.markdown(item["content"])

    with st.form(f"l12_chat_form_{owner}", clear_on_submit=True):
        message = st.text_area(
            "Сообщение ассистенту",
            height=110,
            placeholder="Например: Меня зовут Борис, отвечай кратко и без emoji.",
            key=f"l12_message_{owner}",
        )
        submitted = st.form_submit_button("Отправить", use_container_width=True)
    if submitted and message.strip():
        with st.spinner("Обновляю профиль и собираю персональный запрос…"):
            try:
                result = _post(
                    "/api/chat",
                    {
                        "owner_id": owner,
                        "session_id": SESSION_ID,
                        "message": message.strip(),
                    },
                )
                st.session_state[last_key] = result
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Не удалось получить ответ: {type(exc).__name__}: {exc}")

    result = st.session_state.get(last_key)
    if result:
        updates = result.get("updates") or []
        if updates:
            labels = [
                f"{PROFILE_LABELS.get(item['key'], PREFERENCE_LABELS.get(item['key'], item['key']))}: "
                f"{item['value']}"
                for item in updates
            ]
            st.success("Из диалога обновлено: " + "; ".join(labels))
        else:
            st.caption("Новых устойчивых фактов в последней реплике не найдено.")
        with st.expander("Профиль, который ушёл в последний запрос", expanded=False):
            st.code(result.get("context", {}).get("system_prompt", ""), language="text")
            st.caption(
                f"Промт запроса: {int(result.get('request_tokens') or 0)} токенов · "
                f"ответа: {int(result.get('response_tokens') or 0)} токенов"
            )

    if st.button("Очистить историю диалога", key=f"l12_clear_chat_{owner}"):
        _post("/api/chat/reset", {"owner_id": owner, "session_id": SESSION_ID})
        st.session_state.pop(last_key, None)
        st.rerun()


def _render_profile_check_tab(state: dict) -> None:
    """Проверка профилей: один вопрос всем и серия из 10 вопросов."""
    session = _check_session()
    st.markdown("#### Проверка профилей")
    st.info(
        "**Как устроена проверка.** Вопросы генерируются на сервере при каждом нажатии "
        "и не кешируются. Для каждой сессии создаётся отдельный `session_id`, поэтому "
        "вопросы разных сессий не совпадают. Анализ выполняет `deepseek-v4-pro` "
        "из подписки OpenCode Go. В серии из 10 вопросов темы подбираются под "
        "специализацию профиля; если общий вопрос выходит за границы роли, профиль "
        "обязан сказать об этом, а не выдумывать ответ."
    )
    try:
        profiles = _get("/api/profiles").get("profiles") or []
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить профили: {type(exc).__name__}: {exc}")
        return
    if not profiles:
        st.warning("Нет внесённых профилей. Сначала создайте или восстановите профиль.")
        return
    st.caption(
        f"В проверке участвуют все внесённые профили: **{len(profiles)}** · "
        f"сессия проверки: `{session}`"
    )

    with st.expander("Профили и их предпочтения", expanded=True):
        st.dataframe(
            [
                {
                    "Профиль": item.get("name") or item["owner_id"],
                    "Роль": item.get("role") or "—",
                    "Стиль": (item.get("preference_map") or {}).get("style", "—"),
                    "Формат": (item.get("preference_map") or {}).get("format", "—"),
                    "Код": (item.get("preference_map") or {}).get("code_examples", "—"),
                    "Emoji": (item.get("preference_map") or {}).get("emoji", "—"),
                }
                for item in profiles
            ],
            hide_index=True,
            use_container_width=True,
            height=245,
        )

    all_col, batch_col = st.columns(2)
    with all_col:
        make_all = st.button(
            "Сгенерировать вопрос для всех профилей",
            type="primary",
            use_container_width=True,
            key="l12_check_make_all",
        )
    with batch_col:
        make_batch = st.button(
            "10 случайных вопросов",
            use_container_width=True,
            key="l12_check_make_batch",
        )

    full_answers = st.checkbox(
        "Показывать все ответы полностью",
        value=False,
        key="l12_check_full_answers",
        help="Отключает компактную прокрутку внутри блока — все ответы идут подряд на странице.",
    )

    if make_all:
        with st.spinner("Генерирую новый вопрос и опрашиваю все профили…"):
            try:
                question = _post(
                    "/api/profile-check/question", {"session_id": session}
                )
                previous = (st.session_state.get("l12_check_question") or {}).get(
                    "question"
                )
                if previous and question.get("question") == previous:
                    # На всякий случай исключаем повтор предыдущего вопроса.
                    question = _post(
                        "/api/profile-check/question", {"session_id": session}
                    )
                result = _post(
                    "/api/profile-check/all",
                    {
                        "question": question["question"],
                        "question_id": question["question_id"],
                        "session_id": session,
                    },
                    timeout=300.0,
                )
                st.session_state["l12_check_question"] = question
                st.session_state["l12_check_all"] = result
                st.session_state.pop("l12_check_batch", None)
                st.session_state.pop("l12_check_analysis", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Проверка не выполнена: {type(exc).__name__}: {exc}")

    if make_batch:
        with st.spinner("Генерирую 10 случайных вопросов и опрашиваю профили…"):
            try:
                result = _post(
                    "/api/profile-check/batch",
                    {"session_id": session, "count": 10},
                    timeout=300.0,
                )
                st.session_state["l12_check_batch"] = result
                st.session_state.pop("l12_check_all", None)
                st.session_state.pop("l12_check_question", None)
                st.session_state.pop("l12_check_analysis", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Серия вопросов не выполнена: {type(exc).__name__}: {exc}")

    all_result = st.session_state.get("l12_check_all")
    if all_result:
        question = all_result.get("question") or ""
        st.markdown("##### Один вопрос — все профили")
        st.caption(
            f"Вопрос: `{all_result.get('question_id') or '—'}` · "
            f"профилей: {all_result.get('profiles_count', 0)} · без кеша"
        )
        if all_result.get("failed"):
            st.warning(
                f"Не ответили модели: {int(all_result['failed'])}. "
                "Ответы с пометкой `fallback` не учитывайте как результат профиля."
            )
        if all_result.get("code_missing"):
            st.warning(
                f"Без обязательного примера кода: {int(all_result['code_missing'])}. "
                "Проверьте профили с требованием «с примерами кода»."
            )
        if any(
            item.get("finish_reason") in {"length", "max_tokens"}
            for item in all_result.get("results") or []
        ):
            st.warning("Часть ответов всё ещё помечена как обрезанная по лимиту длины.")
        audit = all_result.get("audit") or {}
        stability = all_result.get("stability") or {}
        cols = st.columns(4)
        cols[0].metric(
            "Соблюдено ответов",
            f"{audit.get('compliant_answers', 0)} / {audit.get('answers', 0)}",
        )
        cols[1].metric(
            "Предпочтения",
            f"{audit.get('passed', 0)} / {audit.get('checked', 0)}",
        )
        cols[2].metric(
            "Первое нарушение",
            f"№{audit['first_violation']}" if audit.get("first_violation") else "нет",
        )
        cols[3].metric(
            "Устойчивость", "OK" if stability.get("unchanged", True) else "изменена"
        )
        if audit.get("first_violation"):
            st.warning(
                "Первое нарушение предпочтений: ответ "
                f"№{audit['first_violation']}."
            )
        st.caption(
            "Устойчивость после ответов: профили "
            f"{stability.get('profiles_before', 0)}/{stability.get('profiles_after', 0)}, "
            "предпочтения "
            f"{stability.get('preferences_before', 0)}/{stability.get('preferences_after', 0)}."
        )
        with st.chat_message("user", avatar="❓"):
            st.markdown(question)
        with (
            st.container(border=True)
            if full_answers
            else st.container(height=520, border=True)
        ):
            for item in all_result.get("results") or []:
                with st.chat_message("assistant", avatar="🧑‍💻"):
                    st.markdown(
                        f"**{item.get('name') or item.get('owner_id')}** · "
                        f"{item.get('role') or 'профиль'}"
                    )
                    prefs = item.get("preferences") or {}
                    if prefs:
                        st.caption(
                            " · ".join(
                                f"{PREFERENCE_LABELS.get(key, key)}: {value}"
                                for key, value in prefs.items()
                            )
                        )
                    st.caption(_audit_text(item))
                    st.markdown(item.get("answer") or "")
                    st.caption(
                        f"Модель: `{item.get('model', '—')}` · "
                        f"промт: {int(item.get('request_tokens') or 0)} токенов · "
                        f"ответ: {int(item.get('response_tokens') or 0)} токенов"
                    )

    batch_result = st.session_state.get("l12_check_batch")
    if batch_result:
        items = batch_result.get("results") or []
        st.markdown("##### 10 случайных вопросов · разные профили")
        st.caption(
            f"Вопросов: {batch_result.get('count', len(items))} · "
            f"задействовано профилей: {batch_result.get('profiles_count', 0)} · без кеша"
        )
        if batch_result.get("failed"):
            st.warning(
                f"Не ответили модели: {int(batch_result['failed'])}. "
                "Такие ответы помечены моделью `fallback`; анализ это учитывает."
            )
        if batch_result.get("code_missing"):
            st.warning(
                f"Без обязательного примера кода: {int(batch_result['code_missing'])}. "
                "Проверьте профили с требованием «с примерами кода»."
            )
        if any(
            item.get("finish_reason") in {"length", "max_tokens"}
            for item in items
        ):
            st.warning("Часть ответов всё ещё помечена как обрезанная по лимиту длины.")
        audit = batch_result.get("audit") or {}
        stability = batch_result.get("stability") or {}
        cols = st.columns(4)
        cols[0].metric(
            "Соблюдено ответов",
            f"{audit.get('compliant_answers', 0)} / {audit.get('answers', 0)}",
        )
        cols[1].metric(
            "Предпочтения",
            f"{audit.get('passed', 0)} / {audit.get('checked', 0)}",
        )
        cols[2].metric(
            "Первое нарушение",
            f"№{audit['first_violation']}" if audit.get("first_violation") else "нет",
        )
        cols[3].metric(
            "Устойчивость", "OK" if stability.get("unchanged", True) else "изменена"
        )
        if audit.get("first_violation"):
            st.warning(
                "Первое нарушение предпочтений: ответ "
                f"№{audit['first_violation']}."
            )
        st.caption(
            "Устойчивость после 10 вопросов: профили "
            f"{stability.get('profiles_before', 0)}/{stability.get('profiles_after', 0)}, "
            "предпочтения "
            f"{stability.get('preferences_before', 0)}/{stability.get('preferences_after', 0)}."
        )
        with (
            st.container(border=True)
            if full_answers
            else st.container(height=560, border=True)
        ):
            for index, item in enumerate(items, start=1):
                with st.chat_message("user", avatar="❓"):
                    st.markdown(f"**{index}. {item.get('question') or ''}**")
                with st.chat_message("assistant", avatar="🧑‍💻"):
                    st.markdown(
                        f"**{item.get('name') or item.get('owner_id')}** · "
                        f"{item.get('role') or 'профиль'}"
                    )
                    prefs = item.get("preferences") or {}
                    if prefs:
                        st.caption(
                            " · ".join(
                                f"{PREFERENCE_LABELS.get(key, key)}: {value}"
                                for key, value in prefs.items()
                            )
                        )
                    st.caption(_audit_text(item))
                    st.markdown(item.get("answer") or "")
                    st.caption(
                        f"Модель: `{item.get('model', '—')}` · "
                        f"промт: {int(item.get('request_tokens') or 0)} токенов · "
                        f"ответ: {int(item.get('response_tokens') or 0)} токенов"
                    )
        if len(items) == 10:
            st.markdown("---")
            st.caption(
                "После ответа на 10 вопросов доступен анализ результатов профилирования."
            )
            if st.button(
                "Анализ результатов профилирования",
                type="primary",
                use_container_width=True,
                key="l12_check_analyze",
            ):
                with st.spinner("Анализирую результаты моделью deepseek-v4-pro…"):
                    try:
                        analysis = _post(
                            "/api/profile-check/analyze",
                            {"session_id": session, "items": items},
                            timeout=300.0,
                        )
                        st.session_state["l12_check_analysis"] = analysis
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(
                            f"Анализ не выполнен: {type(exc).__name__}: {exc}"
                        )

    analysis = st.session_state.get("l12_check_analysis")
    if analysis:
        st.markdown("##### Анализ результатов профилирования")
        st.success(
            f"Модель анализа: `{analysis.get('model', '—')}` · "
            f"запрошена: `{analysis.get('requested_model', 'deepseek-v4-pro')}` · "
            f"промт: {int(analysis.get('request_tokens') or 0)} токенов · "
            f"ответ: {int(analysis.get('response_tokens') or 0)} токенов"
        )
        st.markdown(analysis.get("analysis") or "")
    elif batch_result and len(batch_result.get("results") or []) == 10:
        st.caption("Анализ ещё не запускался.")


def _render_context_tab(state: dict) -> None:
    owner = _owner()
    st.markdown("#### Профиль в каждом запросе")
    st.caption(
        "Один и тот же профиль и предпочтения добавляются в system prompt при каждом "
        "обращении к модели. Ниже — фактический prompt текущего состояния."
    )
    try:
        context = _get(
            "/api/context",
            params={"owner_id": owner, "session_id": SESSION_ID},
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось собрать контекст: {type(exc).__name__}: {exc}")
        return
    st.markdown(
        f"Заполнено полей профиля: **{context['layers']['profile']['filled']}** · "
        f"предпочтений: **{context['layers']['preferences']['filled']}** · "
        f"сообщений: **{context['layers']['dialogue']['count']}**"
    )
    with st.expander("System prompt с профилем", expanded=True):
        st.code(context["system_prompt"], language="text")


def render() -> None:
    _render_sidebar()
    owner = _owner()
    st.title("Урок 12 · Персонализация ассистента")
    st.caption(
        "Профиль пользователя и предпочтения: стиль, формат, примеры кода, emoji, ограничения. "
        "Профиль подключается к каждому запросу и пополняется из диалога."
    )
    try:
        state = _get("/api/profile", params={"owner_id": owner})
    except Exception as exc:  # noqa: BLE001
        st.error(f"API урока 12 недоступен: {type(exc).__name__}: {exc}")
        return

    notice = st.session_state.pop("l12_notice", None)
    if notice:
        st.success(notice)

    profile = state.get("profile") or {}
    st.markdown(
        f"**Текущий профиль:** {_profile_label({'owner_id': owner, **profile})} · "
        f"`{owner}`"
    )
    filled = state.get("filled", 0)
    preference_count = len(state.get("preferences") or [])
    cols = st.columns(3)
    cols[0].metric("Полей профиля", f"{filled} / 5")
    cols[1].metric("Предпочтений", preference_count)
    cols[2].metric("Автообновление", "включено")

    st.info(
        "**Как это работает:** профиль → system prompt → каждый запрос. "
        "После реплики ассистент извлекает устойчивые факты (имя, роль, город, "
        "стиль, формат, примеры кода, emoji, ограничения) и сохраняет их в профиль."
    )

    tabs = st.tabs(
        ["Чат с профилем", "Профиль", "Предпочтения", "Контекст", "Проверка профилей"]
    )
    with tabs[0]:
        _render_chat_tab(state)
    with tabs[1]:
        _render_profile_tab(state)
    with tabs[2]:
        _render_preferences_tab(state)
    with tabs[3]:
        _render_context_tab(state)
    with tabs[4]:
        _render_profile_check_tab(state)
