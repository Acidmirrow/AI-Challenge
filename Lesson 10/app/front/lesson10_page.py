"""Страница урока 10: сравнение стратегий управления контекстом."""

from __future__ import annotations

import re
from html import escape

import httpx
import streamlit as st
import streamlit.components.v1 as components

from common import LESSON_10_API

STRATEGY_OPTIONS = {
    "sliding": "Sliding window",
    "sticky": "Sticky facts / Key-Value memory",
    "summary": "Summary блоки",
    "full": "Без сжатия — вся история",
}

STRATEGY_HINTS = {
    "sliding": "Хранит последние N сообщений; все остальные отбрасываются.",
    "sticky": "Отдельный блок facts «ключ → значение»; обновляется после каждого сообщения пользователя.",
    "summary": "История заменяется summary каждых 10 сообщений.",
    "full": "В запрос уходит вся история диалога.",
}

_CODE_SUFFIX = re.compile(r"\s*·\s*PRJ-[A-Z0-9-]+", re.IGNORECASE)
_CODE_FIELD = re.compile(r"\s*;?\s*Код:\s*PRJ-[A-Z0-9-]+\.?", re.IGNORECASE)


def _clean(text: str) -> str:
    return _CODE_FIELD.sub("", _CODE_SUFFIX.sub("", text))


def _short(text: str, limit: int = 100) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _generate() -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(f"{LESSON_10_API}/api/generate")
    response.raise_for_status()
    return response.json()


def _load_comparison(
    messages: list[dict],
    summaries: list[dict],
    sliding_window: int,
    facts_window: int,
) -> dict:
    with httpx.Client(timeout=90.0) as client:
        response = client.post(
            f"{LESSON_10_API}/api/compare",
            json={
                "messages": messages,
                "summaries": summaries,
                "sliding_window": sliding_window,
                "facts_window": facts_window,
            },
        )
    response.raise_for_status()
    return response.json()


def _analyze(
    rows: list[dict],
    branch: str,
    trunk_count: int,
    branch_count: int,
) -> str:
    compact = [
        {
            "id": item["id"],
            "label": item["label"],
            "parameter": item["parameter"],
            "messages_count": item["messages_count"],
            "facts_count": item["facts_count"],
            "summaries_count": item["summaries_count"],
            "tokens": item["tokens"],
            "dropped_messages": item["dropped_messages"],
        }
        for item in rows
    ]
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{LESSON_10_API}/api/analyze",
            json={
                "strategies": compact,
                "branch": branch,
                "trunk_count": trunk_count,
                "branch_count": branch_count,
            },
        )
    response.raise_for_status()
    analysis = (response.json().get("analysis") or "").strip()
    if not analysis:
        raise RuntimeError("модель вернула пустой развёрнутый вывод")
    return analysis


def _ask(
    messages: list[dict],
    summaries: list[dict],
    strategy: str,
    question: str,
    sliding_window: int,
    facts_window: int,
) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{LESSON_10_API}/api/ask",
            json={
                "messages": messages,
                "summaries": summaries,
                "strategy": strategy,
                "question": question,
                "sliding_window": sliding_window,
                "facts_window": facts_window,
            },
        )
    response.raise_for_status()
    return response.json()


def _strategy_picker() -> str:
    current = st.session_state.get("l10_strategy", "sliding")
    with st.popover(
        f"Стратегия · {STRATEGY_OPTIONS.get(current, STRATEGY_OPTIONS['sliding'])}",
        use_container_width=True,
    ):
        st.caption("Выберите стратегию из списка")
        selected = st.radio(
            "Стратегия сжатия контекста",
            options=list(STRATEGY_OPTIONS),
            format_func=lambda value: STRATEGY_OPTIONS[value],
            captions=[STRATEGY_HINTS[value] for value in STRATEGY_OPTIONS],
            key="l10_strategy",
            label_visibility="collapsed",
        )
    st.caption(STRATEGY_HINTS[selected])
    return selected


