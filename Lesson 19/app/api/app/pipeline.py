"""Детерминированный агент-пайплайн урока 19.

Один запуск выполняет цепочку:
search → summarize → saveToFile.

После каждого шага проверяются `ok` и наличие данных. При ошибке или пустом
результате следующие инструменты не вызываются, а в ответе фиксируется шаг и
причина остановки.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .mcp_client import MCPError, call_tool

SCENARIOS = {
    "none": "Норма",
    "empty_search": "Пустой результат search",
    "summarize_error": "Ошибка summarize",
    "save_error": "Ошибка saveToFile",
}


class PipelineError(RuntimeError):
    """Ошибка транспорта или некорректный ответ MCP."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return f"pipeline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:6]}"


async def _invoke(tool: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], int]:
    try:
        result = await call_tool(tool, arguments)
    except MCPError:
        raise
    text = result.get("text")
    try:
        payload = json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError as exc:
        raise PipelineError(f"{tool}: MCP вернул не JSON") from exc
    if not isinstance(payload, dict):
        raise PipelineError(f"{tool}: пустой ответ MCP")
    if result.get("is_error"):
        payload = {"ok": False, "error": payload.get("error") or f"{tool}: ошибка MCP"}
    return payload, int(result.get("duration_ms") or 0)


def _step(
    index: int,
    tool: str,
    arguments: dict[str, Any],
    payload: dict[str, Any],
    duration_ms: int,
    status: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "tool": tool,
        "status": status,
        "arguments": arguments,
        "result": payload,
        "elapsed_ms": duration_ms,
    }


def _stopped(
    run_id: str,
    query: str,
    scenario: str,
    steps: list[dict[str, Any]],
    tool: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "stopped",
        "run_id": run_id,
        "query": query,
        "scenario": scenario,
        "stopped_at": tool,
        "stopped_step": len(steps),
        "reason": reason,
        "message": f"Цепочка остановлена на шаге {len(steps)} ({tool}): {reason}",
        "steps": steps,
        "output": None,
        "file": None,
        "finished_at": _now(),
    }


class Pipeline:
    """Автоматически проводит данные через три MCP-инструмента."""

    async def run(self, query: str, scenario: str = "none") -> dict[str, Any]:
        query = query.strip()
        scenario = scenario if scenario in SCENARIOS else "none"
        run_id = _run_id()
        steps: list[dict[str, Any]] = []

        search_args: dict[str, Any] = {
            "query": query,
            "empty": scenario == "empty_search",
        }
        search_payload, search_ms = await _invoke("search", search_args)
        search_ok = bool(search_payload.get("ok"))
        results = search_payload.get("results")
        if not search_ok:
            steps.append(_step(1, "search", search_args, search_payload, search_ms, "error"))
            return _stopped(
                run_id,
                query,
                scenario,
                steps,
                "search",
                str(search_payload.get("error") or "search вернул ошибку"),
            )
        if not isinstance(results, list) or not results:
            steps.append(_step(1, "search", search_args, search_payload, search_ms, "empty"))
            return _stopped(
                run_id,
                query,
                scenario,
                steps,
                "search",
                "search вернул пустой результат; summarize и saveToFile не вызывались",
            )
        steps.append(_step(1, "search", search_args, search_payload, search_ms, "ok"))

        summarize_args: dict[str, Any] = {
            "results": results,
            "fail": scenario == "summarize_error",
        }
        summarize_payload, summarize_ms = await _invoke("summarize", summarize_args)
        if not summarize_payload.get("ok"):
            steps.append(
                _step(2, "summarize", summarize_args, summarize_payload, summarize_ms, "error")
            )
            return _stopped(
                run_id,
                query,
                scenario,
                steps,
                "summarize",
                str(summarize_payload.get("error") or "summarize вернул ошибку"),
            )
        summary = str(summarize_payload.get("summary") or "").strip()
        if not summary:
            steps.append(
                _step(2, "summarize", summarize_args, summarize_payload, summarize_ms, "empty")
            )
            return _stopped(
                run_id,
                query,
                scenario,
                steps,
                "summarize",
                "summarize вернул пустую сводку; saveToFile не вызывался",
            )
        steps.append(_step(2, "summarize", summarize_args, summarize_payload, summarize_ms, "ok"))

        save_args: dict[str, Any] = {
            "filename": "pipeline-summary.md",
            "content": summary,
            "fail": scenario == "save_error",
        }
        save_payload, save_ms = await _invoke("saveToFile", save_args)
        if not save_payload.get("ok"):
            steps.append(
                _step(3, "saveToFile", save_args, save_payload, save_ms, "error")
            )
            return _stopped(
                run_id,
                query,
                scenario,
                steps,
                "saveToFile",
                str(save_payload.get("error") or "saveToFile вернул ошибку"),
            )
        steps.append(_step(3, "saveToFile", save_args, save_payload, save_ms, "ok"))

        return {
            "ok": True,
            "status": "done",
            "run_id": run_id,
            "query": query,
            "scenario": scenario,
            "message": "Пайплайн завершён: найдено, обработано и сохранено.",
            "steps": steps,
            "output": summary,
            "file": save_payload,
            "finished_at": _now(),
        }
