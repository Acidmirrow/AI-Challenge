"""Страница «Сравнение моделей» — лаборатория урока 05.

Две вкладки: обычный чат с настройками из сайдбара и сравнение трёх моделей
разного размера на одной задаче. Модели отвечают параллельно, рядом с ответом
идут время, токены и стоимость, а внизу продвинутая модель разбирает результат.
"""

from __future__ import annotations

import httpx
import pandas as pd
import streamlit as st

from common import (
    MODEL_API,
    model_sidebar,
    post_stream,
)

#: Три слота выбора: размер модели → подпись и пояснение
TIER_SLOTS = (
    ("small", "Маленькая модель", "быстрая и дешёвая"),
    ("medium", "Модель побольше", "середина каталога"),
    ("large", "Большая модель", "самая тяжёлая и дорогая"),
)
TIER_LABELS = {"small": "маленькая", "medium": "средняя", "large": "большая"}

#: пункт выпадающего списка задач: прогнать все пять сразу
ALL_TASKS = "__all__"

COST_HINT = (
    "0 $ значит «бесплатный провайдер» или «цена не задана»: прайс лежит "
    "в `config/pricing.properties`."
)


@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {"health": None, "models": [], "tasks": [], "providers": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{MODEL_API}/api/health").json()
            result["models"] = client.get(f"{MODEL_API}/api/models").json()
            result["tasks"] = client.get(f"{MODEL_API}/api/tasks").json()
            result["providers"] = client.get(f"{MODEL_API}/api/providers/status").json()
    except Exception as exc:  # noqa: BLE001 - показываем в сайдбаре
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _models_for_ui(models: list[dict]) -> list[dict]:
    """Mock-модели прячем, если в каталоге есть настоящие."""
    real = [item for item in models if item.get("provider") != "mock"]
    return real or list(models)


def _money(run: dict) -> str:
    if not run.get("cost_usd"):
        return "0 $"
    return f"${run['cost_usd']:.6f}"


def _defaults(groups: dict[str, list[dict]], models: list[dict]) -> dict[str, str]:
    """Стартовые модели для трёх слотов — по одной на размер, без повторов."""
    used: set[str] = set()
    picked: dict[str, str] = {}
    for tier, _, _ in TIER_SLOTS:
        pool = groups.get(tier) or models
        candidate = next((item["id"] for item in pool if item["id"] not in used), None)
        if candidate is None:
            # в каталоге меньше трёх моделей — берём хоть что-то, дальше UI предупредит
            candidate = next((item["id"] for item in models if item["id"] not in used), pool[0]["id"])
        picked[tier] = candidate
        used.add(candidate)
    return picked


def _apply_task() -> None:
    """Callback: при смене задачи подставить её текст в промпт."""
    cache = st.session_state.get("m05_task_cache") or {}
    task = cache.get(st.session_state.get("m05_task") or "")
    if task:
        st.session_state["m05_prompt"] = task["text"]


# --- сайдбар -----------------------------------------------------------------


def _sidebar(models: list[dict], providers: list[dict]) -> dict:
    controls = model_sidebar(
        models,
        providers,
        st.session_state.get("ui_model"),
        prefix="m05",
    )
    current = controls["model"]
    temperature = controls["temperature"]
    reasoning = controls["reasoning"]
    max_tokens = controls["max_tokens"]

    st.divider()

    with st.expander("Системный промпт", expanded=False):
        system_prompt = st.text_area(
            "Инструкция",
            value="Ты — полезный ассистент. Отвечай по делу.",
            height=100,
            label_visibility="collapsed",
            key="m05_system_prompt",
        )

    if st.button("Очистить чат и сравнение", use_container_width=True, key="m05_clear"):
        st.session_state.m05_history = []
        st.session_state.m05_compare = None
        st.session_state.m05_analysis = None
        st.rerun()

    return {
        "model": current,
        "models": models,
        "temperature": float(temperature),
        "reasoning": reasoning,
        "max_tokens": int(max_tokens),
        "system_prompt": system_prompt,
    }


# --- вкладка 1: чат ----------------------------------------------------------


def _render_history() -> None:
    for message in st.session_state.m05_history:
        avatar = "🧑" if message["role"] == "user" else "🤖"
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"] or "—")
            if message.get("reasoning"):
                with st.expander("🧠 Размышления модели", expanded=False):
                    st.markdown(message["reasoning"])
            if message.get("meta"):
                st.markdown(f'<div class="meta-line">{message["meta"]}</div>',
                            unsafe_allow_html=True)


def _send_message(cfg: dict, prompt: str) -> None:
    st.session_state.m05_history.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)

    messages = []
    if cfg["system_prompt"].strip():
        messages.append({"role": "system", "content": cfg["system_prompt"].strip()})
    messages.extend(
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.m05_history
        if not item.get("failed")
    )
    payload = {
        "model": cfg["model"]["id"],
        "messages": messages,
        "temperature": cfg["temperature"],
        "reasoning": cfg["reasoning"],
        "max_tokens": cfg["max_tokens"],
    }

    answer, reasoning, meta, error = "", "", "", None
    finish_reason = None
    with st.chat_message("assistant", avatar="🤖"):
        answer_slot = st.empty()
        meta_slot = st.empty()
        answer_slot.markdown("▌")

        for event, data in post_stream("/api/chat", payload, MODEL_API):
            if event == "reasoning":
                reasoning += data.get("text", "")
            elif event == "delta":
                answer += data.get("text", "")
                answer_slot.markdown(answer + " ▌")
            elif event == "done":
                finish_reason = data.get("finish_reason")
                tokens = data.get("completion_tokens")
                meta = (f"{cfg['model']['id']} · temp {cfg['temperature']:.1f} · "
                        f"{data.get('elapsed_ms', 0)} мс")
                if tokens:
                    meta += f" · {tokens} ток"
                if finish_reason == "length":
                    meta += " · ⚠️ обрезано по max_tokens"
            elif event == "error":
                error = data.get("message", "ошибка")

        answer_slot.error(error) if error else answer_slot.markdown(answer or "—")
        if meta:
            meta_slot.markdown(f'<div class="meta-line">{meta}</div>', unsafe_allow_html=True)
        if finish_reason == "length":
            st.error(
                f"Ответ не уместился в лимит max_tokens = {payload['max_tokens']} — текст оборван. "
                "Увеличьте «Max tokens» и повторите запрос."
            )

    st.session_state.m05_history.append(
        {
            "role": "assistant",
            "content": answer,
            "reasoning": reasoning,
            "meta": meta,
            "error": bool(error),
            "failed": bool(error),
        }
    )