def _num(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _with_prechat(dialogue: dict, pre: list[dict]) -> dict:
    if not pre:
        return dialogue
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
        {**item, "id": item["id"] + offset} for item in dialogue["messages"]
    ]
    summaries = [
        {
            **item,
            "from_id": item["from_id"] + offset,
            "to_id": item["to_id"] + offset,
        }
        for item in dialogue.get("summaries", [])
    ]
    branches = []
    for branch in dialogue.get("branches", []):
        branches.append(
            {
                **branch,
                "messages": [{**item, "id": item["id"] + offset} for item in branch["messages"]],
                "summaries": [
                    {
                        **item,
                        "from_id": item["from_id"] + offset,
                        "to_id": item["to_id"] + offset,
                    }
                    for item in branch.get("summaries", [])
                ],
                "checkpoints": [
                    {**item, "message_id": item["message_id"] + offset}
                    for item in branch.get("checkpoints", [])
                ],
            }
        )
    return {
        **dialogue,
        "messages": messages,
        "summaries": summaries,
        "branches": branches,
        "checkpoints": [
            {**item, "message_id": item["message_id"] + offset}
            for item in dialogue.get("checkpoints", [])
        ],
        "branch_point": dialogue.get("branch_point", 0) + offset,
        "trunk_count": len(messages),
    }


def _branch_view(dialogue: dict, branch_id: str | None) -> dict:
    branches = dialogue.get("branches", [])
    branch = next((item for item in branches if item["id"] == branch_id), None)
    if branch is None:
        branch = branches[0] if branches else None
    if branch is None:
        return dialogue
    return {
        **dialogue,
        "messages": dialogue["messages"] + branch["messages"],
        "summaries": dialogue.get("summaries", []) + branch.get("summaries", []),
        "checkpoints": dialogue.get("checkpoints", []) + branch.get("checkpoints", []),
        "branch": branch,
    }


def _branch_changed() -> None:
    st.session_state["l10_chat"] = []


def _make_dialogue() -> None:
    try:
        pre = st.session_state.get("l10_empty_chat", [])
        generated = _with_prechat(_generate(), pre)
        st.session_state["l10_dialogue"] = generated
        branches = generated.get("branches", [])
        st.session_state["l10_branch"] = branches[0]["id"] if branches else None
        st.session_state["l10_chat"] = []
        st.session_state["l10_empty_chat"] = []
        st.session_state.pop("l10_cleared", None)
        st.session_state.pop("l10_analysis", None)
        st.session_state.pop("l10_analysis_key", None)
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось сгенерировать диалог: {type(exc).__name__}: {exc}")


def _render_full_dialogue(messages: list[dict], row: dict) -> None:
    included = {item["id"] for item in row.get("included_messages", [])}
    if row["id"] == "summary":
        included = {item["id"] for item in messages}
    st.markdown("#### Диалог")
    st.caption("Полностью все сообщения диалога; ✅ — сообщение входит в выбранный контекст.")
    for item in messages:
        role_label = "Пользователь" if item["role"] == "user" else "Модель"
        if row["id"] == "sticky":
            badge = "📌 в facts" if item["id"] in included else "—"
        else:
            badge = "✅ в контексте" if item["id"] in included else "—"
        with st.chat_message(item["role"], avatar="🧑" if item["role"] == "user" else "🤖"):
            st.markdown(_clean(item["content"]))
            st.caption(
                f"№{item['id']} · {role_label} · {_num(item['tokens'])} токенов · {badge}"
            )


