"""Страница «Способы рассуждений» — урок 03 внутри общего интерфейса."""

from __future__ import annotations

import json
import time

import httpx
import pandas as pd
import streamlit as st

from common import (
    PROVIDER_LABELS,
    REASONING_API,
    REASONING_LABELS,
    nixie_digits,
    post_stream,
    provider_badges,
    selectable_models,
)

DEFAULT_TASK = (
    "В корзине 5 яблок, 3 груши и 2 апельсина. Два яблока съели, "
    "а потом добавили 4 груши. Сколько всего фруктов в корзине?"
)



@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {"health": None, "models": [], "strategies": [], "council": {}, "providers": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{REASONING_API}/api/health").json()
            result["models"] = client.get(f"{REASONING_API}/api/models").json()
            result["strategies"] = client.get(f"{REASONING_API}/api/strategies").json()
            result["council"] = client.get(f"{REASONING_API}/api/council").json()
            result["providers"] = client.get(f"{REASONING_API}/api/providers/status").json()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


#: Задачи на логику для сравнения стратегий: от простой арифметики до головоломки
COMPARE_TASKS: dict[str, dict[str, str]] = {
    "extra low": {
        "title": "Арифметика в одно действие",
        "text": "Сколько будет 17 × 4?",
        "answer": "68",
    },
    "low": {
        "title": "Корзина с фруктами",
        "text": (
            "В корзине 5 яблок, 3 груши и 2 апельсина. Два яблока съели, "
            "а потом добавили 4 груши. Сколько всего фруктов в корзине?"
        ),
        "answer": "12 фруктов",
    },
    "medium": {
        "title": "Поезд с задержкой",
        "text": (
            "Поезд отправляется в 14:35 и едет 3 часа 50 минут, но на одной станции "
            "стоит ещё 25 минут сверх графика. Во сколько он прибудет и сколько всего "
            "минут займёт дорога?"
        ),
        "answer": "18:50, 255 минут",
    },
    "high": {
        "title": "Склад и проценты",
        "text": (
            "На складе 240 коробок. В первый день вывезли 3/8 всех коробок, во второй — "
            "40% остатка, в третий — половину того, что осталось после второго дня. "
            "Сколько коробок осталось на складе?"
        ),
        "answer": "45 коробок",
    },
    "extra high": {
        "title": "12 монет на чашечных весах",
        "text": (
            "Есть 12 одинаковых на вид монет, одна из них фальшивая: она легче или тяжелее "
            "настоящей, но неизвестно, в какую сторону. Есть чашечные весы без гирь. "
            "За какое минимальное число взвешиваний можно гарантированно найти фальшивую "
            "монету и определить, легче она или тяжелее? Объясните схему."
        ),
        "answer": "3 взвешивания",
    },
}

VERDICT_ICONS = {"ok": "✅", "wrong": "❌", "unclear": "❓", "—": "·"}

DEFAULT_LEVEL = "low"
DEFAULT_TASK = COMPARE_TASKS[DEFAULT_LEVEL]["text"]


def _apply_council_task() -> None:
    """Callback: подставить текст задачи в поле совета экспертов."""
    level = st.session_state.get("rs_council_level")
    task = COMPARE_TASKS.get(level or "")
    if task:
        st.session_state["rs_council_task"] = task["text"]


def _apply_cross_task() -> None:
    """Callback: подставить текст задачи во вкладку перекрёстной проверки."""
    level = st.session_state.get("rs_cross_level")
    task = COMPARE_TASKS.get(level or "")
    if task:
        st.session_state["rs_cross_task"] = task["text"]


def _apply_compare_task() -> None:
    """Callback: подставить текст выбранной по сложности задачи."""
    level = st.session_state.get("rs_compare_level")
    task = COMPARE_TASKS.get(level or "")
    if task:
        st.session_state["rs_compare_task"] = task["text"]


#: Группа экспертов: роль = способ рассуждения + reasoning + температура
MANUAL = "Вручную"
EXPERTS: dict[str, dict] = {
    MANUAL: {},
    "Аналитик": {
        "description": "Разбирает данные по шагам и ничего не пропускает",
        "strategy": "cot",
        "reasoning": "high",
        "temperature": 0.2,
    },
    "Инженер": {
        "description": "Строит решение по плану и опирается на факты",
        "strategy": "plan_solve",
        "reasoning": "medium",
        "temperature": 0.1,
    },
    "Критик": {
        "description": "Ищет слабые места и проверяет выводы",
        "strategy": "self_check",
        "reasoning": "low",
        "temperature": 0.4,
    },
    "Менеджер": {
        "description": "Коротко и по делу, без рассуждений",
        "strategy": "direct",
        "reasoning": "none",
        "temperature": 0.7,
    },
}


def _apply_expert() -> None:
    """Callback: подставить стратегию, reasoning и температуру выбранной роли."""
    expert = EXPERTS.get(st.session_state.get("rs_expert") or MANUAL) or {}
    if not expert:
        return
    st.session_state["rs_strategy"] = expert["strategy"]
    st.session_state["rs_temperature"] = float(expert["temperature"])

    levels = list(st.session_state.get("rs_levels") or [])
    model_id = st.session_state.get("rs_current_model")
    if levels and model_id:
        level = str(expert["reasoning"])
        if level not in levels:
            level = "none" if "none" in levels else levels[0]
        st.session_state[f"rs_reasoning::{model_id}"] = level


def _nixie_slider(label, *, min_value, max_value, step, default, key, fmt, help=None):
    readout = st.empty()
    kwargs = dict(label=label, min_value=min_value, max_value=max_value, step=step, key=key, help=help)
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


def _render_message(message: dict) -> None:
    with st.chat_message(message["role"], avatar="🧑" if message["role"] == "user" else "🤖"):
        if message.get("reasoning"):
            title = f"🧠 {message.get('reasoning_title') or 'Рассуждение'}"
            with st.expander(title, expanded=False):
                st.markdown(f'<div class="reasoning-text">{message["reasoning"]}</div>',
                            unsafe_allow_html=True)
        st.markdown(message.get("content") or "…")
        if message.get("meta"):
            st.markdown(f'<div class="meta-line">{message["meta"]}</div>', unsafe_allow_html=True)


def render() -> None:
    backend = load_backend()

    if backend["error"]:
        st.error("API урока 03 недоступен")
        st.caption(backend["error"])
        st.caption('Поднять: `cd "Lesson 03/app" && docker compose up -d`')
        st.stop()

    models = backend["models"]
    strategies = backend["strategies"]
    strategy_by_id = {item["id"]: item for item in strategies}

    st.session_state.setdefault("ui_model", None)
    st.session_state.setdefault("rs_history", [])
    st.session_state.setdefault("rs_compare", None)
    st.session_state.setdefault("rs_council", None)

    # mock оставляем только как аварийный вариант, если реальных моделей нет
    mock_models = [m for m in models if m["provider"] == "mock"]
    api_models = [m for m in models if m["provider"] != "mock"]
    models = selectable_models(models)
    current = next((m for m in models if m["id"] == st.session_state.ui_model), None)
    if current is None:
        current = models[0]
        st.session_state.ui_model = current["id"]

    levels = list(current.get("reasoning_levels") or [])
    st.session_state["rs_levels"] = levels
    st.session_state["rs_current_model"] = current["id"]

    # смена модели не должна терять уровень reasoning, заданный экспертом
    active_expert = EXPERTS.get(st.session_state.get("rs_expert") or MANUAL) or {}
    reasoning_key = f"rs_reasoning::{current['id']}"
    if active_expert and levels and reasoning_key not in st.session_state:
        wanted = str(active_expert["reasoning"])
        st.session_state[reasoning_key] = (
            wanted if wanted in levels else ("none" if "none" in levels else levels[0])
        )

    with st.sidebar:
        health = backend["health"] or {}
        st.markdown(
            provider_badges(backend.get("providers") or []), unsafe_allow_html=True
        )

        with st.popover(f"⚙  {current['label']}  ▾", use_container_width=True):
            by_provider: dict[str, list[dict]] = {}
            for option in models:
                by_provider.setdefault(option["provider"], []).append(option)
            for provider, items in by_provider.items():
                caption = PROVIDER_LABELS.get(provider, provider)
                if provider == "mock":
                    caption += " — ключ не настроен"
                st.caption(caption)
                for option in items:
                    mark = "✅ " if option["id"] == current["id"] else ""
                    if st.button(f"{mark}{option['label']}", key=f"rs_pick::{option['id']}",
                                 use_container_width=True):
                        st.session_state.ui_model = option["id"]
                        st.rerun()

        st.divider()

        # --- группа экспертов ---------------------------------------------------
        st.selectbox(
            "Группа экспертов",
            options=list(EXPERTS),
            key="rs_expert",
            on_change=_apply_expert,
            help="Роль задаёт способ рассуждения, уровень reasoning и температуру",
        )
        chosen_expert = EXPERTS.get(st.session_state.get("rs_expert") or MANUAL) or {}
        if chosen_expert:
            st.caption(f"{chosen_expert['description']} · reasoning {chosen_expert['reasoning']}"
                       f" · temp {float(chosen_expert['temperature']):.1f}")
        else:
            st.caption("Ручной режим: стратегия, reasoning и температура задаются отдельно")

        st.divider()

        # --- способ рассуждения -------------------------------------------------
        strategy_id = st.radio(
            "Способ рассуждения",
            options=[item["id"] for item in strategies],
            format_func=lambda sid: strategy_by_id[sid]["label"],
            key="rs_strategy",
            help="Меняет system-промпт: как именно модель должна думать",
        )
        spec = strategy_by_id[strategy_id]
        st.caption(spec["description"])
        with st.expander("System-промпт стратегии", expanded=False):
            st.code(spec["system_prompt"], language="text")

        st.divider()

        # --- фильтры: только температура, reasoning и лимит токенов -------------
        temperature = _nixie_slider("Температура", min_value=0.0, max_value=2.0, step=0.1,
                                    default=0.3, key="rs_temperature", fmt=lambda v: f"{v:.1f}",
                                    help="Выше — разнообразнее и «смелее», ниже — стабильнее")

        if levels:
            reasoning = st.selectbox("Reasoning", options=levels,
                                     index=levels.index("none") if "none" in levels else 0,
                                     format_func=lambda k: REASONING_LABELS.get(k, k),
                                     key=f"rs_reasoning::{current['id']}",
                                     help="Встроенные «размышления» модели — отдельно от стратегии")
        else:
            reasoning = "off"
            st.caption("Reasoning: модель без встроенных рассуждений")

        max_tokens = _nixie_slider("Max tokens", min_value=100, max_value=10_000, step=100,
                                   default=1_000, key="rs_max_tokens",
                                   fmt=lambda v: f"{int(v):05d}",
                                   help="Предел длины ответа: до 10 000 токенов")

    st.markdown("## Способы рассуждений")

    tab_chat, tab_compare, tab_council, tab_cross = st.tabs(
        [
            "Способы рассуждений",
            "Сравнение стратегий",
            "Совет экспертов",
            "Перекрёстная проверка",
        ]
    )

    # -- чат со стратегией --------------------------------------------------------
    with tab_chat:
        st.markdown(f'<div class="strategy-hint">Способ: <b>{spec["label"]}</b> — {spec["description"]}</div>',
                    unsafe_allow_html=True)

        for message in st.session_state.rs_history:
            _render_message(message)

        question = st.chat_input("Спроси что-нибудь…")
        if question:
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in st.session_state.rs_history
            ] + [{"role": "user", "content": question}]
            st.session_state.rs_history.append({"role": "user", "content": question})
            _render_message(st.session_state.rs_history[-1])

            payload = {
                "model": current["id"],
                "messages": history,
                "strategy": strategy_id,
                "temperature": temperature,
                "reasoning": reasoning,
                "max_tokens": max_tokens,
            }
            started = time.perf_counter()
            with st.chat_message("assistant", avatar="🤖"):
                reasoning_box = st.expander("🧠 Модель думает…", expanded=True).empty()
                answer_box = st.empty()
                meta_box = st.empty()
                buffer, native = "", ""
                result, error = None, None
                for event, data in post_stream("/api/chat", payload, REASONING_API):
                    if event == "start":
                        answer_box.caption(f"{spec['label']} · {data.get('model')}")
                        buffer = ""
                    elif event == "reasoning":
                        native += data.get("text", "")
                        reasoning_box.markdown(f'<div class="reasoning-text">{native}</div>',
                                               unsafe_allow_html=True)
                    elif event == "delta":
                        buffer += data.get("text", "")
                        answer_box.markdown(buffer)
                    elif event == "result":
                        result = data
                    elif event == "error":
                        error = data

            if error:
                st.error(error.get("message", "ошибка"))
                st.caption(f"kind: `{error.get('kind', '?')}`")
            elif result:
                parts_reasoning = result.get("reasoning_part") or result.get("native_reasoning") or ""
                answer = result.get("answer_part") or result.get("raw_text") or ""
                elapsed = result.get("elapsed_ms") or int((time.perf_counter() - started) * 1000)
                tokens = (result.get("usage") or {}).get("completion_tokens")
                meta = (f"{result['strategy_label']} · {result['model']} · temp {temperature:.1f} · "
                        f"reasoning {reasoning} · {elapsed} ms")
                if tokens:
                    meta += f" · {tokens} tok"
                if result.get("truncated"):
                    meta += " · ⚠️ обрезано по max_tokens"
                st.session_state.rs_history.append({
                    "role": "assistant",
                    "content": answer,
                    "reasoning": parts_reasoning,
                    "reasoning_title": spec.get("reasoning_hint") or "Рассуждение",
                    "meta": meta,
                })
                if result.get("truncated"):
                    st.error(
                        f"Ответ оборван лимитом max_tokens = {result.get('max_tokens')}: "
                        "увеличьте «Max tokens» и повторите."
                    )
                st.rerun()

    # -- сравнение стратегий ------------------------------------------------------
    with tab_compare:
        st.caption("Одна и та же задача прогоняется через все стратегии. Смотрите на токены, "
                   "время и на то, сходится ли итоговый ответ.")
        st.session_state.setdefault("rs_compare_task", DEFAULT_TASK)
        level_kwargs = dict(
            label="Задача на логику",
            options=list(COMPARE_TASKS),
            format_func=lambda key: f"{key} · {COMPARE_TASKS[key]['title']}",
            key="rs_compare_level",
            on_change=_apply_compare_task,
            help="Сложность задачи: от простой арифметики до классической головоломки",
        )
        if "rs_compare_level" not in st.session_state:
            # по умолчанию — та же задача, что подставлена в поле text
            level_kwargs["index"] = list(COMPARE_TASKS).index(DEFAULT_LEVEL)
        level = st.selectbox(**level_kwargs)
        task = st.text_area("Задача", height=110, key="rs_compare_task")
        reference = COMPARE_TASKS.get(level, {}).get("answer", "")
        if reference:
            with st.expander("Эталонный ответ", expanded=False):
                st.caption(reference)
        if st.button("⚖  Сравнить стратегии", type="primary", key="rs_compare_run"):
            if not task.strip():
                st.warning("Нужна задача")
            else:
                # по одному запросу на стратегию: видно прогресс и падение одной
                # стратегии не убивает всё сравнение
                order = [item["id"] for item in strategies]
                collected: list[dict] = []
                progress = st.progress(0.0, text="Сравниваю стратегии…")
                for index, strategy_id in enumerate(order, start=1):
                    label = strategy_by_id[strategy_id]["label"]
                    progress.progress((index - 1) / len(order), text=f"{label}: запрос…")
                    try:
                        with httpx.Client(timeout=180.0) as client:
                            response = client.post(
                                f"{REASONING_API}/api/compare",
                                json={
                                    "model": current["id"],
                                    "prompt": task.strip(),
                                    "strategies": [strategy_id],
                                    "temperature": temperature,
                                    "reasoning": reasoning,
                                    "max_tokens": max_tokens,
                                },
                            )
                            response.raise_for_status()
                            collected.extend(response.json())
                    except Exception as exc:  # noqa: BLE001
                        collected.append({
                            "strategy": strategy_id,
                            "strategy_label": label,
                            "error": f"{type(exc).__name__}: {exc}",
                        })
                    progress.progress(index / len(order), text=f"{label}: готово")
                progress.empty()
                st.session_state.rs_compare = collected
                st.toast("Сравнение готово", icon="⚖")

        rows = st.session_state.rs_compare
        if rows:
            ok_rows = [item for item in rows if not item.get("error")]
            if any(item.get("truncated") for item in ok_rows):
                st.warning("Часть ответов обрезана лимитом max_tokens — увеличьте «Max tokens», "
                           "иначе сравниваются неполные рассуждения.")
            st.dataframe(
                [
                    {
                        "стратегия": item.get("strategy_label") or item["strategy"],
                        "токенов": (item.get("usage") or {}).get("completion_tokens"),
                        "мс": item.get("elapsed_ms"),
                        "рассуждение, симв.": len(item.get("reasoning") or ""),
                        "finish": item.get("finish_reason") or "—",
                        "лимит": "обрезан" if item.get("truncated") else "ок",
                        "ответ": (item.get("answer") or item.get("error") or "—")[:120],
                    }
                    for item in rows
                ],
                use_container_width=True,
                hide_index=True,
            )
            if len(ok_rows) > 1:
                answers = {item.get("answer", "").strip() for item in ok_rows}
                if len(answers) == 1:
                    st.success("Все стратегии дали одинаковый итоговый ответ — задача слишком простая, "
                               "чтобы увидеть разницу.")
                else:
                    st.info(f"Стратегии разошлись: {len(answers)} разных ответов из {len(ok_rows)}.")
            for item in rows:
                title = item.get("strategy_label") or item["strategy"]
                with st.expander(f"{title}"):
                    if item.get("error"):
                        st.error(item["error"])
                        continue
                    if item.get("reasoning"):
                        st.markdown(f'<div class="reasoning-text">{item["reasoning"]}</div>',
                                    unsafe_allow_html=True)
                    st.markdown("**Ответ:** " + (item.get("answer") or "—"))
        else:
            st.caption("Нажмите «Сравнить стратегии» — прогон идёт по очереди через все способы.")

    # -- совет экспертов ----------------------------------------------------------
    with tab_council:
        council_meta = backend.get("council") or {}
        solvers = council_meta.get("solvers") or []
        reviewers = council_meta.get("reviewers") or []
        st.caption(
            "Сначала отвечает группа: " + ", ".join(item["label"] for item in solvers) +
            ". Потом ответы проверяет другая группа: " +
            ", ".join(item["label"] for item in reviewers) + ". "
            "Каждый участник работает со своей ролью, стратегией и reasoning."
        )

        st.caption(
            f"Лимит ответа каждого участника — «Max tokens» в сайдбаре: {int(max_tokens)}. "
            "Если ответ не уместится, в таблице будет пометка «обрезан»."
        )

        st.session_state.setdefault("rs_council_task", DEFAULT_TASK)
        council_kwargs: dict = dict(
            label="Задача на логику",
            options=list(COMPARE_TASKS),
            format_func=lambda key: f"{key} · {COMPARE_TASKS[key]['title']}",
            key="rs_council_level",
            on_change=_apply_council_task,
            help="Сложность задачи для совета экспертов",
        )
        if "rs_council_level" not in st.session_state:
            council_kwargs["index"] = list(COMPARE_TASKS).index(DEFAULT_LEVEL)
        council_level = st.selectbox(**council_kwargs)
        council_task = st.text_area("Задача", height=110, key="rs_council_task")
        council_reference = COMPARE_TASKS.get(council_level, {}).get("answer", "")
        if council_reference:
            st.caption(f"Эталон: {council_reference}")

        if st.button("🧑‍⚖️  Собрать совет", type="primary", key="rs_council_run"):
            if not council_task.strip():
                st.warning("Нужна задача")
            else:
                council_answers: list[dict] = []
                council_reviews: list[dict] = []
                total = len(solvers) + len(reviewers)
                progress = st.progress(0.0, text="Готовлю ответы экспертов…")
                step = 0

                for member in solvers:
                    step += 1
                    progress.progress((step - 1) / total, text=f"{member['label']}: отвечает…")
                    try:
                        with httpx.Client(timeout=240.0) as client:
                            response = client.post(
                                f"{REASONING_API}/api/council/answer",
                                json={
                                    "model": current["id"],
                                    "prompt": council_task.strip(),
                                    "expert": member["id"],
                                    "max_tokens": max_tokens,
                                },
                            )
                            response.raise_for_status()
                            council_answers.append(response.json())
                    except Exception as exc:  # noqa: BLE001
                        council_answers.append({
                            "expert": member["id"], "label": member["label"],
                            "answer": "", "error": f"{type(exc).__name__}: {exc}",
                        })
                    progress.progress(step / total, text=f"{member['label']}: готово")

                if council_answers:
                    for member in reviewers:
                        step += 1
                        progress.progress((step - 1) / total, text=f"{member['label']}: проверяет…")
                        try:
                            with httpx.Client(timeout=240.0) as client:
                                response = client.post(
                                    f"{REASONING_API}/api/council/review",
                                    json={
                                        "model": current["id"],
                                        "prompt": council_task.strip(),
                                        "reviewer": member["id"],
                                        "max_tokens": max_tokens,
                                        "answers": [
                                            {
                                                "id": item.get("expert"),
                                                "label": item.get("label"),
                                                "answer": item.get("answer"),
                                            }
                                            for item in council_answers
                                        ],
                                    },
                                )
                                response.raise_for_status()
                                council_reviews.append(response.json())
                        except Exception as exc:  # noqa: BLE001
                            council_reviews.append({
                                "reviewer": member["id"], "label": member["label"],
                                "verdicts": [], "error": f"{type(exc).__name__}: {exc}",
                            })
                        progress.progress(step / total, text=f"{member['label']}: готово")

                progress.empty()
                st.session_state.rs_council = {
                    "task": council_task.strip(),
                    "level": council_level,
                    "reference": council_reference,
                    "answers": council_answers,
                    "reviews": council_reviews,
                }
                st.toast("Совет собран", icon="🧑‍⚖️")

        council = st.session_state.rs_council
        if council:
            cut = [item for item in council["answers"] if item.get("truncated")]
            if cut:
                st.warning(
                    "Ответы " + ", ".join(item.get("label") or item["expert"] for item in cut) +
                    " обрезаны лимитом max_tokens: рассуждение съело бюджет, текста не осталось. "
                    "Увеличьте «Max tokens» и соберите совет заново."
                )
            st.markdown("### Ответы группы")
            st.dataframe(
                [
                    {
                        "эксперт": item.get("label") or item["expert"],
                        "стратегия": item.get("strategy") or "—",
                        "токенов": (item.get("usage") or {}).get("completion_tokens"),
                        "мс": item.get("elapsed_ms"),
                        "лимит": "обрезан" if item.get("truncated") else "ок",
                        "ответ": (item.get("answer") or item.get("error") or "—")[:120],
                    }
                    for item in council["answers"]
                ],
                use_container_width=True,
                hide_index=True,
            )

            st.markdown("### Проверка другой группой")
            verdict_matrix = []
            for answer in council["answers"]:
                row = {"эксперт": answer.get("label") or answer["expert"]}
                for review in council["reviews"]:
                    mark = "—"
                    for verdict in review.get("verdicts") or []:
                        if verdict.get("expert") == answer["expert"]:
                            mark = verdict.get("verdict", "unclear")
                    row[review.get("label") or review["reviewer"]] = VERDICT_ICONS.get(mark, "·")
                verdict_matrix.append(row)
            # статическая таблица: canvas-грид с эмодзи иногда остаётся пустым
            st.table(pd.DataFrame(verdict_matrix))
            if council.get("reference"):
                st.caption(f"Эталон: {council['reference']} · "
                           "✅ верно · ❌ ошибка · ❓ спорно · · нет вердикта")

            for review in council["reviews"]:
                title = f"{review.get('label') or review['reviewer']}: итог «{review.get('final_answer') or '—'}»"
                with st.expander(title):
                    if review.get("error"):
                        st.error(review["error"])
                        continue
                    if review.get("finish_reason") == "length":
                        st.warning(
                            "Разбор проверяющего оборван лимитом max_tokens — вердикты могут быть "
                            "неполными."
                        )
                    if not review.get("parsed"):
                        st.caption("Ответ проверяющего не разобран как JSON — показываю как есть.")
                    for verdict in review.get("verdicts") or []:
                        st.markdown(f"{VERDICT_ICONS.get(verdict['verdict'], '·')} "
                                    f"**{verdict['expert']}** — {verdict.get('comment') or '—'}")
                    with st.expander("Сырой ответ проверяющего", expanded=False):
                        st.code(review.get("raw_text") or "—", language="json")

    # -- перекрёстная проверка: одна модель отвечает, другая проверяет ------------
    with tab_cross:
        st.caption(
            "Задачу решает выбранная модель, а проверяет её другая модель — "
            "независимо от ролей совета экспертов."
        )

        st.session_state.setdefault("rs_cross_task", DEFAULT_TASK)
        cross_kwargs: dict = dict(
            label="Задача на логику",
            options=list(COMPARE_TASKS),
            format_func=lambda key: f"{key} · {COMPARE_TASKS[key]['title']}",
            key="rs_cross_level",
            on_change=_apply_cross_task,
            help="Готовые задачи: от простой арифметики до головоломки",
        )
        if "rs_cross_level" not in st.session_state:
            cross_kwargs["index"] = list(COMPARE_TASKS).index(DEFAULT_LEVEL)
        cross_level = st.selectbox(**cross_kwargs)
        cross_task = st.text_area("Задача", height=110, key="rs_cross_task")
        cross_reference = COMPARE_TASKS.get(cross_level, {}).get("answer", "")
        if cross_reference:
            st.caption(f"Эталон: {cross_reference}")

        titles = {item["id"]: item["label"] for item in models}
        ids = list(titles)
        col_answer, col_check = st.columns(2)

        with col_answer:
            solver_kwargs: dict = dict(
                label="Модель отвечает",
                options=ids,
                format_func=lambda mid: f"{titles[mid]} · {mid}",
                key="rs_cross_solver",
            )
            if "rs_cross_solver" not in st.session_state:
                solver_kwargs["index"] = ids.index(current["id"])
            solver_id = st.selectbox(**solver_kwargs)

        with col_check:
            others = [mid for mid in ids if mid != solver_id] or ids
            if st.session_state.get("rs_cross_reviewer") not in others:
                st.session_state["rs_cross_reviewer"] = others[0]
            reviewer_id = st.selectbox(
                "Модель проверяет",
                options=others,
                format_func=lambda mid: f"{titles[mid]} · {mid}",
                key="rs_cross_reviewer",
            )

        cross_max_tokens = _nixie_slider("Max tokens", min_value=100, max_value=10_000, step=100,
                                         default=1_500, key="rs_cross_max_tokens",
                                         fmt=lambda v: f"{int(v):05d}",
                                         help="Предел ответа для обеих моделей")

        if st.button("🔍  Проверить ответ", type="primary", key="rs_cross_run"):
            if not cross_task.strip():
                st.warning("Нужна задача")
            else:
                with st.spinner("Модель отвечает, вторая проверяет…"):
                    try:
                        response = httpx.post(
                            f"{REASONING_API}/api/cross-check",
                            json={
                                "prompt": cross_task,
                                "requirement": cross_level,
                                "solver_model": solver_id,
                                "reviewer_model": reviewer_id,
                                "temperature": 0.2,
                                "max_tokens": int(cross_max_tokens),
                            },
                            timeout=300.0,
                        )
                        response.raise_for_status()
                        st.session_state["rs_cross_result"] = response.json()
                    except Exception as exc:  # noqa: BLE001 - показываем в UI
                        st.session_state["rs_cross_result"] = None
                        st.error(f"Не удалось получить ответ: {type(exc).__name__}: {exc}")

        cross_result = st.session_state.get("rs_cross_result")
        if cross_result:
            cross_answer = cross_result.get("answer") or {}
            cross_review = cross_result.get("review") or {}
            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("### Ответ")
                st.caption(
                    f"{cross_answer.get('label', '—')} · {cross_answer.get('elapsed_ms', 0)} мс · "
                    f"{cross_answer.get('usage', {}).get('completion_tokens', 0)} ток"
                )
                st.markdown(cross_answer.get("answer") or "—")
                if cross_answer.get("truncated"):
                    st.warning(
                        "Ответ не уместился в лимит max_tokens = "
                        f"{int(cross_max_tokens)} — текст оборван, итог может быть неполным. "
                        "Увеличьте «Max tokens» и повторите."
                    )
                if cross_answer.get("reasoning"):
                    with st.expander("Рассуждение модели", expanded=False):
                        st.markdown(cross_answer["reasoning"])

            with col_right:
                st.markdown("### Проверка")
                st.caption(
                    f"{cross_review.get('label', '—')} · {cross_review.get('elapsed_ms', 0)} мс"
                )
                if cross_review.get("parsed"):
                    for verdict in cross_review.get("verdicts") or []:
                        st.markdown(
                            f"{VERDICT_ICONS.get(verdict['verdict'], '·')} "
                            f"**{cross_answer.get('label', 'ответ')}** — "
                            f"{verdict.get('comment') or '—'}"
                        )
                else:
                    st.caption("Проверяющий не вернул JSON со схемой — показываю как есть.")
                if cross_review.get("finish_reason") == "length":
                    st.warning(
                        "Разбор проверяющего оборван лимитом max_tokens — вердикты могут быть "
                        "неполными. Увеличьте «Max tokens» и повторите."
                    )
                if cross_review.get("final_answer"):
                    st.markdown(f"**Итог проверки:** {cross_review['final_answer']}")
                with st.expander("Сырой ответ проверяющего", expanded=False):
                    st.code(cross_review.get("raw_text") or "—", language="json")

    with st.sidebar:
        st.divider()
        if st.button("Очистить чат", use_container_width=True, key="rs_clear"):
            st.session_state.rs_history = []
            st.session_state.rs_compare = None
            st.rerun()
        if st.session_state.rs_history:
            with st.expander("Что отправлено в последнем запросе", expanded=False):
                last = [m for m in st.session_state.rs_history if m["role"] == "user"][-1]
                st.code(json.dumps({"system": spec["system_prompt"], "user": last["content"]},
                                   ensure_ascii=False, indent=2), language="json")
