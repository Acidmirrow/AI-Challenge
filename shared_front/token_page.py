"""Страница «Работа с токенами» — урок 08.

Показывает оценку токенов, бюджет контекстного окна, резерв под ответ,
предпросмотр токенов и обрезку по границе токена.
"""

from __future__ import annotations

from html import escape

import httpx
import pandas as pd
import streamlit as st

from common import TOKEN_API

DEFAULT_TEXT = (
    "Контекст модели — это весь текст, который она обрабатывает за один запрос. "
    "Чем длиннее история диалога, тем меньше места остаётся под новый ответ."
)


@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {"health": None, "models": [], "presets": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{TOKEN_API}/api/health").json()
            result["models"] = client.get(f"{TOKEN_API}/api/models").json()
            result["presets"] = client.get(f"{TOKEN_API}/api/presets").json()["presets"]
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _analyze(text: str, model: str, reserve: int) -> dict:
    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            f"{TOKEN_API}/api/analyze",
            json={"text": text, "model": model, "output_reserve": reserve},
        )
    response.raise_for_status()
    return response.json()


def _set_text(value: str) -> None:
    st.session_state["t08_text"] = value


def _money(value: float) -> str:
    if not value:
        return "$0"
    return f"${value:.8f}"


def _dialogue(model: str, window: int, turns: int, user_tokens: int, assistant_tokens: int) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{TOKEN_API}/api/dialogue",
            json={
                "model": model,
                "turns": turns,
                "user_tokens": user_tokens,
                "assistant_tokens": assistant_tokens,
                "demo_window": window,
            },
        )
    response.raise_for_status()
    return response.json()


def _compare(text: str, model: str, reserve: int, window: int) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{TOKEN_API}/api/compare",
            json={
                "base_text": text[:20_000],
                "model": model,
                "output_reserve": reserve,
                "demo_window": window,
            },
        )
    response.raise_for_status()
    return response.json()