def _render_chat(cfg: dict) -> None:
    st.session_state.setdefault("m05_history", [])
    st.caption(
        "Обычный чат: модель, температура, лимит токенов и системный промпт — "
        "из сайдбара. Сравнение живёт на второй вкладке."
    )
    _render_history()
    prompt = st.chat_input("Спроси что-нибудь…", key="m05_chat_input")
    if prompt:
        _send_message(cfg, prompt)
        st.rerun()


# --- вкладка 2: сравнение моделей --------------------------------------------


def _pick_models(
    models: list[dict], groups: dict[str, list[dict]], *, prefix: str = "m05"
) -> list[str]:
    """Три слота моделей — один и тот же выбор в сравнении и бенчмарке."""
    label_of = {item["id"]: f"{item['label']} · {item['provider']}" for item in models}
    suggestions = _defaults(groups, models)
    selected: list[str] = []
    columns = st.columns(3)
    for column, (tier, label, hint) in zip(columns, TIER_SLOTS):
        pool = groups.get(tier) or models
        ids = [item["id"] for item in pool]
        key = f"{prefix}_pick::{tier}"
        if st.session_state.get(key) not in ids:
            st.session_state[key] = suggestions[tier]
        with column:
            selected.append(
                st.selectbox(
                    label,
                    options=ids,
                    key=key,
                    format_func=lambda mid: label_of.get(mid, mid),
                    help=hint,
                )
            )
            if not groups.get(tier):
                st.caption(f"В каталоге нет {TIER_LABELS[tier]} моделей — показаны все.")

    if len(set(selected)) != len(selected):
        st.warning("Модели должны быть разными: выберите три разные модели.")
    return selected


