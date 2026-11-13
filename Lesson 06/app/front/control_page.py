"""Страница «Управление контекстом: сжатие истории» — урок 09."""

from __future__ import annotations

from html import escape

import httpx
import streamlit as st
import streamlit.components.v1 as components

from common import CONTROL_API

# В уроке 09 стратегия не выбирается: до сжатия используется бюджет
# последних сообщений, после — отдельные summary.
CONTEXT_STRATEGY = "budget"


def _with_prechat(demo: dict, pre: list[dict]) -> dict:
    if not pre:
        return demo
    offset = len(pre)
    history = [
        {
            "id": index,
            "role": item["role"],
            "content": item["content"],
            "tokens": max(1, len(item["content"]) // 4),
        }
        for index, item in enumerate(pre, 1)
    ]
    messages = history + [
        {**item, "id": item["id"] + offset} for item in demo["messages"]
    ]
    summaries = [
        {
            **item,
            "from_id": item["from_id"] + offset,
            "to_id": item["to_id"] + offset,
        }
        for item in demo.get("summaries", [])
    ]
    return {**demo, "messages": messages, "summaries": summaries}


def _demo() -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{CONTROL_API}/api/demo-dialogue")
    response.raise_for_status()
    return response.json()


def _context(
    messages: list[dict],
    summaries: list[dict],
    strategy: str,
    max_messages: int,
    max_tokens: int,
    reserve: int,
    compressed: bool,
) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{CONTROL_API}/api/context",
            json={
                "messages": messages,
                "summaries": summaries,
                "use_summaries": compressed,
                "strategy": strategy,
                "max_messages": max_messages,
                "max_tokens": max_tokens,
                "reserve_tokens": reserve,
                "system_tokens": 20,
            },
        )
    response.raise_for_status()
    return response.json()


def _ask(
    messages: list[dict],
    summaries: list[dict],
    question: str,
    strategy: str,
    max_messages: int,
    max_tokens: int,
    reserve: int,
    compressed: bool,
) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{CONTROL_API}/api/ask",
            json={
                "messages": messages,
                "summaries": summaries,
                "use_summaries": compressed,
                "question": question,
                "strategy": strategy,
                "max_messages": max_messages,
                "max_tokens": max_tokens,
                "reserve_tokens": reserve,
                "system_tokens": 20,
            },
        )
    response.raise_for_status()
    return response.json()


def _compress(messages: list[dict], summaries: list[dict], max_tokens: int, reserve: int) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{CONTROL_API}/api/compress",
            json={
                "messages": messages,
                "summaries": summaries,
                "max_tokens": max_tokens,
                "reserve_tokens": reserve,
                "system_tokens": 20,
            },
        )
    response.raise_for_status()
    return response.json()


def _make_demo() -> None:
    # Диалог не кэшируем: сохраняем только факт, что он запрошен.
    demo = _demo()
    pre = st.session_state.get("l09_empty_chat") or st.session_state.get("l09_pre_chat", [])
    st.session_state["l09_pre_chat"] = pre
    st.session_state["l09_loaded"] = True
    st.session_state["l09_chat"] = []
    st.session_state["l09_empty_chat"] = []
    st.session_state["l09_compressed"] = False
    st.session_state["l09_notice"] = (
        f"Диалог сформирован: {len(demo['messages'])} сообщений, "
        f"{len(demo.get('summaries', []))} summary."
    )


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _labeled_slider(
    label: str,
    min_value: int,
    max_value: int,
    default: int,
    step: int,
    key: str,
    unit: str,
) -> int:
    current = min(max(int(st.session_state.get(key, default)), min_value), max_value)
    if st.session_state.get(key) != current:
        st.session_state[key] = current
    st.markdown(f"**{label}:** {_num(current)} {unit}")
    return st.slider(
        label,
        min_value=min_value,
        max_value=max_value,
        value=default,
        step=step,
        key=key,
        label_visibility="collapsed",
    )


