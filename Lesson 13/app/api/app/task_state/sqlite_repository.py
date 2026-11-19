"""SQLite-адаптер состояния задачи."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .domain import (
    Action,
    Stage,
    TaskEvent,
    TaskNotFound,
    TaskState,
    VersionConflict,
    utcnow,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS task (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    plan_text TEXT,
    context_summary TEXT,
    stage TEXT NOT NULL,
    current_step TEXT NOT NULL,
    expected_action TEXT NOT NULL,
    paused INTEGER NOT NULL DEFAULT 0,
    plan_approved INTEGER NOT NULL DEFAULT 0,
    execution_complete INTEGER NOT NULL DEFAULT 0,
    validation_passed INTEGER NOT NULL DEFAULT 0,
    validation_failed INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (stage IN ('planning','execution','validation','done')),
    CHECK (NOT (validation_passed = 1 AND validation_failed = 1)),
    CHECK (plan_approved = 0 OR (plan_text IS NOT NULL AND trim(plan_text) <> ''))
);

CREATE UNIQUE INDEX IF NOT EXISTS task_one_active_per_session
    ON task(session_id)
    WHERE stage <> 'done';

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    action TEXT NOT NULL,
    from_stage TEXT,
    to_stage TEXT,
    reason TEXT,
    success INTEGER NOT NULL,
    error_code TEXT,
    version_before INTEGER NOT NULL,
    version_after INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES task(task_id)
);

CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    task_id TEXT,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS agent_log_session
    ON agent_log(session_id, id);

CREATE TABLE IF NOT EXISTS chat_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    task_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chat_message_session
    ON chat_message(session_id, id);

CREATE INDEX IF NOT EXISTS chat_message_task
    ON chat_message(task_id, id);

CREATE TABLE IF NOT EXISTS task_step (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    step_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(task_id, step_index)
);

CREATE INDEX IF NOT EXISTS task_step_task
    ON task_step(task_id, step_index);
"""


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _row_to_state(row: sqlite3.Row) -> TaskState:
    return TaskState(
        task_id=row["task_id"],
        session_id=row["session_id"],
        goal=row["goal"],
        plan_text=row["plan_text"],
        context_summary=row["context_summary"],
        stage=Stage(row["stage"]),
        current_step=row["current_step"],
        expected_action=row["expected_action"],
        paused=_bool(row["paused"]),
        plan_approved=_bool(row["plan_approved"]),
        execution_complete=_bool(row["execution_complete"]),
        validation_passed=_bool(row["validation_passed"]),
        validation_failed=_bool(row["validation_failed"]),
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_event(row: sqlite3.Row) -> TaskEvent:
    return TaskEvent(
        task_id=row["task_id"],
        action=row["action"],
        from_stage=row["from_stage"],
        to_stage=row["to_stage"],
        reason=row["reason"],
        success=bool(row["success"]),
        error_code=row["error_code"],
        version_before=int(row["version_before"]),
        version_after=int(row["version_after"]),
        created_at=row["created_at"],
    )


class SQLiteTaskRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        # Файл могут удалить или пересоздать между запросами; схема должна
        # существовать на каждом новом соединении, а не только при старте.
        connection.executescript(SCHEMA)
        return connection

    def _init_schema(self) -> None:
        with self._connect():
            pass

    def create(self, task: TaskState) -> TaskState:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task (
                    task_id, session_id, goal, plan_text, context_summary,
                    stage, current_step, expected_action, paused,
                    plan_approved, execution_complete, validation_passed,
                    validation_failed, version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.session_id,
                    task.goal,
                    task.plan_text,
                    task.context_summary,
                    task.stage.value,
                    task.current_step,
                    task.expected_action,
                    int(task.paused),
                    int(task.plan_approved),
                    int(task.execution_complete),
                    int(task.validation_passed),
                    int(task.validation_failed),
                    task.version,
                    task.created_at,
                    task.updated_at,
                ),
            )
        return task

    def get_by_session(self, session_id: str) -> TaskState | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM task
                WHERE session_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return _row_to_state(row) if row else None

    def apply(
        self,
        task_id: str,
        expected_version: int,
        new_state: TaskState,
        event: TaskEvent,
    ) -> TaskState:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE task SET
                    goal = ?, plan_text = ?, context_summary = ?,
                    stage = ?, current_step = ?, expected_action = ?,
                    paused = ?, plan_approved = ?, execution_complete = ?,
                    validation_passed = ?, validation_failed = ?,
                    version = ?, updated_at = ?
                WHERE task_id = ? AND version = ?
                """,
                (
                    new_state.goal,
                    new_state.plan_text,
                    new_state.context_summary,
                    new_state.stage.value,
                    new_state.current_step,
                    new_state.expected_action,
                    int(new_state.paused),
                    int(new_state.plan_approved),
                    int(new_state.execution_complete),
                    int(new_state.validation_passed),
                    int(new_state.validation_failed),
                    new_state.version,
                    new_state.updated_at,
                    task_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                row = connection.execute(
                    "SELECT * FROM task WHERE task_id = ?", (task_id,)
                ).fetchone()
                if row is None:
                    raise TaskNotFound()
                raise VersionConflict(_row_to_state(row))
            connection.execute(
                """
                INSERT INTO task_history (
                    task_id, action, from_stage, to_stage, reason,
                    success, error_code, version_before, version_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.task_id,
                    event.action,
                    event.from_stage,
                    event.to_stage,
                    event.reason,
                    int(event.success),
                    event.error_code,
                    event.version_before,
                    event.version_after,
                    event.created_at,
                ),
            )
            connection.commit()
        return new_state

    def log_event(self, event: TaskEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_history (
                    task_id, action, from_stage, to_stage, reason,
                    success, error_code, version_before, version_after, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.task_id,
                    event.action,
                    event.from_stage,
                    event.to_stage,
                    event.reason,
                    int(event.success),
                    event.error_code,
                    event.version_before,
                    event.version_after,
                    event.created_at,
                ),
            )

    def history(self, task_id: str) -> list[TaskEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_history
                WHERE task_id = ?
                ORDER BY id ASC
                """,
                (task_id,),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def log_agent_event(
        self,
        *,
        session_id: str,
        task_id: str | None,
        kind: str,
        level: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_log (
                    session_id, task_id, kind, level, message, details, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    kind,
                    level,
                    message,
                    json.dumps(details, ensure_ascii=False) if details else None,
                    utcnow(),
                ),
            )

    def replace_steps(self, task_id: str, titles: list[str]) -> None:
        now = utcnow()
        with self._connect() as connection:
            connection.execute("DELETE FROM task_step WHERE task_id = ?", (task_id,))
            connection.executemany(
                """
                INSERT INTO task_step (
                    task_id, step_index, title, status, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, ?)
                """,
                [
                    (task_id, index, title, now, now)
                    for index, title in enumerate(titles, start=1)
                ],
            )

    def steps(self, task_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM task_step
                WHERE task_id = ?
                ORDER BY step_index ASC
                """,
                (task_id,),
            ).fetchall()
        return [
            {
                "step_id": row["id"],
                "task_id": row["task_id"],
                "index": row["step_index"],
                "title": row["title"],
                "status": row["status"],
                "result": row["result"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def start_step(self, task_id: str, step_id: int) -> dict | None:
        now = utcnow()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE task_step
                SET status = 'running', updated_at = ?
                WHERE id = ? AND task_id = ? AND status IN ('pending', 'failed')
                """,
                (now, step_id, task_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM task_step WHERE id = ?", (step_id,)
            ).fetchone()
        return {
            "step_id": row["id"],
            "task_id": row["task_id"],
            "index": row["step_index"],
            "title": row["title"],
            "status": row["status"],
            "result": row["result"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def finish_step(
        self, task_id: str, step_id: int, *, status: str, result: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE task_step
                SET status = ?, result = ?, updated_at = ?
                WHERE id = ? AND task_id = ?
                """,
                (status, result[:8_000], utcnow(), step_id, task_id),
            )

    def save_chat_message(
        self,
        *,
        session_id: str,
        task_id: str | None,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_message (
                    session_id, task_id, role, content, meta, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    task_id,
                    role,
                    content,
                    json.dumps(meta, ensure_ascii=False) if meta else None,
                    utcnow(),
                ),
            )

    def chat_history(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            if task_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM chat_message
                    WHERE session_id = ? AND task_id IS NULL
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM chat_message
                    WHERE session_id = ? AND task_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (session_id, task_id, limit),
                ).fetchall()
        result: list[dict] = []
        for row in reversed(rows):
            meta = None
            if row["meta"]:
                try:
                    meta = json.loads(row["meta"])
                except json.JSONDecodeError:
                    meta = {}
            item = {
                "id": row["id"],
                "session_id": row["session_id"],
                "task_id": row["task_id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            if meta:
                item.update(meta)
            result.append(item)
        return result

    def agent_log(self, session_id: str, limit: int = 200) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM agent_log
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        result: list[dict] = []
        for row in rows:
            details = None
            if row["details"]:
                try:
                    details = json.loads(row["details"])
                except json.JSONDecodeError:
                    details = {"raw": row["details"]}
            result.append(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "task_id": row["task_id"],
                    "kind": row["kind"],
                    "level": row["level"],
                    "message": row["message"],
                    "details": details,
                    "created_at": row["created_at"],
                }
            )
        return result


    def clear_tasks(self) -> dict[str, int]:
        """Удалить задачи, шаги, историю, чат и лог (локальный сброс)."""
        tables = ("task_step", "task_history", "chat_message", "agent_log", "task")
        counts: dict[str, int] = {}
        with self._connect() as connection:
            for table in tables:
                row = connection.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()
                counts[table] = int(row["n"] if row else 0)
                connection.execute(f"DELETE FROM {table}")
        return counts

    def clear_chat(self) -> dict[str, int]:
        """Удалить только сообщения чата, оставив задачи и лог."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM chat_message"
            ).fetchone()
            count = int(row["n"] if row else 0)
            connection.execute("DELETE FROM chat_message")
        return {"chat_message": count}
