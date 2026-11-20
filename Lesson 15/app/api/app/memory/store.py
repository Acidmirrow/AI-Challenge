"""Политики и SQLite-хранилище памяти урока 15."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class FactPolicy:
    key: str
    title: str
    policy: str  # replace | append
    category: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "title": self.title,
            "policy": self.policy,
            "category": self.category,
            "description": self.description,
        }


FACT_POLICIES: tuple[FactPolicy, ...] = (
    FactPolicy("deadline", "Срок", "replace", "schedule", "Новое значение заменяет старое."),
    FactPolicy("status", "Статус", "replace", "schedule", "Новый статус заменяет старый."),
    FactPolicy("version", "Версия", "replace", "product", "Новая версия заменяет старую."),
    FactPolicy("approach", "Подход", "replace", "architecture", "Выбранный подход заменяет предыдущий."),
    FactPolicy(
        "sms_requirement",
        "Требование SMS",
        "replace",
        "business",
        "Статус требования заменяется: активно или отменено.",
    ),
    FactPolicy(
        "decisions",
        "Принятые решения",
        "append",
        "history",
        "Накапливается списком; старые решения не теряются.",
    ),
    FactPolicy(
        "change_history",
        "История изменений",
        "append",
        "history",
        "Накапливается списком для аудита.",
    ),
)

POLICY_BY_KEY = {item.key: item for item in FACT_POLICIES}

DEFAULT_FACTS: tuple[tuple[str, str], ...] = (
    ("deadline", "15 декабря"),
    ("status", "в работе"),
    ("version", "v1"),
    ("approach", "Ручная проверка"),
    ("sms_requirement", "SMS-уведомления обязательны"),
    ("decisions", "Выбрали SQLite для хранения"),
    ("change_history", "Стартовые значения памяти"),
)


@dataclass(frozen=True)
class Fact:
    key: str
    title: str
    value: str
    policy: str
    category: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "value": self.value,
            "policy": self.policy,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class MemoryStore:
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
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS fact (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    value TEXT NOT NULL,
                    policy TEXT NOT NULL,
                    category TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(owner_id, key)
                );

                CREATE TABLE IF NOT EXISTS fact_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    old_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    change_type TEXT NOT NULL,
                    reason TEXT,
                    changed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS short_term (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS working (
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    session_id TEXT NOT NULL,
                    goal TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    next_step TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(owner_id, session_id)
                );

                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL DEFAULT 'demo',
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    stale_count INTEGER NOT NULL DEFAULT 0,
                    stale_values TEXT NOT NULL DEFAULT '',
                    old_values_in_prompt TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )

    def _seed(self) -> None:
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) AS n FROM fact").fetchone()["n"]
            if count:
                return
            stamp = now_iso()
            for key, value in DEFAULT_FACTS:
                policy = POLICY_BY_KEY[key]
                connection.execute(
                    """
                    INSERT INTO fact(owner_id, key, title, value, policy, category,
                                     created_at, updated_at)
                    VALUES ('demo', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (key, policy.title, value, policy.policy, policy.category, stamp, stamp),
                )

    def facts(self) -> list[Fact]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM fact WHERE owner_id = 'demo' ORDER BY category, key"
            ).fetchall()
        return [
            Fact(
                key=row["key"],
                title=row["title"],
                value=row["value"],
                policy=row["policy"],
                category=row["category"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def fact(self, key: str) -> Fact | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fact WHERE owner_id = 'demo' AND key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return Fact(
            row["key"], row["title"], row["value"], row["policy"],
            row["category"], row["created_at"], row["updated_at"],
        )

    def history(self, key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if key:
                rows = connection.execute(
                    "SELECT * FROM fact_history WHERE owner_id = 'demo' AND key = ? "
                    "ORDER BY id DESC LIMIT ?",
                    (key, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM fact_history WHERE owner_id = 'demo' "
                    "ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def old_values(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT old_value FROM fact_history "
                "WHERE owner_id = 'demo' AND change_type = 'replace'"
            ).fetchall()
        return [row["old_value"] for row in rows if row["old_value"]]

    def update(self, key: str, value: str, *, reason: str = "") -> dict[str, Any]:
        value = str(value or "").strip()
        if not value:
            raise ValueError("Значение факта не может быть пустым")
        policy = POLICY_BY_KEY.get(key)
        if policy is None:
            raise KeyError(key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM fact WHERE owner_id = 'demo' AND key = ?", (key,)
            ).fetchone()
            if not row:
                raise KeyError(key)
            old_value = row["value"]
            stamp = now_iso()
            if policy.policy == "append":
                existing_items = []
                for line in old_value.splitlines():
                    item = line.strip()
                    if item.startswith("- "):
                        item = item[2:].strip()
                    if item:
                        existing_items.append(item)
                if value in existing_items:
                    return {
                        "key": key,
                        "title": policy.title,
                        "old_value": old_value,
                        "new_value": old_value,
                        "policy": policy.policy,
                        "changed": False,
                        "skipped": True,
                        "reason": "duplicate",
                        "message": f"Значение «{value}» уже есть в «{policy.title}»; не добавлено.",
                        "updated_at": row["updated_at"],
                    }
                new_value = (
                    f"{old_value}\n- {value}" if old_value.strip() else f"- {value}"
                )
            else:
                new_value = value
            changed = new_value != old_value
            connection.execute(
                "UPDATE fact SET value = ?, updated_at = ? WHERE id = ?",
                (new_value, stamp, row["id"]),
            )
            if changed:
                connection.execute(
                    """
                    INSERT INTO fact_history(owner_id, key, title, old_value,
                        new_value, change_type, reason, changed_at)
                    VALUES ('demo', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        row["title"],
                        old_value,
                        new_value,
                        policy.policy,
                        reason,
                        stamp,
                    ),
                )
                # change_history — накопительный журнал. Любое изменение
                # факта (кроме самого журнала) добавляет строку с «было → стало».
                if key != "change_history":
                    history_row = connection.execute(
                        "SELECT id, value FROM fact WHERE owner_id = 'demo' "
                        "AND key = 'change_history'"
                    ).fetchone()
                    old_log = history_row["value"] if history_row else ""
                    if policy.policy == "append":
                        log_line = (
                            f"{stamp[:19]} · {row['title']}: "
                            f"добавлено «{str(value).replace(chr(10), ' ')}»"
                        )
                    else:
                        log_line = (
                            f"{stamp[:19]} · {row['title']}: "
                            f"{str(old_value).replace(chr(10), ' ')} → "
                            f"{str(new_value).replace(chr(10), ' ')}"
                        )
                    if len(log_line) > 1_000:
                        log_line = log_line[:997] + "…"
                    new_log = f"{old_log}\n- {log_line}" if old_log else f"- {log_line}"
                    if history_row:
                        connection.execute(
                            "UPDATE fact SET value = ?, updated_at = ? WHERE id = ?",
                            (new_log, stamp, history_row["id"]),
                        )
        return {
            "key": key,
            "title": policy.title,
            "old_value": old_value,
            "new_value": new_value,
            "policy": policy.policy,
            "changed": changed,
            "skipped": False,
            "updated_at": stamp,
        }

    def append_short(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO short_term(owner_id, session_id, role, content, created_at) "
                "VALUES ('demo', ?, ?, ?, ?)",
                (session_id, role, content[:8_000], now_iso()),
            )

    def short_term(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM short_term WHERE owner_id = 'demo' AND session_id = ? "
                "ORDER BY id ASC",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_working(self, session_id: str, goal: str, status: str, next_step: str = "") -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO working(owner_id, session_id, goal, status, next_step, updated_at)
                VALUES ('demo', ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, session_id) DO UPDATE SET
                    goal=excluded.goal, status=excluded.status,
                    next_step=excluded.next_step, updated_at=excluded.updated_at
                """,
                (session_id, goal[:2_000], status[:200], next_step[:2_000], now_iso()),
            )
        return self.working(session_id)

    def working(self, session_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM working WHERE owner_id = 'demo' AND session_id = ?",
                (session_id,),
            ).fetchone()
        return dict(row) if row else {}

    def clear_working(self, session_id: str) -> dict[str, int]:
        with self._connect() as connection:
            working = connection.execute(
                "DELETE FROM working WHERE owner_id = 'demo' AND session_id = ?",
                (session_id,),
            ).rowcount
            short = connection.execute(
                "DELETE FROM short_term WHERE owner_id = 'demo' AND session_id = ?",
                (session_id,),
            ).rowcount
        return {"working": working, "short_term": short}

    def prompt_block(self) -> str:
        lines = ["АКТУАЛЬНАЯ ДОЛГОВРЕМЕННАЯ ПАМЯТЬ:"]
        for item in self.facts():
            # change_history — аудит «было → стало», а не актуальное значение.
            # В промпт он не попадает, иначе старые значения снова окажутся
            # в контексте модели.
            if item.key == "change_history":
                continue
            lines.append(
                f"- {item.key} «{item.title}»: {item.value} "
                f"(обновлено {item.updated_at})"
            )
        return "\n".join(lines)

    def prompt_old_values(self) -> list[str]:
        prompt = self.prompt_block().lower()
        return [value for value in self.old_values() if value.lower() in prompt]

    def stale_in_answer(self, answer: str) -> list[str]:
        lowered = (answer or "").lower()
        return [value for value in self.old_values() if value.lower() in lowered]

    def record_audit(
        self,
        session_id: str,
        question: str,
        answer: str,
        stale: list[str],
        old_in_prompt: list[str],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO audit(owner_id, session_id, question, answer,
                    stale_count, stale_values, old_values_in_prompt, created_at)
                VALUES ('demo', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    question[:2_000],
                    answer[:8_000],
                    len(stale),
                    "\n".join(stale),
                    "\n".join(old_in_prompt),
                    now_iso(),
                ),
            )

    def audits(self, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit WHERE owner_id = 'demo' AND session_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def stale_stats(self, session_id: str) -> dict[str, int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(stale_count), 0) AS stale "
                "FROM audit WHERE owner_id = 'demo' AND session_id = ?",
                (session_id,),
            ).fetchone()
        return {"answers": int(row["total"] or 0), "stale_answers": int(row["stale"] or 0)}

    def state(self, session_id: str) -> dict[str, Any]:
        return {
            "facts": [item.to_dict() for item in self.facts()],
            "working": self.working(session_id),
            "short_term": self.short_term(session_id),
            "history": self.history(limit=50),
            "policies": [item.to_dict() for item in FACT_POLICIES],
            "prompt": self.prompt_block(),
            "old_values_in_prompt": self.prompt_old_values(),
            "stale": self.stale_stats(session_id),
        }
