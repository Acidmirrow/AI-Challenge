"""Фоновый планировщик урока 18.

Цикл работы:
1. `fetch_metrics` — получить новую порцию данных через MCP;
2. `save_snapshot` — сохранить каждый запуск в SQLite;
3. раз в `report_interval` вызвать `read_snapshots` и собрать отчёт по всем
   запускам периода, а не только по последнему.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from . import storage
from .config import Settings
from .mcp_client import MCPError, call_tool


class SchedulerError(RuntimeError):
    """Планировщик не смог выполнить цикл."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _payload(result: dict[str, Any], tool: str) -> dict[str, Any]:
    text = result.get("text")
    try:
        payload = json.loads(text) if isinstance(text, str) else None
    except json.JSONDecodeError as exc:
        raise SchedulerError(f"{tool}: MCP вернул не JSON") from exc
    if not isinstance(payload, dict):
        raise SchedulerError(f"{tool}: пустой ответ MCP")
    if result.get("is_error") or not payload.get("ok"):
        raise SchedulerError(str(payload.get("error") or f"{tool}: ошибка MCP"))
    return payload


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _aggregate(snapshots: list[dict[str, Any]], since: str, until: str, window: int) -> dict[str, Any]:
    """Собрать сводку по всем снимкам периода."""
    if not snapshots:
        return {
            "period_start": since,
            "period_end": until,
            "window_minutes": window,
            "runs": 0,
            "snapshot_ids": [],
            "first_run_at": None,
            "last_run_at": None,
            "cpu_avg": 0.0,
            "cpu_max": 0.0,
            "requests_total": 0,
            "errors_total": 0,
            "error_rate_pct": 0.0,
            "latency_avg": 0.0,
            "queue_avg": 0.0,
            "series": [],
        }
    cpu = [float(item["cpu_pct"]) for item in snapshots]
    requests = [int(item["requests"]) for item in snapshots]
    errors = [int(item["errors"]) for item in snapshots]
    latency = [float(item["latency_ms"]) for item in snapshots]
    queue = [int(item["queue_depth"]) for item in snapshots]
    requests_total = sum(requests)
    errors_total = sum(errors)
    return {
        "period_start": since,
        "period_end": until,
        "window_minutes": window,
        "runs": len(snapshots),
        "snapshot_ids": [int(item["id"]) for item in snapshots],
        "first_run_at": snapshots[0]["collected_at"],
        "last_run_at": snapshots[-1]["collected_at"],
        "cpu_avg": _avg(cpu),
        "cpu_max": round(max(cpu), 2),
        "requests_total": requests_total,
        "errors_total": errors_total,
        "error_rate_pct": round(errors_total / max(requests_total, 1) * 100, 2),
        "latency_avg": _avg(latency),
        "queue_avg": _avg([float(value) for value in queue]),
        "series": [
            {
                "id": int(item["id"]),
                "run_id": item["run_id"],
                "collected_at": item["collected_at"],
                "cpu_pct": float(item["cpu_pct"]),
                "requests": int(item["requests"]),
                "errors": int(item["errors"]),
            }
            for item in snapshots
        ],
    }


class Scheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._runs = 0
        self._last_run_at: str | None = None
        self._next_run_at: str | None = None
        self._last_report_at: str | None = None
        self._last_report_monotonic: float | None = None
        self._last_error: str | None = None
        self._last_snapshot: dict[str, Any] | None = None

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def start(self) -> None:
        if not self.settings.scheduler_enabled or self.running:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(), name="lesson18-scheduler")

    async def stop(self) -> None:
        """Остановить цикл, дав текущему MCP-вызову завершиться."""
        self._stop.set()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=10.0)
        except asyncio.TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        # Небольшая пауза, чтобы приложение успело подняться.
        await asyncio.sleep(max(0.0, float(self.settings.scheduler_startup_delay_s)))
        while not self._stop.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.snapshot_interval
                )
            except asyncio.TimeoutError:
                continue

    async def run_once(self) -> dict[str, Any]:
        """Один цикл: получить снимок, сохранить его и при необходимости собрать отчёт."""
        async with self._lock:
            fetched = _payload(
                await call_tool("fetch_metrics", {"source": self.settings.scheduler_source}),
                "fetch_metrics",
            )
            snapshot = fetched.get("snapshot")
            if not isinstance(snapshot, dict):
                raise SchedulerError("fetch_metrics не вернул snapshot")
            saved = _payload(
                await call_tool("save_snapshot", {"snapshot": snapshot}),
                "save_snapshot",
            )
            record = saved.get("snapshot")
            if not isinstance(record, dict):
                raise SchedulerError("save_snapshot не вернул запись")
            self._runs += 1
            self._last_run_at = str(record.get("collected_at") or _now().isoformat())
            self._next_run_at = (
                _now() + timedelta(seconds=self.settings.snapshot_interval)
            ).isoformat()
            self._last_snapshot = record
            self._last_error = None
            if self._report_due():
                await self._build_report_locked()
            return record

    async def build_report(self) -> dict[str, Any]:
        """Собрать отчёт вручную или по расписанию."""
        async with self._lock:
            return await self._build_report_locked()

    async def clear_results(self) -> dict[str, int]:
        """Удалить накопленные снимки и отчёты, не останавливая цикл."""
        async with self._lock:
            deleted = storage.clear_results()
            self._runs = 0
            self._last_run_at = None
            self._next_run_at = None
            self._last_report_at = None
            self._last_report_monotonic = None
            self._last_error = None
            self._last_snapshot = None
            return deleted

    def _report_due(self) -> bool:
        if self._last_report_monotonic is None:
            return True
        return (
            time.monotonic() - self._last_report_monotonic
            >= self.settings.report_interval
        )

    async def _build_report_locked(self) -> dict[str, Any]:
        now = _now()
        window = int(self.settings.scheduler_report_window_minutes)
        since = (now - timedelta(minutes=window)).isoformat()
        result = _payload(
            await call_tool(
                "read_snapshots",
                {"since": since, "until": now.isoformat(), "limit": 5000},
            ),
            "read_snapshots",
        )
        snapshots = result.get("snapshots")
        if not isinstance(snapshots, list):
            raise SchedulerError("read_snapshots не вернул список снимков")
        report = _aggregate(snapshots, since, now.isoformat(), window)
        try:
            saved = storage.save_report(report)
        except sqlite3.Error as exc:
            raise SchedulerError(f"Не удалось сохранить отчёт: {exc}") from exc
        self._last_report_at = str(saved.get("created_at") or now.isoformat())
        self._last_report_monotonic = time.monotonic()
        return saved

    def status(self) -> dict[str, Any]:
        try:
            snapshots_total = storage.count_snapshots()
            reports_total = storage.count_reports()
        except Exception as exc:  # noqa: BLE001
            snapshots_total = 0
            reports_total = 0
            self._last_error = str(exc)
        return {
            "enabled": self.settings.scheduler_enabled,
            "running": self.running,
            "snapshot_interval_s": self.settings.snapshot_interval,
            "report_interval_s": self.settings.report_interval,
            "window_minutes": self.settings.scheduler_report_window_minutes,
            "snapshot_limit": storage.MAX_SNAPSHOTS,
            "runs_this_process": self._runs,
            "snapshots_total": snapshots_total,
            "reports_total": reports_total,
            "last_run_at": self._last_run_at,
            "next_run_at": self._next_run_at,
            "last_report_at": self._last_report_at,
            "last_error": self._last_error,
            "last_snapshot": self._last_snapshot,
            "db_path": str(storage.db_path()),
        }
