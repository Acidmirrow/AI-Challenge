"""SQLite-хранилище диалогов урока 07.

Контекст хранится не в памяти процесса и не в Streamlit-сессии, а в файле
SQLite. Поэтому история переживает перезапуск API, контейнера и страницы.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ContextStore:
    """Сессии и сообщения в одном SQLite-файле."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
                    content TEXT NOT NULL,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    tool_calls TEXT NOT NULL DEFAULT '[]',
                    tool_call_id TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )
            # Старая схема разрешала только user/assistant. SQLite не умеет
            # менять CHECK, поэтому переносим данные в новую таблицу.
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'messages'"
            ).fetchone()
            if schema and "'tool'" not in (schema["sql"] or ""):
                conn.executescript(
                    """
                    DROP INDEX IF EXISTS idx_messages_session;
                    ALTER TABLE messages RENAME TO messages_legacy;
                    CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
                        content TEXT NOT NULL,
                        tokens INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        tool_calls TEXT NOT NULL DEFAULT '[]',
                        tool_call_id TEXT NOT NULL DEFAULT '',
                        name TEXT NOT NULL DEFAULT ''
                    );
                    INSERT INTO messages(id, session_id, role, content, tokens, created_at)
                        SELECT id, session_id, role, content, tokens, created_at
                        FROM messages_legacy;
                    DROP TABLE messages_legacy;
                    CREATE INDEX IF NOT EXISTS idx_messages_session
                        ON messages(session_id, id);
                    """
                )

            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(messages)")
            }
            migrations = {
                "tool_calls": "TEXT NOT NULL DEFAULT '[]'",
                "tool_call_id": "TEXT NOT NULL DEFAULT ''",
                "name": "TEXT NOT NULL DEFAULT ''",
            }
            for column, ddl in migrations.items():
                if column not in columns:
                    conn.execute(f"ALTER TABLE messages ADD COLUMN {column} {ddl}")

    def create_session(self, session_id: str, title: str = "") -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions(id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, title, _now(), _now()),
            )
        return self.get_session(session_id) or {}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.rowid AS number, s.*, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.id = ?
                GROUP BY s.id
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_session_by_number(self, number: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT s.rowid AS number, s.*, COUNT(m.id) AS message_count
                FROM sessions s
                LEFT JOIN messages m ON m.session_id = s.id
                WHERE s.rowid = ?
                GROUP BY s.id
                """,
                (number,),
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.rowid AS number, s.*, COUNT(m.id) AS message_count
                FROM sessions s
                JOIN messages m ON m.session_id = s.id
                GROUP BY s.id
                ORDER BY s.updated_at DESC, s.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def history(self, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT id, role, content, tokens, created_at, tool_calls, tool_call_id, name "
            "FROM messages WHERE session_id = ?"
        )
        params: list[Any] = [session_id]
        if limit is not None:
            sql = (
                "SELECT * FROM ("
                + sql
                + " ORDER BY id DESC LIMIT ?"
                + ") ORDER BY id ASC"
            )
            params.append(limit)
        else:
            sql += " ORDER BY id ASC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["tool_calls"] = json.loads(item.get("tool_calls") or "[]")
            except json.JSONDecodeError:
                item["tool_calls"] = []
            result.append(item)
        return result

    def append(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str = "",
        name: str = "",
    ) -> dict[str, Any]:
        if role not in ("user", "assistant", "tool"):
            raise ValueError(f"Неизвестная роль сообщения: {role}")
        created = _now()
        title = content.strip().replace("\n", " ")[:60] if role == "user" else ""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages(session_id, role, content, tokens, created_at, "
                "tool_calls, tool_call_id, name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    role,
                    content,
                    _tokens(content),
                    created,
                    json.dumps(tool_calls or [], ensure_ascii=False),
                    tool_call_id,
                    name,
                ),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ?, "
                "title = CASE WHEN title = '' AND ? != '' THEN ? ELSE title END "
                "WHERE id = ?",
                (created, title, title, session_id),
            )
            row = conn.execute(
                "SELECT id, role, content, tokens, created_at, tool_calls, tool_call_id, name "
                "FROM messages WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        if not row:
            return {}
        item = dict(row)
        try:
            item["tool_calls"] = json.loads(item.get("tool_calls") or "[]")
        except json.JSONDecodeError:
            item["tool_calls"] = []
        return item

    def clear(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE sessions SET updated_at = ?, title = '' WHERE id = ?",
                (_now(), session_id),
            )

    def delete(self, session_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def delete_all(self) -> tuple[int, int]:
        """Удалить все сессии и сообщения. Возвращает (сессии, сообщения)."""
        with self._connect() as conn:
            sessions = int(
                conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]
            )
            messages = int(
                conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
            )
            conn.execute("DELETE FROM messages")
            conn.execute("DELETE FROM sessions")
        return sessions, messages

    def count_sessions(self) -> int:
        """Считать только диалоги, в которых есть хотя бы одно сообщение."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM sessions s "
                "WHERE EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)"
            ).fetchone()
        return int(row["n"]) if row else 0
