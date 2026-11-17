"""Трёхслойная память ассистента с правилами best practice.

Слои:
- краткосрочная память — последние сообщения текущего диалога, TTL;
- рабочая память — данные текущей задачи, TTL;
- долговременная память — профиль, решения и знания; структурированное
  хранилище, provenance, confidence, TTL и FTS5-поиск.

Долговременная память не является «свалкой»: в контекст попадает только
релевантная выборка в пределах бюджета токенов.
"""

from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SHORT_TERM_LIMIT = 24
SHORT_TERM_PROMPT_WINDOW = 8
SHORT_TERM_TTL_HOURS = 24
WORKING_TTL_HOURS = 72
LONG_TERM_RETRIEVE_LIMIT = 8
LONG_TERM_CONTEXT_TOKENS = 900
DEFAULT_OWNER = "demo"
DEFAULT_SESSION_ID = "demo"
DEFAULT_DB_PATH = "/srv/data/memory.db"
WORKING_FIELDS = ("title", "goal", "status", "next_step", "constraints")
LONG_SECTIONS = ("profile", "decisions", "knowledge")

#: Демо-профиль: стартовый пример, а не персональные данные.
DEFAULT_LONG_TERM = (
    ("profile", "Имя", "Пользователь", "демо-профиль", 0.6),
    ("profile", "Роль", "Студент курса AI Challenge", "демо-профиль", 0.6),
    (
        "profile",
        "Предпочтения",
        "Русский язык; краткие ответы; сначала факты, потом выводы",
        "демо-профиль",
        0.6,
    ),
    (
        "decisions",
        "Провайдер",
        "OpenCode Go: deepseek-v4.1-flash для чата, deepseek-v4-pro для анализа",
        "история проекта",
        0.9,
    ),
    (
        "decisions",
        "Модель памяти",
        "Три слоя: краткосрочная, рабочая и долговременная память",
        "урок 11",
        0.9,
    ),
    (
        "knowledge",
        "Курс",
        "AI Challenge: уроки 01–11, урок 11 — модель памяти",
        "карта курса",
        0.8,
    ),
    (
        "knowledge",
        "Стек",
        "FastAPI + Streamlit, общий gateway и front",
        "архитектура проекта",
        0.8,
    ),
)