def _chat_api(history: list[dict]) -> str:
    with httpx.Client(timeout=45.0) as client:
        response = client.post(
            f"{LESSON_10_API}/api/chat",
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
        const anchors = doc.querySelectorAll('.l10-chat-anchor');
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
        "сначала нажмите «Сгенерировать диалог»."
    )
    chat = st.session_state.setdefault("l10_empty_chat", [])
    with st.container(height=360, border=True):
        for entry in chat:
            with st.chat_message(entry["role"], avatar="🧑" if entry["role"] == "user" else "🤖"):
                st.markdown(entry["content"])
        st.markdown('<div class="l10-chat-anchor"></div>', unsafe_allow_html=True)
    _scroll_chat_to_bottom()

    with st.form("l10_chat_empty_form", clear_on_submit=True):
        question = st.text_input(
            "Сообщение для ИИ-модели",
            placeholder="Напишите сообщение…",
            key="l10_chat_empty_text",
        )
        send_col, generate_col = st.columns(2)
        with send_col:
            submitted = st.form_submit_button("Отправить", use_container_width=True)
        with generate_col:
            generate = st.form_submit_button("Сгенерировать диалог", use_container_width=True)
    if generate:
        _make_dialogue()
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
    dialogue: dict,
    strategy: str,
    sliding_window: int,
    facts_window: int,
    row: dict | None = None,
) -> None:
    st.markdown("#### Чат с ИИ-моделью")
    st.caption(
        "Вопрос отправляется с контекстом, собранным по выбранной стратегии. "
        "Ответ показывает источник."
    )
    chat = st.session_state.setdefault("l10_chat", [])
    checkpoints = {
        item["message_id"]: item["label"] for item in dialogue.get("checkpoints", [])
    }
    with st.container(height=360, border=True):
        if row is not None:
            included = {item["id"] for item in row.get("included_messages", [])}
            if row["id"] == "summary":
                included = {item["id"] for item in dialogue["messages"]}
            for item in dialogue["messages"]:
                role_label = "Пользователь" if item["role"] == "user" else "Модель"
                if row["id"] == "sticky":
                    badge = "📌 в facts" if item["id"] in included else "—"
                else:
                    badge = "✅ в контексте" if item["id"] in included else "—"
                with st.chat_message(item["role"], avatar="🧑" if item["role"] == "user" else "🤖"):
                    st.markdown(_clean(item["content"]))
                    st.caption(
                        f"№{item['id']} · {role_label} · {_num(item['tokens'])} токенов · {badge}"
                    )
                    if item["id"] in checkpoints:
                        st.caption(f"★ Checkpoint · {checkpoints[item['id']]}")
        for entry in chat:
            with st.chat_message(entry["role"], avatar="🧑" if entry["role"] == "user" else "🤖"):
                st.markdown(entry["content"])
                if entry.get("mode") == "general":
                    st.caption("Режим: общий вопрос к модели")
                elif entry.get("mode") == "context":
                    st.caption("Режим: только по контексту")
                if entry.get("source"):
                    st.caption(f"Источник: {entry['source']}")
        st.markdown('<div class="l10-chat-anchor"></div>', unsafe_allow_html=True)
    _scroll_chat_to_bottom()

    if st.session_state.pop("l10_clear_chat_text", False):
        st.session_state["l10_chat_text"] = ""
    with st.form("l10_chat_form", clear_on_submit=False):
        question = st.text_input(
            "Сообщение для ИИ-модели",
            placeholder="Спросите по текущему диалогу…",
            key="l10_chat_text",
        )
        send_col, mode_col = st.columns([1, 2])
        with send_col:
            submitted = st.form_submit_button("Отправить", use_container_width=True)
        with mode_col:
            context_only = st.toggle(
                "Только по контексту",
                value=True,
                key="l10_context_only",
                help="Выключите, чтобы задать общий вопрос модели без контекста диалога.",
            )
    if submitted and question.strip():
        chat.append({"role": "user", "content": question.strip()})
        try:
            if context_only:
                answer = _ask(
                    dialogue["messages"],
                    dialogue.get("summaries", []),
                    strategy,
                    question.strip(),
                    sliding_window,
                    facts_window,
                )
                chat.append(
                    {
                        "role": "assistant",
                        "content": answer["answer"],
                        "source": answer.get("source") or "",
                        "mode": "context",
                    }
                )
            else:
                chat.append(
                    {
                        "role": "assistant",
                        "content": _chat_api(chat),
                        "source": "",
                        "mode": "general",
                    }
                )
        except Exception as exc:  # noqa: BLE001
            chat.append(
                {
                    "role": "assistant",
                    "content": f"Не удалось получить ответ: {type(exc).__name__}: {exc}",
                    "source": "",
                }
            )
        st.session_state["l10_clear_chat_text"] = True
        st.rerun()

def _render_context(row: dict) -> None:
    strategy = row["id"]
    if strategy == "sticky":
        facts = row.get("facts") or {}
        if not facts:
            st.warning(
                "Facts пока пуст: увеличьте «Сколько последних сообщений уходят в facts»."
            )
            return
        st.markdown("#### Facts (Key-Value memory)")
        st.caption(
            f"Обновлений после сообщений пользователя: {row['facts_updates']}. "
            "Facts накапливаются и не удаляются при сдвиге окна."
        )
        st.table(
            [
                {"Ключ": key, "Значение": value}
                for key, value in facts.items()
                if key != "Код" and "PRJ-" not in str(value)
            ]
        )
        return

    if strategy == "summary":
        st.markdown("#### Summary блоки")
        for summary in row.get("included_summaries", []):
            with st.expander(
                f"SUMMARY {summary['from_id']}–{summary['to_id']} · "
                f"{_num(summary['tokens'])} токенов"
            ):
                st.write(_clean(summary["content"]))
        return

    st.caption("Полный диалог показан выше; зелёная метка отмечает сообщения в контексте.")


