"""Урок 18: планировщик, MCP-инструменты и накопленные отчёты."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API = os.getenv("LESSON_18_API_BASE_URL", "http://localhost:8018").rstrip("/")
TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.HTTPError as exc:
        return {"_error": f"API урока 18 недоступен: {exc}"}
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


def _status() -> dict[str, Any]:
    result = _request("GET", "/api/scheduler/status")
    return result if isinstance(result, dict) and not result.get("_error") else {}


def _render_status(status: dict[str, Any]) -> None:
    if not status:
        st.error("Не удалось получить статус планировщика.")
        return
    running = status.get("running")
    enabled = status.get("enabled")
    if running:
        label = "работает"
    elif enabled:
        label = "запускается"
    else:
        label = "выключен"

    first, second, third, fourth = st.columns(4)
    first.metric("Планировщик", label)
    second.metric("Снимков", status.get("snapshots_total", 0))
    third.metric("Отчётов", status.get("reports_total", 0))
    fourth.metric("Запусков процесса", status.get("runs_this_process", 0))
    st.caption(
        f"Снимок каждые **{status.get('snapshot_interval_s')} с** · "
        f"отчёт каждые **{status.get('report_interval_s')} с** · "
        f"окно отчёта **{status.get('window_minutes')} мин** · "
        f"лимит снимков **{status.get('snapshot_limit', 500)}**"
    )
    if status.get("last_error"):
        st.error(f"Последняя ошибка: {status['last_error']}")
    if status.get("db_path"):
        st.caption(f"SQLite: `{status['db_path']}`")


def _render_actions() -> None:
    st.markdown("#### Управление")
    first, second, third, fourth = st.columns(4)
    run = first.button("Запустить цикл сейчас", use_container_width=True, key="l18_run")
    report = second.button("Собрать отчёт сейчас", type="primary", use_container_width=True, key="l18_report")
    refresh = third.button("Обновить", use_container_width=True, key="l18_refresh")
    clear = fourth.button("Очистить результаты", use_container_width=True, key="l18_clear")

    if run:
        result = _request("POST", "/api/scheduler/run")
        st.session_state["l18_action"] = ("Снимок", result)
        st.rerun()
    if report:
        result = _request("POST", "/api/scheduler/report")
        st.session_state["l18_action"] = ("Отчёт", result)
        st.rerun()
    if refresh:
        st.rerun()
    if clear:
        result = _request("POST", "/api/scheduler/clear")
        st.session_state["l18_action"] = ("Очистка", result)
        st.rerun()
    st.caption("«Очистить результаты» удаляет все накопленные снимки и отчёты; планировщик продолжает работу.")

    action = st.session_state.pop("l18_action", None)
    if action:
        title, result = action
        if result.get("_error"):
            st.error(f"{title}: {result['_error']}")
        else:
            st.success(f"{title} готов")
            st.json(result)


def _render_snapshots() -> None:
    st.markdown("#### Накопленные снимки")
    data = _request("GET", "/api/snapshots", params={"limit": 20})
    if data.get("_error"):
        st.error(data["_error"])
        return
    snapshots = data.get("snapshots") or []
    if not snapshots:
        st.info("Снимков ещё нет. Планировщик сделает первый автоматически.")
        return
    st.caption(f"Показаны последние {len(snapshots)} из {data.get('total', len(snapshots))}.")
    st.dataframe(
        [
            {
                "id": item.get("id"),
                "время": item.get("collected_at"),
                "источник": item.get("source"),
                "CPU %": item.get("cpu_pct"),
                "запросы": item.get("requests"),
                "ошибки": item.get("errors"),
                "p95, мс": item.get("latency_ms"),
                "очередь": item.get("queue_depth"),
            }
            for item in snapshots
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_report() -> None:
    st.markdown("#### Последний агрегированный отчёт")
    data = _request("GET", "/api/reports/latest")
    if data.get("_error"):
        st.error(data["_error"])
        return
    report = data.get("report")
    if not report:
        st.info("Отчёт ещё не собран.")
        return

    first, second, third, fourth = st.columns(4)
    first.metric("Запусков в отчёте", report.get("runs", 0))
    second.metric("Запросов всего", report.get("requests_total", 0))
    third.metric("Ошибок всего", report.get("errors_total", 0))
    fourth.metric("Ошибок, %", report.get("error_rate_pct", 0))
    st.caption(
        f"Период: `{report.get('period_start')}` → `{report.get('period_end')}` · "
        f"CPU avg **{report.get('cpu_avg')}%** · "
        f"latency avg **{report.get('latency_avg')} мс**"
    )
    series = report.get("series") or []
    if series:
        st.dataframe(
            [
                {
                    "id": item.get("id"),
                    "время": item.get("collected_at"),
                    "CPU %": item.get("cpu_pct"),
                    "запросы": item.get("requests"),
                    "ошибки": item.get("errors"),
                }
                for item in series
            ],
            use_container_width=True,
            hide_index=True,
        )
    with st.expander("Отчёт целиком (JSON)"):
        st.json(report)


def _render_tools() -> None:
    with st.expander("MCP-инструменты планировщика", expanded=False):
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


def render() -> None:
    st.markdown("## Урок 18. Планировщик и фоновые задачи")
    st.markdown(
        """
        <style>
        .st-key-l18_clear button {
            background-color: #b42318 !important;
            border-color: #b42318 !important;
            color: #ffffff !important;
        }
        .st-key-l18_clear button:hover {
            background-color: #912018 !important;
            border-color: #912018 !important;
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Фоновый процесс по расписанию собирает метрики через MCP, сохраняет каждый "
        "запуск в SQLite и периодически строит сводку по всем накопленным запускам."
    )
    status = _status()
    _render_status(status)
    _render_actions()
    _render_snapshots()
    _render_report()
    _render_tools()