def _render_compare(cfg: dict, tasks: list[dict]) -> None:
    models = cfg["models"]
    groups: dict[str, list[dict]] = {tier: [] for tier, _, _ in TIER_SLOTS}
    for item in models:
        groups.setdefault(item.get("tier") or "medium", []).append(item)

    task_map = {item["id"]: item for item in tasks}
    st.session_state["m05_task_cache"] = task_map
    task_options = list(task_map) + [ALL_TASKS]
    if tasks and st.session_state.get("m05_task") not in task_options:
        st.session_state["m05_task"] = tasks[0]["id"]

    st.selectbox(
        "Задача",
        options=task_options,
        format_func=lambda tid: (
            f"Все задачи сразу · {len(tasks)} задач"
            if tid == ALL_TASKS
            else f"{task_map[tid]['title']} · {task_map[tid]['complexity']}"
        ),
        key="m05_task",
        on_change=_apply_task,
        help="Одна задача или все пять сразу — во втором случае со сводной таблицей по моделям",
    )

    is_all = st.session_state.get("m05_task") == ALL_TASKS
    current_task = {} if is_all else (task_map.get(st.session_state.get("m05_task") or "") or {})
    if is_all:
        prompt = ""
        st.caption(
            "Все пять задач. Модели отвечают на каждую, ответы сверяются с эталоном, "
            "ниже — сводная таблица «модель × правильно/неправильно»."
        )
    else:
        if current_task and "m05_prompt" not in st.session_state:
            st.session_state["m05_prompt"] = current_task["text"]
        prompt = st.text_area("Промпт для сравнения", height=110, key="m05_prompt")
        if current_task:
            details = [f"сложность: {current_task['complexity']}"]
            if current_task.get("reference"):
                details.append(f"эталон: {current_task['reference']}")
            st.caption(" · ".join(details))

    st.markdown("#### Модели для сравнения")
    selected = _pick_models(models, groups, prefix="m05")
    duplicate = len(set(selected)) != len(selected)
    label_of = {item["id"]: f"{item['label']} · {item['provider']}" for item in models}

    payload_ready = (is_all or bool(prompt.strip())) and not duplicate
    run_clicked = st.button(
        "▶  Сравнить на всех задачах" if is_all else "▶  Сравнить модели",
        type="primary",
        key="m05_run_all" if is_all else "m05_run",
        disabled=not payload_ready,
        help=(
            "5 задач × 3 модели: верность, время, токены и стоимость"
            if is_all
            else "Три модели ответят на этот промпт одновременно"
        ),
    )

    if run_clicked and is_all:
        default_judge = next(
            (item["id"] for item in models if item.get("tier") == "large"), None
        )
        with st.spinner("Модели решают пять задач…"):
            try:
                response = httpx.post(
                    f"{MODEL_API}/api/benchmark",
                    json={
                        "models": selected,
                        "tasks": [task["id"] for task in tasks],
                        "temperature": cfg["temperature"],
                        "reasoning": cfg["reasoning"],
                        "max_tokens": cfg["max_tokens"],
                        "judge": default_judge,
                    },
                    timeout=900.0,
                )
                response.raise_for_status()
                st.session_state["m05_all_result"] = response.json()
                st.session_state["m05_all_analysis"] = None
            except httpx.HTTPStatusError as exc:
                st.session_state["m05_all_result"] = None
                st.error(
                    f"Сравнение не удалось ({exc.response.status_code}): "
                    f"{exc.response.text[:300]}"
                )
            except Exception as exc:  # noqa: BLE001 - показываем в UI
                st.session_state["m05_all_result"] = None
                st.error(f"Сравнение не удалось: {type(exc).__name__}: {exc}")

    elif run_clicked:
        with st.spinner("Три модели отвечают параллельно…"):
            try:
                response = httpx.post(
                    f"{MODEL_API}/api/compare",
                    json={
                        "prompt": prompt.strip(),
                        "models": selected,
                        "task": current_task.get("id", ""),
                        "complexity": current_task.get("complexity", ""),
                        "reference": current_task.get("reference", ""),
                        "temperature": cfg["temperature"],
                        "reasoning": cfg["reasoning"],
                        "max_tokens": cfg["max_tokens"],
                    },
                    timeout=300.0,
                )
                response.raise_for_status()
                st.session_state.m05_compare = response.json()
                st.session_state["m05_analysis"] = None
            except httpx.HTTPStatusError as exc:
                st.session_state.m05_compare = None
                detail = exc.response.text[:300]
                st.error(f"Сравнение не удалось ({exc.response.status_code}): {detail}")
            except Exception as exc:  # noqa: BLE001 - показываем в UI
                st.session_state.m05_compare = None
                st.error(f"Сравнение не удалось: {type(exc).__name__}: {exc}")

    if is_all:
        bench = st.session_state.get("m05_all_result")
        if bench:
            _bench_tables(bench, tasks)
            analyzer = next(
                (item["id"] for item in models if item.get("tier") == "large"),
                selected[0] if selected else "",
            )
            _bench_analysis(
                bench, tasks, cfg,
                analyzer=analyzer,
                button_key="m05_all_analyze_run",
                state_key="m05_all_analysis",
                button_label="🔎  Анализ результатов",
            )
        return

    compare = st.session_state.get("m05_compare")
    if not compare:
        return

    runs = compare.get("runs") or []
    totals = compare.get("totals") or {}

    st.markdown("### Ответы моделей")
    answer_columns = st.columns(max(len(runs), 1))
    for column, run in zip(answer_columns, runs):
        with column:
            st.markdown(f"**{run.get('label') or run['model']}**")
            st.caption(f"{TIER_LABELS.get(run.get('tier', ''), run.get('tier', ''))} · "
                       f"{run.get('provider')}")
            if run.get("error"):
                st.error(run["error"])
                continue
            st.markdown(run.get("answer") or "—")
            usage = run.get("usage") or {}
            st.markdown(
                f'<div class="meta-line">{run.get("elapsed_ms", 0)} мс · '
                f'{usage.get("completion_tokens", 0)} ток · {_money(run)}</div>',
                unsafe_allow_html=True,
            )
            if run.get("reasoning"):
                with st.expander("🧠 Размышления модели", expanded=False):
                    st.markdown(run["reasoning"])

    st.markdown("### Сравнительная таблица")
    rows = []
    for run in runs:
        usage = run.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        rows.append(
            {
                "Модель": run.get("label") or run["model"],
                "Провайдер": run.get("provider", ""),
                "Размер": TIER_LABELS.get(run.get("tier", ""), run.get("tier", "")),
                "Время, мс": run.get("elapsed_ms", 0),
                "Токены (вход)": prompt_tokens,
                "Токены (выход)": completion_tokens,
                "Всего токенов": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
                "Стоимость, $": round(float(run.get("cost_usd") or 0.0), 6),
                "Статус": (
                    "ошибка"
                    if run.get("error")
                    else "обрезан" if run.get("truncated") else "ок"
                ),
            }
        )
    st.table(pd.DataFrame(rows), hide_index=True)

    st.caption(
        f"Итого: {totals.get('total_tokens', 0)} токенов · "
        f"${totals.get('cost_usd', 0.0):.6f} · "
        f"параллельно за {totals.get('elapsed_ms', 0)} мс"
    )
    st.caption(COST_HINT)
    if totals.get("failed"):
        st.warning(
            f"Моделей с ошибкой: {totals['failed']} — ответы неполные, "
            "проверьте ключи и индикаторы провайдеров в сайдбаре."
        )
    if totals.get("truncated"):
        st.warning(
            "Часть ответов оборвана лимитом max_tokens — увеличьте «Max tokens», "
            "иначе сравнение неполное."
        )

    # --- анализ результатов продвинутой моделью ------------------------------
    st.markdown("### Анализ результатов")
    st.caption(
        "Продвинутая модель прочитает ответы и метрики, сверит их с эталоном "
        "и скажет, какая модель лучше на этой задаче."
    )

    analyzer_pool = groups.get("large") or models
    analyzer_ids = [item["id"] for item in analyzer_pool]
    if st.session_state.get("m05_analyzer") not in analyzer_ids:
        st.session_state["m05_analyzer"] = analyzer_ids[0]
    analyzer = st.selectbox(
        "Модель для анализа",
        options=analyzer_ids,
        key="m05_analyzer",
        format_func=lambda mid: label_of.get(mid, mid),
        help="По умолчанию — самая большая модель каталога",
    )

    if st.button("🔎  Анализ результатов", key="m05_analyze_run"):
        usable = [
            {
                "model": run["model"],
                "label": run.get("label") or run["model"],
                "answer": run.get("answer") or "",
                "elapsed_ms": run.get("elapsed_ms", 0),
                "usage": run.get("usage") or {},
                "cost_usd": run.get("cost_usd", 0.0),
            }
            for run in runs
            if (run.get("answer") or "").strip()
        ]
        if not usable:
            st.warning("Нет ответов для анализа")
        else:
            with st.spinner("Модель-аналитик читает ответы…"):
                try:
                    response = httpx.post(
                        f"{MODEL_API}/api/analyze",
                        json={
                            "model": analyzer,
                            "prompt": compare.get("prompt") or "",
                            "task": compare.get("task") or "",
                            "complexity": compare.get("complexity") or "",
                            "reference": compare.get("reference") or "",
                            "runs": usable,
                            "max_tokens": cfg["max_tokens"],
                        },
                        timeout=300.0,
                    )
                    response.raise_for_status()
                    st.session_state["m05_analysis"] = response.json()
                except Exception as exc:  # noqa: BLE001 - показываем в UI
                    st.session_state["m05_analysis"] = None
                    st.error(f"Не удалось проанализировать: {type(exc).__name__}: {exc}")

    analysis = st.session_state.get("m05_analysis")
    if analysis:
        st.markdown(analysis.get("text") or "—")
        st.caption(
            f"{analysis.get('model')} · {analysis.get('elapsed_ms', 0)} мс · "
            f"{(analysis.get('usage') or {}).get('completion_tokens', 0)} ток"
        )
        if analysis.get("truncated"):
            st.warning("Анализ оборван лимитом max_tokens — увеличьте «Max tokens».")


