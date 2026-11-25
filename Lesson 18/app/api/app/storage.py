"""SQLite-хранилище урока 18: снимки метрик и агрегированные отчёты."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "/srv/data/lesson18.db"
MAX_SNAPSHOTS = 500


def db_path() -> Path:
    return Path(os.getenv("SCHEDULER_DB_PATH") or os.getenv("LESSON18_DB") or DEFAULT_DB_PATH)


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA journal_mode=WAL")
    _init_schema(connection)
    return connection


def _init_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL UNIQUE,
            collected_at TEXT NOT NULL,
            source TEXT NOT NULL,
            cpu_pct REAL NOT NULL,
            requests INTEGER NOT NULL,
            errors INTEGER NOT NULL,
            latency_ms REAL NOT NULL,
            queue_depth INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_collected
            ON snapshots (collected_at, id);

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            period_start TEXT,
            period_end TEXT,
            runs INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        """
    )
    connection.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, name: str) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} должен быть числом") from exc


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc


def save_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Сохранить один снимок; повторный run_id не создаёт дубликат."""
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot должен быть объектом")
    run_id = str(snapshot.get("run_id") or "").strip()
    collected_at = str(snapshot.get("collected_at") or "").strip()
    if not run_id:
        raise ValueError("run_id обязателен")
    if not collected_at:
        raise ValueError("collected_at обязателен")
    record = {
        "run_id": run_id,
        "collected_at": collected_at,
        "source": str(snapshot.get("source") or "demo-api").strip() or "demo-api",
        "cpu_pct": _as_float(snapshot.get("cpu_pct"), "cpu_pct"),
        "requests": _as_int(snapshot.get("requests"), "requests"),
        "errors": _as_int(snapshot.get("errors"), "errors"),
        "latency_ms": _as_float(snapshot.get("latency_ms"), "latency_ms"),
        "queue_depth": _as_int(snapshot.get("queue_depth"), "queue_depth"),
    }
    with closing(_connect()) as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO snapshots
                (run_id, collected_at, source, cpu_pct, requests, errors,
                 latency_ms, queue_depth, created_at)
            VALUES
                (:run_id, :collected_at, :source, :cpu_pct, :requests, :errors,
                 :latency_ms, :queue_depth, :created_at)
            """,
            {**record, "created_at": _now()},
        )
        row = connection.execute(
            "SELECT * FROM snapshots WHERE run_id = ?", (run_id,)
        ).fetchone()
        total = int(connection.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"])
        excess = max(0, total - MAX_SNAPSHOTS)
        if excess:
            connection.execute(
                """
                DELETE FROM snapshots
                WHERE id IN (
                    SELECT id FROM snapshots ORDER BY id ASC LIMIT ?
                )
                """,
                (excess,),
            )
            total -= excess
        connection.commit()
    if row is None:
        raise RuntimeError("Не удалось сохранить снимок")
    return {**dict(row), "total": total, "limit": MAX_SNAPSHOTS, "trimmed": excess}


def clear_results() -> dict[str, int]:
    """Удалить все накопленные снимки и отчёты, не останавливая планировщик."""
    with closing(_connect()) as connection:
        snapshots_deleted = int(
            connection.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"]
        )
        reports_deleted = int(
            connection.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"]
        )
        connection.execute("DELETE FROM snapshots")
        connection.execute("DELETE FROM reports")
        connection.commit()
    return {
        "snapshots_deleted": snapshots_deleted,
        "reports_deleted": reports_deleted,
    }


def read_snapshots(
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Прочитать накопленные снимки за период в хронологическом порядке."""
    limit = max(1, min(int(limit), 5_000))
    clauses: list[str] = []
    params: list[Any] = []
    if since:
        clauses.append("collected_at >= ?")
        params.append(since)
    if until:
        clauses.append("collected_at <= ?")
        params.append(until)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(_connect()) as connection:
        rows = connection.execute(
            f"SELECT * FROM snapshots{where} ORDER BY collected_at ASC, id ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
        total = connection.execute(
            f"SELECT COUNT(*) AS n FROM snapshots{where}", tuple(params)
        ).fetchone()["n"]
    snapshots = [dict(row) for row in rows]
    return {"count": len(snapshots), "total": total, "snapshots": snapshots}


def count_snapshots() -> int:
    with closing(_connect()) as connection:
        return int(connection.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"])


def count_reports() -> int:
    with closing(_connect()) as connection:
        return int(connection.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"])


def save_report(report: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps(report, ensure_ascii=False)
    with closing(_connect()) as connection:
        cursor = connection.execute(
            """
            INSERT INTO reports (created_at, period_start, period_end, runs, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                _now(),
                report.get("period_start"),
                report.get("period_end"),
                int(report.get("runs") or 0),
                payload,
            ),
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Не удалось сохранить отчёт")
        report_id = int(cursor.lastrowid)
        connection.commit()
    return {**report, "id": report_id}


def latest_report() -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _report_row(row) if row else None


def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with closing(_connect()) as connection:
        rows = connection.execute(
            "SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_report_row(row) for row in rows]


def _report_row(row: sqlite3.Row) -> dict[str, Any]:
    data = json.loads(row["payload_json"])
    data["id"] = row["id"]
    data["created_at"] = row["created_at"]
    return data