def render() -> None:
    with st.sidebar:
        st.markdown("### Урок 10")
        st.caption("Сравнение стратегий управления контекстом")
        strategy = _strategy_picker()
        dialogue_for_branch = st.session_state.get("l10_dialogue")
        branch_id = None
        if dialogue_for_branch and dialogue_for_branch.get("branches"):
            branches = dialogue_for_branch["branches"]
            branch_ids = [item["id"] for item in branches]
            current_branch = st.session_state.get("l10_branch")
            branch_index = branch_ids.index(current_branch) if current_branch in branch_ids else 0
            branch_id = st.selectbox(
                "Ветка диалога",
                options=branch_ids,
                index=branch_index,
                format_func=lambda value: next(
                    item["label"] for item in branches if item["id"] == value
                ),
                key="l10_branch",
                on_change=_branch_changed,
            )
            branch_for_window = next(
                (item for item in branches if item["id"] == branch_id), branches[0]
            )
            branch_len = len(branch_for_window["messages"])
        else:
            branch_len = 0
        if st.button(
            "Очистить весь диалог",
            use_container_width=True,
            key="l10_clear",
        ):
            st.session_state["l10_dialogue"] = None
            st.session_state["l10_chat"] = []
            st.session_state["l10_empty_chat"] = []
            st.session_state.pop("l10_branch", None)
            st.session_state.pop("l10_analysis", None)
            st.session_state.pop("l10_analysis_key", None)
            st.rerun()

        # Sliding window всегда захватывает всю выбранную ветку и 10 сообщений ствола.
        sliding_window = 10 + branch_len
        st.caption(
            "Sliding window настроен автоматически: "
            f"10 сообщений ствола + {branch_len} сообщений ветки = {sliding_window}."
        )

        if strategy == "sticky":
            facts_window = st.slider(
                "Сколько последних сообщений уходят в facts",
                min_value=1,
                max_value=50,
                value=6,
                step=1,
                key="l10_facts_window",
            )
            st.caption(
                "После каждого сообщения пользователя facts обновляются "
                f"по последним {facts_window} сообщениям."
            )
        else:
            facts_window = int(st.session_state.get("l10_facts_window", 6))

        st.divider()

    st.markdown(
        """<style>
        .l10-stats { display: flex; flex-wrap: wrap; gap: .35rem 1.1rem;
                     font-size: .74rem; opacity: .78; margin: .2rem 0 .6rem; }
        .l10-stats b { font-weight: 600; opacity: 1; }
        </style>""",
        unsafe_allow_html=True,
    )
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
    st.title("Управление контекстом: Сравнение стратегий")
    st.caption("Урок 10 · ИИ-агент управления контекстом")
    st.markdown(
        "ИИ-агент: три стратегии сжатия контекста и режим без сжатия. "
        "Сначала сгенерируйте ветвящийся диалог, затем выберите ветку и стратегию."
    )

    dialogue = st.session_state.get("l10_dialogue")
    if not dialogue:
        st.info(
            "Диалог ещё не создан. Нажмите **«Сгенерировать диалог»** — "
            "будет создан ствол на 25 сообщений и три ветки по 10–15 сообщений."
        )
        _render_empty_chat()
        return

    view = _branch_view(dialogue, branch_id)
    branch = view.get("branch")
    branch_note = (
        f"ствол {len(dialogue['messages'])} + ветка {len(branch['messages'])}"
        if branch
        else f"{len(view['messages'])} сообщений"
    )
    st.markdown(f"### {_clean(view['title'])}")
    st.caption(
        f"{branch_note} · {len(view.get('summaries', []))} summary · "
        f"{'ветка: ' + branch['label'] if branch else 'уникальная тема'}."
    )
    if branch:
        st.caption(
            f"Ствол одинаковый (hash {dialogue.get('trunk_hash', '—')}), "
            f"все ветки начинаются после сообщения №{dialogue.get('branch_point', 25)}."
        )
    try:
        comparison = _load_comparison(
            view["messages"],
            view.get("summaries", []),
            sliding_window,
            facts_window,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"API урока 10 недоступен: {type(exc).__name__}: {exc}")
        return

    rows = comparison.get("strategies", [])
    by_id = {row["id"]: row for row in rows}
    row = by_id.get(strategy)
    if row is None:
        st.error("API не вернул выбранную стратегию.")
        return

    st.markdown(
        f'<div class="l10-stats">'
        f'<span><b>Стратегия:</b> {escape(STRATEGY_OPTIONS[strategy])}</span>'
        f'<span><b>Токенов:</b> {_num(row["tokens"])}</span>'
        f'<span><b>Сообщений:</b> {row["messages_count"]}</span>'
        f'<span><b>Facts:</b> {row["facts_count"]}</span>'
        f'<span><b>Отброшено:</b> {row["dropped_messages"]}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.caption(f"Параметр: {row['parameter']}.")

    _render_chat(view, strategy, sliding_window, facts_window, row=row)
    _render_context(row)

    st.divider()
    st.markdown("#### Результаты агента: стратегии контекста")
    complexity = {
        "sliding": "Низкая",
        "sticky": "Средняя",
        "summary": "Средняя",
        "full": "Высокая",
    }
    table = []
    for item in rows:
        if item["id"] == "sticky":
            details = item["facts_count"]
        elif item["id"] == "summary":
            details = item["summaries_count"]
        else:
            details = item["messages_count"]
        table.append(
            {
                "Стратегия": ("● " if item["id"] == strategy else "") + item["label"],
                "Деталей сохранено": details,
                "Токены": _num(item["tokens"]),
                "Сложность": complexity[item["id"]],
            }
        )
    st.table(table)

    st.markdown("#### Развёрнутый вывод")
    branch_label = branch["label"] if branch else "ветка не выбрана"
    branch_count = len(branch["messages"]) if branch else 0
    analysis_key = (
        f"v2:{dialogue.get('trunk_hash', '')}:{branch.get('id', '') if branch else ''}:"
        f"{sliding_window}:{facts_window}"
    )
    cached_analysis = (
        st.session_state.get("l10_analysis_key") == analysis_key
        and st.session_state.get("l10_analysis")
    )
    if cached_analysis:
        st.markdown(st.session_state["l10_analysis"])
        st.caption("Анализ: deepseek-v4-pro")
    else:
        st.info(
            "Развёрнутый вывод формируется по запросу, чтобы переключение веток "
            "не ждало reasoning-модель."
        )
        if st.button(
            "Сформировать развёрнутый вывод",
            type="primary",
            key="l10_analyze_button",
        ):
            try:
                with st.spinner("deepseek-v4-pro формирует развёрнутый вывод…"):
                    text = _analyze(
                        rows,
                        branch_label,
                        len(dialogue["messages"]),
                        branch_count,
                    )
                if not text.strip():
                    raise RuntimeError("пустой ответ анализа")
                st.session_state["l10_analysis"] = text
                st.session_state["l10_analysis_key"] = analysis_key
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.warning(
                    f"Анализ deepseek-v4-pro недоступен: {type(exc).__name__}: {exc}"
                )

    st.markdown("#### Выводы")
    full = by_id["full"]
    sliding = by_id["sliding"]
    sticky = by_id["sticky"]
    summary = by_id["summary"]
    branch_label = branch["label"] if branch else "ветка не выбрана"
    branch_len = len(branch["messages"]) if branch else 0
    st.markdown(
        f"""
- **Ствол — {len(dialogue['messages'])} сообщений, ветка «{branch_label}» — {branch_len} сообщений.**
  Все данные генерируются заново; между запусками контекст не переиспользуется.
- **Без сжатия** сохраняет весь ствол и всю ветку: {full['messages_count']} сообщений,
  {_num(full['tokens'])} токенов. Это максимальная полнота, но и максимальная цена.
- **Sliding window (N={sliding_window})** оставляет {sliding['messages_count']} сообщений
  и отбрасывает {sliding['dropped_messages']}. При небольшом N в контекст может попасть
  только хвост ветки, а ранние факты ствола потеряются.
- **Sticky facts** сохраняет {sticky['facts_count']} ключевых фактов
  при {_num(sticky['tokens'])} токенах. Это дешевле полной истории, но детали
  и формулировки, не попавшие в facts, исчезают.
- **Summary блоки** передают {summary['summaries_count']} summary
  на {_num(summary['tokens'])} токенов: ствол и ветка сжаты, поэтому общий смысл
  сохраняется, а точные детали можно потерять.
- **Вывод для ветвления:** для вопросов, где важны факты из ствола и выбранной ветки,
  надёжнее полная история или sticky facts; summary — компромисс по стоимости;
  sliding window подходит только для вопросов о последних сообщениях ветки.
""",
        unsafe_allow_html=False,
    )