# --- вкладка 3: бенчмарк по всем задачам ------------------------------------


def _sec(ms: int | float) -> str:
    return f"{float(ms or 0) / 1000:.1f}"


def _bench_tables(bench: dict, tasks: list[dict]) -> None:
    """Сводная таблица и матрица «задача × модель» для бенчмарка."""
    summary = bench.get("models") or []
    runs = bench.get("runs") or []
    comparison = bench.get("comparison") or {}
    totals = bench.get("totals") or {}
    task_map = {task["id"]: task for task in tasks}

    st.markdown("### Модель → верных / время / токены / стоимость")
    rows = []
    for item in summary:
        rows.append(
            {
                "Модель": item.get("label") or item["model"],
                "Размер": TIER_LABELS.get(item.get("tier", ""), item.get("tier", "")),
                "Верных": f"{item.get('correct', 0)} / {item.get('total', 0)}",
                "Точность, %": round(float(item.get("accuracy") or 0) * 100),
                "Время, с": _sec(item.get("elapsed_ms", 0)),
                "Среднее, с": _sec(item.get("avg_elapsed_ms", 0)),
                "Токены": item.get("total_tokens", 0),
                "Стоимость, $": round(float(item.get("cost_usd") or 0), 6),
            }
        )
    st.table(pd.DataFrame(rows), hide_index=True)

    if comparison:
        large = comparison.get("large_label") or comparison.get("large")
        small = comparison.get("small_label") or comparison.get("small")
        delta = comparison.get("accuracy_delta_pp", 0)
        extra = comparison.get("extra_correct", 0)
        ratio = comparison.get("cost_ratio")
        if delta > 0:
            verdict = f"точнее на **{delta} п.п.** (+{extra} задач)"
        elif delta == 0:
            verdict = "точность такая же"
        else:
            verdict = f"менее точна на **{abs(delta)} п.п.** (меньше на {abs(extra)} задач)"
        if comparison.get("both_free"):
            st.markdown(f"**{large}** и **{small}** — обе бесплатны; {verdict}.")
        elif ratio is not None and ratio >= 1:
            st.markdown(
                f"**{large}** дороже **{small}** в **{ratio}×**; {verdict}."
            )
        elif ratio is not None:
            st.markdown(
                f"**{large}** дешевле **{small}** в **{round(1 / ratio, 2)}×**; {verdict}."
            )
        else:
            st.markdown(
                f"**{large}** дороже **{small}** на ${comparison.get('cost_delta_usd', 0)}; "
                f"{verdict}."
            )

    if totals.get("errors"):
        st.warning(
            f"Ошибок провайдеров: {totals['errors']} — часть задач не выполнена, "
            "сводка неполная."
        )
    st.caption(
        "Верность проверена моделью-судьёй."
        if totals.get("judged")
        else "Верность проверена по числам эталона."
    )

    st.markdown("### По задачам")
    matrix = []
    for task_id in bench.get("task_ids") or []:
        info = task_map.get(task_id, {})
        row = {
            "Задача": f"{info.get('title', task_id)} · {info.get('complexity', '')}",
            "Эталон": info.get("reference", ""),
        }
        for item in summary:
            run = next(
                (
                    run
                    for run in runs
                    if run["task"] == task_id and run["model"] == item["model"]
                ),
                None,
            )
            name = item.get("label") or item["model"]
            if run is None:
                row[name] = "—"
            elif run.get("error"):
                row[name] = "ошибка"
            else:
                row[name] = f"{'✓' if run.get('correct') else '✗'} {_sec(run.get('elapsed_ms', 0))} с"
        matrix.append(row)
    st.table(pd.DataFrame(matrix), hide_index=True)

    with st.expander("Ответы моделей по задачам", expanded=False):
        for task_id in bench.get("task_ids") or []:
            info = task_map.get(task_id, {})
            st.markdown(
                f"**{info.get('title', task_id)}** · эталон: `{info.get('reference', '—')}`"
            )
            for item in summary:
                run = next(
                    (
                        run
                        for run in runs
                        if run["task"] == task_id and run["model"] == item["model"]
                    ),
                    None,
                )
                if run is None:
                    continue
                mark = "✅" if run.get("correct") else "❌"
                st.caption(
                    f"{mark} {item.get('label') or item['model']} · "
                    f"{_sec(run.get('elapsed_ms', 0))} с · "
                    f"{(run.get('usage') or {}).get('total_tokens', 0)} ток"
                )
                st.markdown((run.get("answer") or run.get("error") or "—")[:800])
            st.divider()


