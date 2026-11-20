"""SQLite-хранилище инвариантов, изменений, чата и попыток обхода."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .domain import DEFAULT_INVARIANTS, Invariant, changed, utcnow


SCHEMA = """
CREATE TABLE IF NOT EXISTS invariant (
    invariant_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    statement TEXT NOT NULL,
    category TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invariant_change (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invariant_id TEXT NOT NULL,
    old_statement TEXT NOT NULL,
    new_statement TEXT NOT NULL,
    changed_by TEXT NOT NULL,
    reason TEXT,
    version_after INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (invariant_id) REFERENCES invariant(invariant_id)
);

CREATE TABLE IF NOT EXISTS chat_message (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS chat_message_session
    ON chat_message(session_id, id);

CREATE TABLE IF NOT EXISTS attempt (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    decision TEXT NOT NULL,
    source TEXT NOT NULL,
    violations TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS attempt_session
    ON attempt(session_id, id);
"""


def _row_to_invariant(row: sqlite3.Row) -> Invariant:
    return Invariant(
        invariant_id=row["invariant_id"],
        title=row["title"],
        statement=row["statement"],
        category=row["category"],
        active=bool(row["active"]),
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class InvariantStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._seed()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            connection.execute("PRAGMA journal_mode = DELETE")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _seed(self) -> None:
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM invariant"
            ).fetchone()["n"]
            if count:
                return
            now = utcnow()
            for item in DEFAULT_INVARIANTS:
                connection.execute(
                    """
                    INSERT INTO invariant
                        (invariant_id, title, statement, category, active,
                         version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.invariant_id,
                        item.title,
                        item.statement,
                        item.category,
                        int(item.active),
                        item.version,
                        now,
                        now,
                    ),
                )

    def list_invariants(self) -> list[Invariant]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM invariant ORDER BY invariant_id"
            ).fetchall()
        return [_row_to_invariant(row) for row in rows]

    def get(self, invariant_id: str) -> Invariant | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM invariant WHERE invariant_id = ?",
                (invariant_id,),
            ).fetchone()
        return _row_to_invariant(row) if row else None

    def change(
        self,
        invariant_id: str,
        statement: str,
        *,
        changed_by: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM invariant WHERE invariant_id = ?",
                (invariant_id,),
            ).fetchone()
            if row is None:
                raise KeyError(invariant_id)
            old = _row_to_invariant(row)
            updated = changed(old, statement)
            now = utcnow()
            connection.execute(
                """
                UPDATE invariant
                   SET statement = ?, version = ?, updated_at = ?
                 WHERE invariant_id = ?
                """,
                (updated.statement, updated.version, now, invariant_id),
            )
            connection.execute(
                """
                INSERT INTO invariant_change
                    (invariant_id, old_statement, new_statement, changed_by,
                     reason, version_after, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    invariant_id,
                    old.statement,
                    updated.statement,
                    changed_by,
                    reason,
                    updated.version,
                    now,
                ),
            )
        return {
            "invariant": updated.to_dict(),
            "old_statement": old.statement,
            "new_statement": updated.statement,
            "version": updated.version,
        }

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM invariant_change
                 ORDER BY id DESC
                 LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chat_message
                    (session_id, role, content, meta, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    content[:20_000],
                    json.dumps(meta, ensure_ascii=False) if meta else None,
                    utcnow(),
                ),
            )

    def messages(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM chat_message
                 WHERE session_id = ?
                 ORDER BY id DESC
                 LIMIT ?
                """,
                (session_id, max(1, min(int(limit), 300))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in reversed(rows):
            item: dict[str, Any] = {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            if row["meta"]:
                try:
                    item.update(json.loads(row["meta"]))
                except json.JSONDecodeError:
                    pass
            result.append(item)
        return result

    def record_attempt(
        self,
        session_id: str,
        prompt: str,
        decision: str,
        *,
        source: str,
        violations: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO attempt
                    (session_id, prompt, decision, source, violations, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    prompt[:2_000],
                    decision,
                    source,
                    json.dumps(violations or [], ensure_ascii=False),
                    utcnow(),
                ),
            )

    def attempts(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM attempt
                 WHERE session_id = ?
                 ORDER BY id DESC
                 LIMIT ?
                """,
                (session_id, max(1, min(int(limit), 300))),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            violations: list[dict[str, Any]] = []
            if row["violations"]:
                try:
                    violations = json.loads(row["violations"])
                except json.JSONDecodeError:
                    pass
            result.append(
                {
                    "id": row["id"],
                    "prompt": row["prompt"],
                    "decision": row["decision"],
                    "source": row["source"],
                    "violations": violations,
                    "created_at": row["created_at"],
                }
            )
        return result

    def attempt_stats(self, session_id: str) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN decision = 'refuse' THEN 1 ELSE 0 END) AS blocked,
                    SUM(CASE WHEN decision = 'allow' THEN 1 ELSE 0 END) AS allowed
                  FROM attempt
                 WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "blocked": int(row["blocked"] or 0),
            "allowed": int(row["allowed"] or 0),
        }