def _render_messages(
    messages: list[dict],
    summaries: list[dict],
    result: dict,
    compressed: bool,
) -> None:
    included_ids = set() if compressed else set(result["included_ids"])
    tokens_by_id = result.get("message_tokens", {})
    summary_by_to = {item["to_id"]: item for item in summaries}

    for item in messages:
        is_included = item["id"] in included_ids
        role = item["role"]
        with st.chat_message(role, avatar="🧑" if role == "user" else "🤖"):
            if compressed:
                badge = "📦 заменено summary"
            elif is_included:
                badge = "✅ в контексте"
            else:
                badge = "⛔ отброшено"
            tokens = tokens_by_id.get(
                str(item["id"]), tokens_by_id.get(item["id"], item["tokens"])
            )
            if compressed or not is_included:
                st.caption(f"№{item['id']} · {_num(tokens)} токенов · {badge}")
                st.markdown(escape(item["content"]))
            else:
                st.markdown(escape(item["content"]))
                st.caption(f"№{item['id']} · {_num(tokens)} токенов · {badge}")

        summary = summary_by_to.get(item["id"])
        if summary:
            with st.expander(
                f"SUMMARY {summary['from_id']}–{summary['to_id']} · "
                f"{_num(summary['tokens'])} токенов"
            ):
                st.write(summary["content"])


def _chat_api(history: list[dict]) -> str:
    with httpx.Client(timeout=45.0) as client:
        response = client.post(
            f"{CONTROL_API}/api/chat",
            json={"messages": [{"role": item["role"], "content": item["content"]} for item in history]},
        )
    response.raise_for_status()
    return response.json()["answer"]


def _general_reply(text: str) -> str:
    low = text.lower().strip()
    if any(word in low for word in ("привет", "здравствуй", "добрый")):
        return "Привет! Я готов помочь. Сформируйте диалог, и я смогу отвечать по его фактам."
    if "спасибо" in low:
        return "Пожалуйста! Если нужен ответ по проекту, сначала сформируйте диалог."
    if "как дела" in low:
        return "У меня всё готово. Сформируйте диалог — и можно задавать вопросы по нему."
    if any(word in low for word in ("кто ты", "что ты умеешь")):
        return "Я контекстный ИИ-помощник: отвечаю по фактам диалога. Сформируйте диалог, чтобы начать."
    return (
        "Принял сообщение и сохранил его в истории. "
        "После формирования диалога смогу отвечать по его фактам."
    )


def _scroll_chat_to_bottom() -> None:
    """Прокрутить историю чата к последнему сообщению."""
    components.html(
        """
        <script>
        const doc = window.parent.document;
        const anchors = doc.querySelectorAll('.l09-chat-anchor');
        const anchor = anchors[anchors.length - 1];
        if (anchor) {
            let box = anchor.parentElement;
            while (box) {
                if (box.scrollHeight > box.clientHeight + 2) {
                    box.scrollTop = box.scrollHeight;
                    break;
                }
                box = box.parentElement;
            }
        }
        </script>
        """,
        height=0,
    )


def _render_empty_chat() -> None:
    st.markdown("#### Чат с ИИ-моделью")
    st.caption(
        "Сообщение не создаёт диалог. Чтобы получать ответы по контексту, "
        "сначала нажмите «Сформировать диалог»."
    )
    chat = st.session_state.setdefault("l09_empty_chat", [])
    with st.container(height=360, border=True):
        for entry in chat:
            with st.chat_message(entry["role"], avatar="🧑" if entry["role"] == "user" else "🤖"):
                st.markdown(entry["content"])
        st.markdown('<div class="l09-chat-anchor"></div>', unsafe_allow_html=True)
    _scroll_chat_to_bottom()
    with st.form("l09_chat_empty_form", clear_on_submit=True):
        question = st.text_input(
            "Сообщение для ИИ-модели",
            placeholder="Напишите сообщение…",
            key="l09_chat_empty_text",
        )
        send_col, generate_col = st.columns(2)
        with send_col:
            submitted = st.form_submit_button("Отправить", use_container_width=True)
        with generate_col:
            generate = st.form_submit_button("Сформировать диалог", use_container_width=True)
    if generate:
        _make_demo()
        st.rerun()
    if submitted and question.strip():
        chat.append({"role": "user", "content": question.strip()})
        try:
            answer = _chat_api(chat)
        except Exception:  # noqa: BLE001
            answer = _general_reply(question)
        chat.append({"role": "assistant", "content": answer})
        st.rerun()