def _bench_analysis(
    bench: dict,
    tasks: list[dict],
    cfg: dict,
    *,
    analyzer: str,
    button_key: str,
    state_key: str,
    button_label: str = "🔎  Сделать вывод",
) -> None:
    """Кнопка «Сделать вывод»: модель-аналитик разбирает сводку бенчмарка."""
    runs = bench.get("runs") or []
    summary = bench.get("models") or []
    comparison = bench.get("comparison") or {}
    task_map = {task["id"]: task for task in tasks}
    st.markdown("### Вывод: где маленькой модели достаточно")
    st.caption(
        "Модель-аналитик читает сводку и ответы, считает верные задачи и говорит, "
        "на каких задачах можно обойтись маленькой моделью."
    )

    if st.button(button_label, key=button_key):
        payload_tasks = []
        for task_id in bench.get("task_ids") or []:
            info = task_map.get(task_id, {})
            payload_tasks.append(
                {
                    "task": task_id,
                    "title": info.get("title", task_id),
                    "reference": info.get("reference", ""),
                    "answers": [
                        {
                            "model": run["model"],
                            "label": run.get("label") or run["model"],
                            "answer": run.get("answer") or "",
                            "correct": bool(run.get("correct")),
                        }
                        for run in runs
                        if run["task"] == task_id
                    ],
                }
            )
        with st.spinner("Модель-аналитик читает результаты…"):
            try:
                response = httpx.post(
                    f"{MODEL_API}/api/benchmark/analyze",
                    json={
                        "model": analyzer,
                        "summary": summary,
                        "tasks": payload_tasks,
                        "comparison": comparison,
                        "max_tokens": cfg["max_tokens"],
                    },
                    timeout=600.0,
                )
                response.raise_for_status()
                st.session_state[state_key] = response.json()
            except Exception as exc:  # noqa: BLE001 - показываем в UI
                st.session_state[state_key] = None
                st.error(f"Не удалось сделать вывод: {type(exc).__name__}: {exc}")

    analysis = st.session_state.get(state_key)
    if analysis:
        st.markdown(analysis.get("text") or "—")
        st.caption(
            f"{analysis.get('model')} · {analysis.get('elapsed_ms', 0)} мс · "
            f"{(analysis.get('usage') or {}).get('completion_tokens', 0)} ток"
        )
        if analysis.get("truncated"):
            st.warning("Вывод оборван лимитом max_tokens — увеличьте «Max tokens».")