_SECRET_RE = re.compile(
    r"(?i)(oc_sk_[a-z0-9_-]{8,}|sk-[a-z0-9_-]{12,}|"
    r"bearer\s+[a-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S{8,}|"
    r"password\s*[:=]\s*\S{4,})"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _expires(hours: float | None) -> str:
    if hours is None:
        return ""
    return _iso(_now() + timedelta(hours=hours))


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _text(value: Any, limit: int = 4_000) -> str:
    return str(value or "").strip()[:limit]


def _owner(value: str | None) -> str:
    return _text(value, 80) or DEFAULT_OWNER


def _assert_safe(value: str) -> None:
    if _SECRET_RE.search(value):
        raise ValueError("Похоже на секрет или ключ: запись в память запрещена")


class MemoryStore:
    """Хранилище трёх слоёв памяти."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fts = False
        self._init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS short_term (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_short_session
                    ON short_term(owner_id, session_id, id);

                CREATE TABLE IF NOT EXISTS working (
                    session_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    title TEXT NOT NULL DEFAULT '',
                    goal TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    next_step TEXT NOT NULL DEFAULT '',
                    constraints TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS long_term (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    section TEXT NOT NULL CHECK (section IN ('profile', 'decisions', 'knowledge')),
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    importance REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(owner_id, section, key)
                );

                CREATE TABLE IF NOT EXISTS long_term_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    owner_id TEXT NOT NULL,
                    section TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0.7,
                    superseded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

            # Миграция старой схемы урока 11 без потери записей.
            short_columns = self._columns(conn, "short_term")
            if "owner_id" not in short_columns:
                conn.execute(
                    "ALTER TABLE short_term ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'demo'"
                )
                conn.execute(
                    "ALTER TABLE short_term ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''"
                )
                short_columns = self._columns(conn, "short_term")
            for column in ("prompt_tokens", "completion_tokens"):
                if column not in short_columns:
                    conn.execute(
                        f"ALTER TABLE short_term ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                    )
            if "owner_id" not in self._columns(conn, "working"):
                conn.execute(
                    "ALTER TABLE working ADD COLUMN owner_id TEXT NOT NULL DEFAULT 'demo'"
                )
                conn.execute(
                    "ALTER TABLE working ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''"
                )

            long_columns = self._columns(conn, "long_term")
            if long_columns and "owner_id" not in long_columns:
                conn.executescript(
                    """
                    ALTER TABLE long_term RENAME TO long_term_legacy;
                    CREATE TABLE long_term (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        owner_id TEXT NOT NULL DEFAULT 'demo',
                        section TEXT NOT NULL CHECK (section IN ('profile', 'decisions', 'knowledge')),
                        key TEXT NOT NULL,
                        value TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT '',
                        confidence REAL NOT NULL DEFAULT 0.7,
                        importance REAL NOT NULL DEFAULT 0.5,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT NOT NULL DEFAULT '',
                        UNIQUE(owner_id, section, key)
                    );
                    INSERT INTO long_term(
                        id, owner_id, section, key, value, source, confidence,
                        importance, status, created_at, updated_at, expires_at
                    )
                    SELECT id, 'demo', section, key, value, source, 0.7, 0.5,
                           'active', created_at, updated_at, ''
                    FROM long_term_legacy;
                    DROP TABLE long_term_legacy;
                    """
                )

            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS long_term_fts USING fts5(
                        content,
                        section UNINDEXED,
                        item_id UNINDEXED,
                        owner_id UNINDEXED,
                        tokenize='unicode61'
                    )
                    """
                )
                self._fts = True
            except sqlite3.OperationalError:
                self._fts = False

            seeded = conn.execute(
                "SELECT value FROM meta WHERE key = 'seeded'"
            ).fetchone()
            if seeded is None:
                count = conn.execute("SELECT COUNT(*) AS n FROM long_term").fetchone()["n"]
                if count == 0:
                    now = _iso(_now())
                    for section, key, value, source, confidence in DEFAULT_LONG_TERM:
                        conn.execute(
                            "INSERT INTO long_term(owner_id, section, key, value, source, "
                            "confidence, importance, status, created_at, updated_at, expires_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                            (
                                DEFAULT_OWNER,
                                section,
                                key,
                                value,
                                source,
                                confidence,
                                0.7 if section == "profile" else 0.8,
                                now,
                                now,
                                _expires(24 * 180) if section == "knowledge" else "",
                            ),
                        )
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES ('seeded', '1')"
                )

            self._rebuild_fts(conn)

    def _rebuild_fts(self, conn: sqlite3.Connection) -> None:
        if not self._fts:
            return
        conn.execute("DELETE FROM long_term_fts")
        rows = conn.execute(
            "SELECT id, owner_id, section, key, value FROM long_term "
            "WHERE status = 'active'"
        ).fetchall()
        for row in rows:
            conn.execute(
                "INSERT INTO long_term_fts(content, section, item_id, owner_id) "
                "VALUES (?, ?, ?, ?)",
                (f"{row['key']}: {row['value']}", row["section"], str(row["id"]), row["owner_id"]),
            )

    def _sync_fts(self, conn: sqlite3.Connection, item: dict[str, Any]) -> None:
        if not self._fts:
            return
        conn.execute("DELETE FROM long_term_fts WHERE item_id = ?", (str(item["id"]),))
        conn.execute(
            "INSERT INTO long_term_fts(content, section, item_id, owner_id) "
            "VALUES (?, ?, ?, ?)",
            (
                f"{item['key']}: {item['value']}",
                item["section"],
                str(item["id"]),
                item["owner_id"],
            ),
        )

    def state(self, owner_id: str = DEFAULT_OWNER, session_id: str = DEFAULT_SESSION_ID) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        session_id = _text(session_id, 80) or DEFAULT_SESSION_ID
        now = _iso(_now())
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM short_term WHERE owner_id = ? AND session_id = ? "
                "AND expires_at != '' AND expires_at <= ?",
                (owner_id, session_id, now),
            )
            short_rows = conn.execute(
                "SELECT id, owner_id, role, content, tokens, prompt_tokens, "
                "completion_tokens, created_at, expires_at "
                "FROM short_term WHERE owner_id = ? AND session_id = ? ORDER BY id ASC",
                (owner_id, session_id),
            ).fetchall()
            working = conn.execute(
                "SELECT * FROM working WHERE owner_id = ? AND session_id = ? "
                "AND (expires_at = '' OR expires_at > ?)",
                (owner_id, session_id, now),
            ).fetchone()
            long_rows = conn.execute(
                "SELECT id, owner_id, section, key, value, source, confidence, importance, "
                "status, created_at, updated_at, expires_at FROM long_term "
                "WHERE owner_id = ? AND status = 'active' "
                "AND (expires_at = '' OR expires_at > ?) ORDER BY section, key",
                (owner_id, now),
            ).fetchall()

        short = [dict(row) for row in short_rows]
        long_items = [dict(row) for row in long_rows]
        grouped: dict[str, list[dict[str, Any]]] = {
            section: [item for item in long_items if item["section"] == section]
            for section in LONG_SECTIONS
        }
        return {
            "owner_id": owner_id,
            "session_id": session_id,
            "short_term": {
                "messages": short,
                "count": len(short),
                "limit": SHORT_TERM_LIMIT,
                "prompt_window": SHORT_TERM_PROMPT_WINDOW,
                "tokens": sum(item["tokens"] for item in short),
                "ttl_hours": SHORT_TERM_TTL_HOURS,
            },
            "working": dict(working) if working else {
                "session_id": session_id,
                "owner_id": owner_id,
                **{field: "" for field in WORKING_FIELDS},
                "updated_at": "",
                "expires_at": "",
            },
            "long_term": {
                "items": long_items,
                "count": len(long_items),
                "retrieval_limit": LONG_TERM_RETRIEVE_LIMIT,
                **grouped,
            },
        }

    def append_short(
        self,
        owner_id: str,
        session_id: str,
        role: str,
        content: str,
        *,
        ttl_hours: float = SHORT_TERM_TTL_HOURS,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        session_id = _text(session_id, 80) or DEFAULT_SESSION_ID
        role = _text(role, 20)
        content = _text(content, 4_000)
        if role not in ("user", "assistant"):
            raise ValueError("Роль должна быть user или assistant")
        if not content:
            raise ValueError("Сообщение не может быть пустым")
        created = _iso(_now())
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO short_term(owner_id, session_id, role, content, tokens, "
                "prompt_tokens, completion_tokens, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    owner_id,
                    session_id,
                    role,
                    content,
                    _tokens(content),
                    max(0, int(prompt_tokens)),
                    max(0, int(completion_tokens)),
                    created,
                    _expires(ttl_hours),
                ),
            )
            conn.execute(
                "DELETE FROM short_term WHERE owner_id = ? AND session_id = ? AND id NOT IN ("
                "SELECT id FROM short_term WHERE owner_id = ? AND session_id = ? "
                "ORDER BY id DESC LIMIT ?)",
                (owner_id, session_id, owner_id, session_id, SHORT_TERM_LIMIT),
            )
            row = conn.execute(
                "SELECT id, owner_id, role, content, tokens, prompt_tokens, "
                "completion_tokens, created_at, expires_at "
                "FROM short_term WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return dict(row) if row else {}

    def clear_short(self, owner_id: str = DEFAULT_OWNER, session_id: str = DEFAULT_SESSION_ID) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM short_term WHERE owner_id = ? AND session_id = ?",
                (_owner(owner_id), session_id),
            )
        return cursor.rowcount

    def set_working(
        self, owner_id: str, session_id: str, values: dict[str, Any], *, ttl_hours: float = WORKING_TTL_HOURS
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        session_id = _text(session_id, 80) or DEFAULT_SESSION_ID
        clean = {field: _text(values.get(field), 4_000) for field in WORKING_FIELDS}
        with self._connect() as conn:
            if not any(clean.values()):
                conn.execute(
                    "DELETE FROM working WHERE owner_id = ? AND session_id = ?",
                    (owner_id, session_id),
                )
            else:
                conn.execute(
                    "INSERT INTO working(session_id, owner_id, title, goal, status, next_step, "
                    "constraints, updated_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(session_id) DO UPDATE SET owner_id=excluded.owner_id, "
                    "title=excluded.title, goal=excluded.goal, status=excluded.status, "
                    "next_step=excluded.next_step, constraints=excluded.constraints, "
                    "updated_at=excluded.updated_at, expires_at=excluded.expires_at",
                    (
                        session_id,
                        owner_id,
                        clean["title"],
                        clean["goal"],
                        clean["status"],
                        clean["next_step"],
                        clean["constraints"],
                        _iso(_now()),
                        _expires(ttl_hours),
                    ),
                )
        return self.state(owner_id, session_id)["working"]

    def clear_working(self, owner_id: str = DEFAULT_OWNER, session_id: str = DEFAULT_SESSION_ID) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM working WHERE owner_id = ? AND session_id = ?",
                (_owner(owner_id), session_id),
            )
        return cursor.rowcount

    def upsert_long(
        self,
        owner_id: str,
        section: str,
        key: str,
        value: str,
        source: str = "пользователь",
        *,
        confidence: float = 0.7,
        importance: float = 0.5,
        ttl_hours: float | None = None,
    ) -> dict[str, Any]:
        owner_id = _owner(owner_id)
        section = _text(section, 20)
        key = _text(key, 120)
        value = _text(value, 4_000)
        source = _text(source, 200) or "пользователь"
        if section not in LONG_SECTIONS:
            raise ValueError("Неизвестный раздел долговременной памяти")
        if not key or not value:
            raise ValueError("Ключ и значение не могут быть пустыми")
        _assert_safe(key)
        _assert_safe(value)
        _assert_safe(source)
        confidence = max(0.0, min(1.0, float(confidence)))
        importance = max(0.0, min(1.0, float(importance)))
        if ttl_hours is None and section == "knowledge":
            ttl_hours = 24 * 180
        now = _iso(_now())
        with self._connect() as conn:
            old = conn.execute(
                "SELECT * FROM long_term WHERE owner_id = ? AND section = ? AND key = ?",
                (owner_id, section, key),
            ).fetchone()
            if old:
                conn.execute(
                    "INSERT INTO long_term_history(item_id, owner_id, section, key, value, "
                    "source, confidence, superseded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        old["id"],
                        old["owner_id"],
                        old["section"],
                        old["key"],
                        old["value"],
                        old["source"],
                        old["confidence"],
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE long_term SET value = ?, source = ?, confidence = ?, importance = ?, "
                    "status = 'active', updated_at = ?, expires_at = ? WHERE id = ?",
                    (value, source, confidence, importance, now, _expires(ttl_hours), old["id"]),
                )
                item_id = old["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO long_term(owner_id, section, key, value, source, confidence, "
                    "importance, status, created_at, updated_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                    (owner_id, section, key, value, source, confidence, importance, now, now, _expires(ttl_hours)),
                )
                item_id = int(cursor.lastrowid or 0)
            row = conn.execute(
                "SELECT id, owner_id, section, key, value, source, confidence, importance, "
                "status, created_at, updated_at, expires_at FROM long_term WHERE id = ?",
                (item_id,),
            ).fetchone()
            if row:
                self._sync_fts(conn, dict(row))
        return dict(row) if row else {}

    def delete_long(self, owner_id: str, item_id: int) -> bool:
        owner_id = _owner(owner_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM long_term WHERE id = ? AND owner_id = ?",
                (item_id, owner_id),
            ).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM long_term WHERE id = ?", (item_id,))
            if self._fts:
                conn.execute("DELETE FROM long_term_fts WHERE item_id = ?", (str(item_id),))
        return True

    def history(self, owner_id: str, section: str, key: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM long_term_history WHERE owner_id = ? AND section = ? "
                "AND key = ? ORDER BY id DESC",
                (_owner(owner_id), section, key),
            ).fetchall()
        return [dict(row) for row in rows]

    def retrieve(
        self,
        owner_id: str = DEFAULT_OWNER,
        query: str = "",
        *,
        limit: int = LONG_TERM_RETRIEVE_LIMIT,
        max_tokens: int = LONG_TERM_CONTEXT_TOKENS,
    ) -> list[dict[str, Any]]:
        """Вернуть релевантную выборку, а не всю долговременную память."""
        owner_id = _owner(owner_id)
        now = _iso(_now())
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, owner_id, section, key, value, source, confidence, importance, "
                "status, created_at, updated_at, expires_at FROM long_term "
                "WHERE owner_id = ? AND status = 'active' "
                "AND (expires_at = '' OR expires_at > ?) ORDER BY section, key",
                (owner_id, now),
            ).fetchall()
            candidates = [dict(row) for row in rows]
            matched: list[dict[str, Any]] = []
            terms = [term for term in re.findall(r"[\w-]+", query, flags=re.UNICODE) if len(term) > 1]
            if self._fts and terms:
                fts_query = " OR ".join(f'"{term}"' for term in terms[:12])
                try:
                    matched = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT l.*, bm25(long_term_fts) AS rank FROM long_term_fts f "
                            "JOIN long_term l ON l.id = CAST(f.item_id AS INTEGER) "
                            "WHERE long_term_fts MATCH ? AND l.owner_id = ? AND l.status = 'active' "
                            "AND (l.expires_at = '' OR l.expires_at > ?) "
                            "ORDER BY rank LIMIT ?",
                            (fts_query, owner_id, now, max(limit * 2, 12)),
                        ).fetchall()
                    ]
                except sqlite3.OperationalError:
                    matched = []

        by_id = {item["id"]: item for item in candidates}
        for item in matched:
            if item["id"] in by_id:
                by_id[item["id"]]["rank"] = item.get("rank")
        profile = [item for item in candidates if item["section"] == "profile"]
        chosen: list[dict[str, Any]] = []
        seen: set[int] = set()
        for item in profile[:3] + (matched or candidates):
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            chosen.append(item)

        def score(item: dict[str, Any]) -> tuple[float, float, int]:
            rank = item.get("rank")
            relevance = 1.0 if rank is None else 1.0 / (1.0 + abs(float(rank)))
            confidence = float(item.get("confidence") or 0.5)
            importance = float(item.get("importance") or 0.5)
            recent = item.get("updated_at") or item.get("created_at") or ""
            try:
                age_days = max(0.0, (_now() - datetime.fromisoformat(recent)).total_seconds() / 86_400)
            except (TypeError, ValueError):
                age_days = 365.0
            recency = 1.0 / (1.0 + age_days / 30.0)
            return (relevance * 0.4 + confidence * 0.25 + importance * 0.2 + recency * 0.15, recency, item["id"])

        # Профиль — устойчивый контекст и не должен вытесняться случайными фактами.
        profile_chosen = profile[:3]
        others = [item for item in (matched or candidates) if item["id"] not in {p["id"] for p in profile_chosen}]
        others.sort(key=score, reverse=True)
        chosen = profile_chosen + others
        selected: list[dict[str, Any]] = []
        used = 0
        for item in chosen:
            cost = _tokens(f"{item['key']}: {item['value']}")
            if selected and used + cost > max_tokens:
                continue
            selected.append(item)
            used += cost
            if len(selected) >= limit:
                break
        return selected

    def reset_session(self, owner_id: str = DEFAULT_OWNER, session_id: str = DEFAULT_SESSION_ID) -> dict[str, int]:
        short = self.clear_short(owner_id, session_id)
        working = self.clear_working(owner_id, session_id)
        return {"short_term": short, "working": working}

    def stats(self, owner_id: str = DEFAULT_OWNER, session_id: str = DEFAULT_SESSION_ID) -> dict[str, Any]:
        state = self.state(owner_id, session_id)
        return {
            "short_term": state["short_term"]["count"],
            "working": sum(1 for field in WORKING_FIELDS if state["working"].get(field)),
            "long_term": state["long_term"]["count"],
            "prompt_window": SHORT_TERM_PROMPT_WINDOW,
            "short_limit": SHORT_TERM_LIMIT,
            "retrieval_limit": LONG_TERM_RETRIEVE_LIMIT,
        }