def render() -> None:
    backend = load_backend()
    models = backend["models"] or []
    if not models:
        st.error("API урока 08 недоступен или не вернул модели")
        if backend["error"]:
            st.caption(backend["error"])
        return

    st.markdown(
        """<style>
        .token-chips { display: flex; flex-wrap: wrap; gap: .22rem; margin: .4rem 0; }
        .token-chip { font-family: ui-monospace, monospace; font-size: .68rem;
                      padding: .08rem .28rem; border: 1px solid var(--border);
                      border-radius: .3rem; opacity: .78; }
        .token-chip b { opacity: .35; margin-right: .18rem; font-weight: 400; }
        </style>""",
        unsafe_allow_html=True,
    )

    st.session_state.setdefault("t08_text", DEFAULT_TEXT)
    by_id = {item["id"]: item for item in models}

    with st.sidebar:
        st.markdown("#### Токены")
        model_id = st.selectbox(
            "Модель",
            options=[item["id"] for item in models],
            format_func=lambda value: by_id[value]["label"],
            key="t08_model",
        )
        model = by_id[model_id]
        st.caption(
            f"Контекст: {model['context_window']:,} токенов · "
            f"ответ до {model['output_max']:,}".replace(",", " ")
        )
        st.caption(
            f"Тариф: ${model['input_price_per_1m']:.2f} / 1M вход · "
            f"${model['output_price_per_1m']:.2f} / 1M выход"
        )
        max_reserve = min(int(model["output_max"]), 20_000)
        reserve = st.slider(
            "Резерв под ответ",
            min_value=0,
            max_value=max_reserve,
            value=min(1_000, max_reserve),
            step=100,
            key="t08_reserve",
            help="Сколько токенов оставить для ответа модели",
        )
        demo_window = st.slider(
            "Демо-окно для сравнения",
            min_value=512,
            max_value=32_000,
            value=8_000,
            step=512,
            key="t08_window",
            help="Ограничение окна для наглядного сравнения трёх контекстов",
        )
        st.caption("Параметры роста диалога")
        turns = st.slider("Ходов", 1, 50, 30, key="t08_turns")
        user_tokens = st.slider("Токенов в сообщении", 1, 500, 100, key="t08_user_tokens")
        assistant_tokens = st.slider("Токенов в ответе", 1, 1_000, 200, key="t08_assistant_tokens")
        st.divider()
        st.caption("Пресеты текста:")
        for preset in backend["presets"]:
            st.button(
                preset["label"],
                key=f"t08_preset::{preset['id']}",
                use_container_width=True,
                on_click=_set_text,
                args=(preset["text"],),
            )

    st.markdown("## Работа с токенами")
    st.caption(
        "Оценка токенов, бюджет контекстного окна и обрезка текста. "
        "Токенизация учебная: слова и пунктуация считаются отдельными единицами."
    )

    text = st.text_area(
        "Текст",
        key="t08_text",
        height=210,
        placeholder="Вставь текст, чтобы оценить его стоимость в токенах…",
    )

    if not text:
        st.info("Введи текст или выбери пресет в сайдбаре.")
        return

    try:
        result = _analyze(text, model_id, reserve)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось посчитать токены: {exc}")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Символов", f"{result['chars']:,}".replace(",", " "))
    m2.metric("Слов", f"{result['words']:,}".replace(",", " "))
    m3.metric("Токенов", f"{result['tokens']:,}".replace(",", " "))
    m4.metric("Токенов / слово", result["tokens_per_word"])

    st.markdown("#### Бюджет контекста")
    available = max(1, result["available"])
    ratio = min(1.0, result["tokens"] / available)
    st.progress(ratio)
    st.caption(
        f"Окно {result['context_window']:,} · резерв {result['output_reserve']:,} · "
        f"доступно {result['available']:,} · текст {result['tokens']:,}".replace(",", " ")
    )

    st.markdown("#### Стоимость")
    c1, c2, c3 = st.columns(3)
    c1.metric("Вход", _money(result["input_cost"]))
    c2.metric("Резерв ответа", _money(result["output_cost"]))
    c3.metric("Итого максимум", _money(result["total_cost"]))
    st.caption(
        f"Ориентир по тарифу ${result['input_price_per_1m']:.2f} / 1M вход · "
        f"${result['output_price_per_1m']:.2f} / 1M выход (USD). "
        "Стоимость ответа рассчитана на весь резерв; фактический ответ может быть короче."
    )
    if not result["fits"]:
        st.caption(
            f"Стоимость входа посчитана по {result['kept_tokens']} помещающимся "
            f"токенам; полный текст стоил бы {_money(result['full_input_cost'])}."
        )

    if result["fits"]:
        st.success(
            f"Текст помещается. Таких текстов в доступное окно влезет: "
            f"{result['copies']}."
        )
    else:
        st.warning(
            f"Не помещается: превышение на {result['overflow']:,} токенов. "
            f"Ниже — вариант, обрезанный до {result['truncated_tokens']:,} токенов."
            .replace(",", " ")
        )
        with st.expander("Показать обрезанный текст", expanded=True):
            st.text(result["truncated_text"])

    st.markdown("#### Предпросмотр токенов")
    chips = "".join(
        f'<span class="token-chip"><b>{item["index"]}</b>{escape(item["text"])}</span>'
        for item in result["preview"]
    )
    st.markdown(f'<div class="token-chips">{chips}</div>', unsafe_allow_html=True)
    if result["preview_truncated"]:
        st.caption("Показаны первые 120 токенов.")

    with st.expander("Как считается"):
        st.markdown(
            "Слова и знаки пунктуации считаются отдельными токенами. "
            "Реальный BPE-токенизатор модели может дать другое число: "
            "для русского языка один токен часто короче слова. "
            "Точный расход виден в `usage` ответа модели."
        )

    st.markdown("## Сравнение трёх типов контекста")
    st.caption(
        "Минимальный текст, большой текст в пределах демо-окна и максимальный "
        "с превышением. Сравнение показывает зависимость токенов, стоимости "
        "и обрезки от объёма контекста."
    )
    if st.button("Сравнить три контекста", type="primary"):
        try:
            st.session_state["t08_compare"] = _compare(
                text, model_id, reserve, demo_window
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Не удалось сравнить контексты: {exc}")

    compared = st.session_state.get("t08_compare")
    if compared:
        st.caption(
            f"Модель: {compared['label']} · демо-окно: "
            f"{compared['demo_window']:,} · доступно: {compared['available']:,} токенов"
            .replace(",", " ")
        )
        rows = [
            {
                "Контекст": item["label"],
                "Символы": item["chars"],
                "Слова": item["words"],
                "Токены": item["tokens"],
                "Ток./слово": item["tokens_per_word"],
                "Вход $": _money(item["input_cost"]),
                "Ответ $": _money(item["output_cost"]),
                "Итого $": _money(item["total_cost"]),
                "Помещается": "да" if item["fits"] else f"нет (+{item['overflow']})",
            }
            for item in compared["contexts"]
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        chart = pd.DataFrame(
            {
                "Контекст": [item["label"] for item in compared["contexts"]],
                "Токены": [item["tokens"] for item in compared["contexts"]],
            }
        ).set_index("Контекст")
        st.bar_chart(chart)
        if not compared["contexts"][2]["fits"]:
            st.caption(
                "У максимального варианта стоимость входа посчитана только по "
                "помещающейся части; полный текст в запрос не отправляется."
            )
        st.markdown("#### Зависимости")
        for dependency in compared["dependencies"]:
            st.markdown(f"- {dependency}")
        with st.expander("Как построены три контекста", expanded=False):
            st.markdown(
                f"Минимальный — базовый текст. Большой — повторение базового текста "
                f"до ~70% доступного бюджета; максимальный — до ~120%, поэтому "
                f"он обрезается. Демо-окно {compared['demo_window']:,} токенов "
                f"используется вместо полного окна модели, чтобы сравнение было "
                f"наглядным.".replace(",", " ")
            )


    st.markdown("## Рост стоимости и токенов по диалогу")
    st.caption(
        "Каждый следующий ход снова отправляет всю историю. Посмотрим, как растут "
        "prompt-токены, стоимость и когда наступает переполнение окна."
    )
    if st.button("Рассчитать диалог", type="primary"):
        try:
            st.session_state["t08_dialogue"] = _dialogue(
                model_id, demo_window, turns, user_tokens, assistant_tokens
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Не удалось рассчитать диалог: {exc}")

    dialogue = st.session_state.get("t08_dialogue")
    if dialogue:
        st.caption(
            f"Модель: {dialogue['label']} · демо-окно: {dialogue['demo_window']:,} токенов"
            .replace(",", " ")
        )
        dial_rows = [
            {
                "Ход": item["turn"],
                "История": item["history_tokens"],
                "Prompt": item["prompt_tokens"],
                "Ответ": item["completion_tokens"],
                "Стоимость $": _money(item["total_cost"]),
                "Накоплено $": _money(item["cumulative_cost"]),
                "Помещается": "да" if item["fits"] else f"нет (+{item['overflow']})",
            }
            for item in dialogue["turns"]
        ]
        st.dataframe(pd.DataFrame(dial_rows), hide_index=True, use_container_width=True)
        growth = pd.DataFrame(
            {
                "Ход": [item["turn"] for item in dialogue["turns"]],
                "Prompt-токены": [item["prompt_tokens"] for item in dialogue["turns"]],
                "Накопленная стоимость": [item["cumulative_cost"] for item in dialogue["turns"]],
            }
        ).set_index("Ход")
        st.line_chart(growth[["Prompt-токены"]])
        st.line_chart(growth[["Накопленная стоимость"]])

        if dialogue["first_overflow_turn"]:
            st.error(
                f"Переполнение впервые на ходе {dialogue['first_overflow_turn']}: "
                f"превышение {dialogue['first_overflow_tokens']:,} токенов."
                .replace(",", " ")
            )
            st.caption(
                "Стоимость после первого переполнения — гипотетическая: такой "
                "prompt уже не отправится без обрезки или будет отклонён."
            )
        else:
            st.success("За выбранное число ходов окно не переполняется.")

        st.markdown("### Что ломается при переполнении")
        for risk in dialogue["risks"]:
            st.markdown(f"- {risk}")
        st.caption(
            "Чем длиннее диалог, тем больше prompt-токенов уходит на каждый ход; "
            "стоимость входа растёт, а свободное место в окне уменьшается."
        )