def _render_benchmark(cfg: dict, tasks: list[dict]) -> None:
    models = cfg["models"]
    groups: dict[str, list[dict]] = {tier: [] for tier, _, _ in TIER_SLOTS}
    for item in models:
        groups.setdefault(item.get("tier") or "medium", []).append(item)

    st.caption(
        "Все пять задач на трёх моделях. Верным считается ответ, в котором есть все "
        "числа эталона; рядом — время, токены и стоимость каждого прогона."
    )
    st.markdown("#### Модели для бенчмарка")
    selected = _pick_models(models, groups, prefix="m05b")
    duplicate = len(set(selected)) != len(selected)
    label_of = {item["id"]: item["label"] for item in models}

    analyzer_ids = [item["id"] for item in models]
    default_judge = next(
        (item["id"] for item in models if item.get("tier") == "large"), models[0]["id"]
    )
    if st.session_state.get("m05_bench_analyzer") not in analyzer_ids:
        st.session_state["m05_bench_analyzer"] = default_judge
    judge = st.selectbox(
        "Модель-судья и аналитик",
        options=analyzer_ids,
        key="m05_bench_analyzer",
        format_func=lambda mid: label_of.get(mid, mid),
        help="Сверяет итоговые ответы с эталоном и делает вывод по бенчмарку",
    )
    st.caption(
        "Судья проверяет итоговый ответ каждой модели по эталону; если он недоступен, "
        "остаётся проверка по числам эталона."
    )

    run_clicked = st.button(
        "▶  Прогнать все задачи",
        type="primary",
        key="m05_bench_run",
        disabled=duplicate,
        help="5 задач × 3 модели; ответы сверяются с эталоном",
    )

    if run_clicked:
        with st.spinner("Модели решают пять задач…"):
            try:
                response = httpx.post(
                    f"{MODEL_API}/api/benchmark",
                    json={
                        "models": selected,
                        "tasks": [task["id"] for task in tasks],
                        "temperature": cfg["temperature"],
                        "reasoning": cfg["reasoning"],
                        "max_tokens": cfg["max_tokens"],
                        "judge": judge,
                    },
                    timeout=900.0,
                )
                response.raise_for_status()
                st.session_state["m05_benchmark"] = response.json()
                st.session_state["m05_bench_analysis"] = None
            except httpx.HTTPStatusError as exc:
                st.session_state["m05_benchmark"] = None
                st.error(
                    f"Бенчмарк не удался ({exc.response.status_code}): "
                    f"{exc.response.text[:300]}"
                )
            except Exception as exc:  # noqa: BLE001 - показываем в UI
                st.session_state["m05_benchmark"] = None
                st.error(f"Бенчмарк не удался: {type(exc).__name__}: {exc}")

    bench = st.session_state.get("m05_benchmark")
    if not bench:
        return

    _bench_tables(bench, tasks)

    _bench_analysis(
        bench, tasks, cfg,
        analyzer=judge,
        button_key="m05_bench_analyze_run",
        state_key="m05_bench_analysis",
    )