def _render_chat(
    messages: list[dict],
    summaries: list[dict],
    strategy: str,
    max_messages: int,
    max_tokens: int,
    reserve: int,
    compressed: bool,
    result: dict,
) -> None:
    st.markdown("#### Чат с ИИ-моделью")
    st.caption(
        "Ответ строится только по тому, что попало в текущий контекст. "
        "При сжатии используются summary, а не полные сообщения. "
        "Каждый вопрос отправляется заново с пересобранным контекстом."
    )
    chat = st.session_state.setdefault("l09_chat", [])
    with st.container(height=360, border=True):
        _render_messages(messages, summaries, result, compressed)
        for entry in chat:
            with st.chat_message(entry["role"], avatar="🧑" if entry["role"] == "user" else "🤖"):
                st.markdown(entry["content"])
                sources = entry.get("sources") or []
                if sources:
                    if entry.get("compressed"):
                        labels = [f"summary №{item - 1000}" for item in sources if item >= 1000]
                    else:
                        labels = [f"№{item}" for item in sources]
                    st.caption("Источники: " + ", ".join(labels))
                elif entry.get("mode") == "general":
                    st.caption("Режим: общий вопрос к модели")
                elif entry["role"] == "assistant":
                    st.caption("Ответ без источника: факт не найден в выбранном контексте.")
                if entry.get("mode") == "context":
                    st.caption("Режим: только по контексту")
        st.markdown('<div class="l09-chat-anchor"></div>', unsafe_allow_html=True)
    _scroll_chat_to_bottom()
    if st.session_state.pop("l09_clear_chat_text", False):
        st.session_state["l09_chat_text"] = ""
    with st.form("l09_chat_form", clear_on_submit=False):
        question = st.text_input(
            "Сообщение для ИИ-модели",
            placeholder="Спросите по истории диалога…",
            key="l09_chat_text",
        )
        send_col, mode_col = st.columns([1, 2])
        with send_col:
            submitted = st.form_submit_button("Отправить", use_container_width=True)
        with mode_col:
            context_only = st.toggle(
                "Только по контексту",
                value=True,
                key="l09_context_only",
                help="Выключите, чтобы задать общий вопрос модели без контекста диалога.",
            )
    if submitted and question.strip():
        chat.append({"role": "user", "content": question.strip()})
        try:
            if context_only:
                answer = _ask(
                    messages,
                    summaries,
                    question,
                    strategy,
                    max_messages,
                    max_tokens,
                    reserve,
                    compressed,
                )
                chat.append(
                    {
                        "role": "assistant",
                        "content": answer["answer"],
                        "sources": answer.get("source_ids") or [],
                        "compressed": bool(answer.get("compressed")),
                        "mode": "context",
                    }
                )
            else:
                chat.append(
                    {
                        "role": "assistant",
                        "content": _chat_api(chat),
                        "sources": [],
                        "compressed": False,
                        "mode": "general",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            chat.append(
                {
                    "role": "assistant",
                    "content": f"Не удалось получить ответ: {type(exc).__name__}: {exc}",
                    "sources": [],
                }
            )
        st.session_state["l09_clear_chat_text"] = True
        st.rerun()


def _render_dialogue(
    demo: dict,
    messages: list[dict],
    summaries: list[dict],
    result: dict,
    compressed: bool,
    strategy: str,
    max_messages: int,
    max_tokens: int,
    reserve: int,
) -> None:
    st.markdown(f"### {escape(demo['title'])}")
    st.caption(demo.get("description", ""))
    if st.session_state.get("l09_notice"):
        st.success(st.session_state["l09_notice"])
        st.session_state.pop("l09_notice", None)

    cols = st.columns(4)
    cols[0].metric("Сообщений", len(messages))
    cols[1].metric("В контексте", len(result["included_ids"]))
    cols[2].metric("Токенов", _num(result["context_tokens"]))
    cols[3].metric("Отброшено", len(result["dropped_ids"]))

    if compressed:
        st.info(
            f"Активно сжатие: в запрос уходят {len(result['included_ids'])} summary "
            f"вместо {len(messages)} сообщений. Полная история показана для справки."
        )
    elif not result["fits"]:
        st.error(
            f"Контекст не помещается в окно: {_num(result['context_tokens'])} из "
            f"{_num(result['available'])} токенов, превышение {_num(result['overflow'])}."
        )
    elif result["dropped_ids"]:
        st.info(
            f"В контекст вошли {len(result['included_ids'])} из {len(messages)} сообщений; "
            f"{len(result['dropped_ids'])} отброшено."
        )
    else:
        st.success("Вся история помещается в выбранное окно контекста.")

    st.markdown("#### Сообщения")
    st.caption("Каждые 10 сообщений сворачиваются в отдельное summary — раскройте блок под десятым сообщением.")
    _render_chat(
        messages, summaries, strategy, max_messages, max_tokens, reserve, compressed, result
    )


def _render_comparison(
    messages: list[dict],
    summaries: list[dict],
    comparison: dict,
    compressed: bool,
    max_tokens: int,
    reserve: int,
) -> None:
    st.markdown("### Использование токенов: до и после сжатия")
    st.caption(
        f"Сравнивается полная история ({len(messages)} сообщений) и отдельно "
        f"хранимые summary ({len(summaries)} шт.). Доступно под контекст: "
        f"{_num(max(0, max_tokens - reserve))} токенов."
    )

    before = comparison["before"]
    after = comparison["after"]
    rows = [
        {
            "Вариант": "До сжатия — полная история",
            "Сообщений": before["messages"],
            "Summary": before["summaries"],
            "Токенов": before["tokens"],
            "Экономия": "—",
            "Помещается": "да" if before["fits"] else f"нет, +{_num(before['overflow'])}",
        },
        {
            "Вариант": "После сжатия — summary",
            "Сообщений": after["messages"],
            "Summary": after["summaries"],
            "Токенов": after["tokens"],
            "Экономия": f"{comparison['saved_percent']:.1f}%",
            "Помещается": "да" if after["fits"] else f"нет, +{_num(after['overflow'])}",
        },
    ]
    st.table(rows)

    cols = st.columns(3)
    cols[0].metric("Токенов до", _num(before["tokens"]))
    cols[1].metric("Токенов после", _num(after["tokens"]))
    cols[2].metric(
        "Экономия",
        f"{_num(comparison['saved_tokens'])} токенов",
        f"{comparison['saved_percent']:.1f}%",
    )

    st.markdown("#### Что именно хранится отдельно")
    st.caption(
        "Summary не являются сообщениями диалога: они лежат отдельным списком "
        "и подставляются в запрос только при включённом сжатии."
    )
    for summary in summaries:
        with st.expander(
            f"SUMMARY {summary['from_id']}–{summary['to_id']} · "
            f"{_num(summary['tokens'])} токенов"
        ):
            st.write(summary["content"])

    if compressed:
        st.success("Сжатие включено: в контекст подставляются summary.")
    else:
        st.info("Сжатие выключено: в контекст подставляется выбранная история сообщений.")


def render() -> None:
    st.markdown(
        """<style>
        .l09-intro { font-size: .86rem; opacity: .72; max-width: 62rem; margin-bottom: .4rem; }
        </style>""",
        unsafe_allow_html=True,
    )

    demo = None
    load_error = ""
    if st.session_state.get("l09_loaded"):
        try:
            # Каждый rerun — новый запрос к API, без кэша диалога.
            demo = _with_prechat(_demo(), st.session_state.get("l09_pre_chat", []))
        except Exception as exc:  # noqa: BLE001
            load_error = f"{type(exc).__name__}: {exc}"
    messages = demo["messages"] if demo else []
    summaries = demo.get("summaries", []) if demo else []

    with st.sidebar:
        st.markdown("#### Сжатие истории")
        st.caption("Настройки применяются к текущему демо-диалогу.")

        strategy = CONTEXT_STRATEGY
        compressed = bool(st.session_state.get("l09_compressed", False))
        if st.button(
            "Вернуть полную историю" if compressed else "Сжать контекст (summary)",
            use_container_width=True,
            key="l09_compress",
            disabled=not messages,
        ):
            st.session_state["l09_compressed"] = not compressed
            st.session_state["l09_notice"] = (
                "Контекст сжат: используются отдельные summary."
                if not compressed
                else "Сжатие отключено: снова используется история сообщений."
            )
            st.rerun()
        st.caption(
            "До сжатия — последние сообщения в пределах лимита; "
            "после — отдельные summary каждых 10 сообщений."
        )

        max_messages = _labeled_slider(
            "Лимит сообщений", 2, 25, 12, 1, "l09_max_messages", "сообщений"
        )
        max_tokens = _labeled_slider(
            "Окно контекста", 256, 8_000, 4_000, 128, "l09_max_tokens", "токенов"
        )
        reserve = _labeled_slider(
            "Резерв под ответ", 0, 2_000, 500, 50, "l09_reserve", "токенов"
        )

        result = None
        if messages:
            try:
                result = _context(
                    messages, summaries, strategy, max_messages, max_tokens, reserve, compressed
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"API контекста недоступен: {type(exc).__name__}: {exc}")

        if result:
            st.divider()
            st.caption("Текущий контекст")
            if compressed:
                st.markdown(
                    f"**Сжатый контекст** · {len(result['included_ids'])} из "
                    f"{len(summaries)} summary  \n"
                    f"{_num(result['context_tokens'])} / {_num(result['available'])} токенов  \n"
                    f"Отброшено summary: {len(result['dropped_ids'])}"
                )
            else:
                st.markdown(
                    f"**{result['strategy_label']}** · "
                    f"{len(result['included_ids'])} из {len(messages)} сообщений  \n"
                    f"{_num(result['context_tokens'])} / {_num(result['available'])} токенов  \n"
                    f"Отброшено: {len(result['dropped_ids'])}"
                )
            if not result["fits"]:
                st.warning(f"Переполнение: +{_num(result['overflow'])} токенов")
        st.divider()
        if st.button("Очистить диалог", use_container_width=True, key="l09_clear"):
            st.session_state.pop("l09_notice", None)
            st.session_state.pop("l09_chat", None)
            st.session_state.pop("l09_empty_chat", None)
            st.session_state.pop("l09_pre_chat", None)
            st.session_state["l09_loaded"] = False
            st.session_state["l09_compressed"] = False
            st.rerun()

    if load_error:
        st.error(f"Не удалось получить диалог из API: {load_error}")
        return

    st.markdown(
        """<style>
        @media (max-width: 900px) {
            [data-testid="stMain"] {
                margin-left: 300px !important;
                width: calc(100% - 300px) !important;
                max-width: calc(100% - 300px) !important;
            }
        }
        </style>""",
        unsafe_allow_html=True,
    )
    st.title("Управление контекстом: сжатие истории")
    st.markdown(
        '<div class="l09-intro">Демонстрационный диалог на 25 сообщений. '
        "Каждые 10 сообщений имеют отдельное summary, последний блок — 5 сообщений; "
        "кнопка «Сжать контекст (summary)» заменяет полную историю на summary и показывает "
        "экономию токенов.</div>",
        unsafe_allow_html=True,
    )
    if not messages:
        st.info("Нажмите **«Сформировать диалог»** ниже, чтобы начать.")
        _render_empty_chat()
        return

    if result is None:
        st.error("Контекст не рассчитан.")
        return

    try:
        comparison = _compress(messages, summaries, max_tokens, reserve)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось сравнить токены: {type(exc).__name__}: {exc}")
        return

    dialogue_tab, comparison_tab = st.tabs(["Диалог", "Сравнение токенов"])
    with dialogue_tab:
        _render_dialogue(
            demo,
            messages,
            summaries,
            result,
            compressed,
            strategy,
            max_messages,
            max_tokens,
            reserve,
        )
    with comparison_tab:
        _render_comparison(messages, summaries, comparison, compressed, max_tokens, reserve)
