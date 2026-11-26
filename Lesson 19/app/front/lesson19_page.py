"""Урок 19: автоматический пайплайн search → summarize → saveToFile."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API = os.getenv("LESSON_19_API_BASE_URL", "http://localhost:8019").rstrip("/")
TIMEOUT = httpx.Timeout(90.0, connect=10.0)

SCENARIOS = {
    "none": "Норма",
    "empty_search": "Пустой результат search",
    "summarize_error": "Ошибка summarize",
    "save_error": "Ошибка saveToFile",
}
STEP_ORDER = ["search", "summarize", "saveToFile"]


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.HTTPError as exc:
        return {"_error": f"API урока 19 недоступен: {exc}"}
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        return {"_error": f"{response.status_code}: {detail}"}
    try:
        return response.json()
    except ValueError:
        return {"_error": "API вернул не JSON"}


def _render_chain(result: dict[str, Any] | None) -> None:
    run_steps = {item.get("tool"): item for item in (result or {}).get("steps") or []}
    pieces = []
    for tool in STEP_ORDER:
        step = run_steps.get(tool)
        if step is None:
            marker = "·"
        elif step.get("status") == "ok":
            marker = "✓"
        elif step.get("status") == "empty":
            marker = "∅"
        else:
            marker = "✕"
        pieces.append(f"{marker} {tool}")
    st.markdown("#### Цепочка")
    st.code("  →  ".join(pieces), language=None)


def _render_result(result: dict[str, Any]) -> None:
    if result.get("_error"):
        st.error(result["_error"])
        return

    _render_chain(result)
    if result.get("ok"):
        st.success(result.get("message") or "Пайплайн завершён.")
    else:
        st.error(result.get("message") or "Пайплайн остановлен.")
        st.info(
            "Итоговый результат не сформирован: следующие инструменты не вызывались "
            "после сбойного или пустого шага."
        )

    steps = result.get("steps") or []
    if steps:
        st.markdown("#### Трасса выполнения")
        for step in steps:
            status = step.get("status")
            icon = {"ok": "✅", "error": "❌", "empty": "⚠️"}.get(str(status), "•")
            st.markdown(
                f"**{icon} {step.get('index')}. `{step.get('tool')}`** "
                f"· {step.get('elapsed_ms', 0)} мс · `{status}`"
            )
            with st.expander(f"Аргументы и результат · {step.get('tool')}", expanded=False):
                st.caption("Аргументы")
                st.json(step.get("arguments") or {})
                st.caption("Результат")
                st.json(step.get("result") or {})

    if result.get("ok") and result.get("output"):
        st.markdown("#### Итоговый результат")
        st.code(result["output"], language="text")
        file = result.get("file") or {}
        if file.get("path"):
            st.caption(f"Сохранено: `{file['path']}` · {file.get('bytes', 0)} байт")


def _render_tools() -> None:
    with st.expander("MCP-сервер и инструменты", expanded=False):
        inspect = _request("POST", "/api/mcp/inspect")
        if inspect.get("_error"):
            st.error(inspect["_error"])
            return
        st.caption(
            f"Сервер `{(inspect.get('server') or {}).get('name', '—')}` · "
            f"транспорт `{inspect.get('transport', '—')}` · "
            f"инструментов: {inspect.get('tool_count', 0)}"
        )
        for tool in inspect.get("tools") or []:
            st.markdown(f"**`{tool.get('name')}`**")
            st.write(tool.get("description") or "")
            st.json(tool.get("input_schema") or {})


def _run(query: str, scenario: str) -> None:
    with st.spinner("Агент выполняет цепочку MCP-инструментов…"):
        result = _request(
            "POST", "/api/pipeline/run", json={"query": query, "scenario": scenario}
        )
    st.session_state["l19_result"] = result


def render() -> None:
    st.markdown("## Урок 19. Композиция MCP инструментов")
    st.caption(
        "Один MCP-сервер предоставляет search, summarize и saveToFile. Агент "
        "автоматически передаёт данные по цепочке и останавливается, если шаг "
        "вернул ошибку или пустой результат."
    )

    st.markdown("#### Запуск пайплайна")
    query = st.text_input(
        "Поисковый запрос",
        value="MCP инструменты",
        key="l19_query",
    )
    scenario = st.selectbox(
        "Сценарий",
        options=list(SCENARIOS),
        format_func=lambda value: SCENARIOS[value],
        key="l19_scenario",
    )
    if st.button("Запустить автоматическую цепочку", type="primary", key="l19_run"):
        _run(query, scenario)

    result = st.session_state.get("l19_result")
    if result:
        _render_result(result)
    else:
        st.info("Нажмите кнопку — агент выполнит все три шага автоматически.")

    with st.expander("Ожидаемое поведение при сбоях", expanded=False):
        st.markdown(
            """
- **Пустой search** — `summarize` не вызывается; в трассе один шаг.
- **Ошибка summarize** — `saveToFile` не вызывается; в трассе два шага.
- **Ошибка saveToFile** — итоговый результат не объявляется успешным; в трассе три шага.
- При остановке `output` и `file` равны `None`: агент не выдаёт результат, которого нет.
            """
        )
    _render_tools()