# --- точка входа страницы ----------------------------------------------------


def render() -> None:
    backend = load_backend()
    st.session_state.setdefault("m05_history", [])
    st.session_state.setdefault("m05_compare", None)
    st.session_state.setdefault("m05_analysis", None)
    st.session_state.setdefault("m05_benchmark", None)
    st.session_state.setdefault("m05_bench_analysis", None)
    st.session_state.setdefault("m05_all_result", None)
    st.session_state.setdefault("m05_all_analysis", None)

    models = _models_for_ui(backend["models"])
    tasks = backend["tasks"]

    st.markdown("## Сравнение моделей")
    st.caption(
        "Урок 05: один промпт — три модели разного размера. Во вкладке «Сравнение по задачам» "
        "все пять задач проверяются по эталону: верные ответы, время, токены и стоимость."
    )

    if backend["error"]:
        st.error("API урока 05 недоступен")
        st.caption(backend["error"])
        return
    if not models:
        st.error("API вернул пустой список моделей")
        return

    with st.sidebar:
        cfg = _sidebar(models, backend.get("providers") or [])

    chat_tab, compare_tab, bench_tab = st.tabs(
        ["Чат", "Сравнение моделей", "Сравнение по задачам"]
    )
    with chat_tab:
        _render_chat(cfg)
    with compare_tab:
        if tasks:
            _render_compare(cfg, tasks)
        else:
            st.warning("API не вернул список задач")
    with bench_tab:
        if tasks:
            _render_benchmark(cfg, tasks)
        else:
            st.warning("API не вернул список задач")
