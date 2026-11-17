"""Профиль пользователя и предпочтения для урока 12.

Профиль хранится отдельно от истории диалога. Каждое изменение фиксируется
в истории, чтобы было видно, что пришло из ручной формы, а что из диалога.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_OWNER = "demo"
DEFAULT_SESSION_ID = "demo"
DEFAULT_DB_PATH = "/srv/data/profile.db"
PROFILE_FIELDS = ("name", "role", "city", "language", "timezone")
PREFERENCE_KEYS = ("style", "format", "code_examples", "emoji", "constraints")
SECRET_PATTERN = re.compile(
    r"(?i)(oc_sk_[a-z0-9_-]{8,}|sk-[a-z0-9_-]{12,}|api[_-]?key\s*[:=]\s*\S+|"
    r"password\s*[:=]\s*\S+|bearer\s+\S+)"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(value: str | None, limit: int = 500) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


TEST_PROFILES = (
    {
        "owner_id": "demo",
        "profile": {
            "name": "Борис",
            "role": "разработчик",
            "city": "Москва",
            "language": "русский",
            "timezone": "Europe/Moscow",
        },
        "preferences": {
            "style": "обращение на «ты»",
            "format": "кратко",
            "code_examples": "с примерами кода",
            "emoji": "без emoji",
            "constraints": "без воды",
        },
    },
    {
        "owner_id": "test-alice",
        "profile": {"name": "Анна", "role": "аналитик", "city": "Москва", "language": "русский", "timezone": "Europe/Moscow"},
        "preferences": {
            "style": "формальный",
            "format": "таблицей",
            "code_examples": "без примеров кода",
            "emoji": "без emoji",
            "constraints": "без воды",
        },
    },
    {
        "owner_id": "test-elena",
        "profile": {"name": "Елена", "role": "продакт-менеджер", "city": "Казань", "language": "русский", "timezone": "Europe/Moscow"},
        "preferences": {
            "style": "формальный",
            "format": "списком",
            "code_examples": "без примеров кода",
            "emoji": "с emoji",
            "constraints": "без воды",
        },
    },
    {
        "owner_id": "test-ivan",
        "profile": {"name": "Иван", "role": "студент", "city": "Новосибирск", "language": "русский", "timezone": "Asia/Novosibirsk"},
        "preferences": {
            "style": "неформальный",
            "format": "пошагово",
            "code_examples": "с примерами кода",
            "emoji": "с emoji",
            "constraints": "с примерами",
        },
    },
    {
        "owner_id": "test-olga",
        "profile": {"name": "Ольга", "role": "дизайнер", "city": "Екатеринбург", "language": "русский", "timezone": "Asia/Yekaterinburg"},
        "preferences": {
            "style": "неформальный",
            "format": "кратко",
            "code_examples": "с примерами кода",
            "emoji": "без emoji",
            "constraints": "без канцелярита",
        },
    },
)


class ProfileStore:
    """Небольшое SQLite-хранилище профиля, предпочтений и истории диалога."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    owner_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    owner_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'пользователь',
                    confidence REAL NOT NULL DEFAULT 0.8,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    key TEXT NOT NULL,
                    old_value TEXT NOT NULL DEFAULT '',
                    new_value TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS messages_session_idx "
                "ON messages(owner_id, session_id, id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS history_owner_idx ON history(owner_id, id)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _row_profile(self, row: sqlite3.Row | None) -> dict[str, str]:
        return {
            field: (row[field] if row else "")
            for field in PROFILE_FIELDS
        }

    def get(self, owner_id: str = DEFAULT_OWNER) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM profiles WHERE owner_id = ?", (owner_id,)
            ).fetchone()
            preference_rows = conn.execute(
                "SELECT key, value, source, confidence, updated_at "
                "FROM preferences WHERE owner_id = ? ORDER BY key",
                (owner_id,),
            ).fetchall()
            history_rows = conn.execute(
                "SELECT kind, key, old_value, new_value, source, changed_at "
                "FROM history WHERE owner_id = ? ORDER BY id DESC LIMIT 20",
                (owner_id,),
            ).fetchall()
        preferences = [dict(item) for item in preference_rows]
        profile = self._row_profile(row)
        return {
            "owner_id": owner_id,
            "profile": profile,
            "preferences": preferences,
            "preference_map": {item["key"]: item["value"] for item in preferences},
            "history": [dict(item) for item in history_rows],
            "updated_at": row["updated_at"] if row else "",
            "filled": sum(1 for value in profile.values() if value),
        }

    def save_profile(
        self,
        owner_id: str,
        values: dict[str, str],
        *,
        source: str = "пользователь",
    ) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        current = self.get(owner_id)["profile"]
        clean_values = {
            field: _clean(values.get(field, current[field]), 200)
            for field in PROFILE_FIELDS
        }
        changed = {
            field: value
            for field, value in clean_values.items()
            if value != current[field]
        }
        if not changed:
            return self.get(owner_id)
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles(owner_id, name, role, city, language, timezone, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id) DO UPDATE SET
                    name=excluded.name, role=excluded.role, city=excluded.city,
                    language=excluded.language, timezone=excluded.timezone,
                    updated_at=excluded.updated_at
                """,
                (
                    owner_id,
                    clean_values["name"],
                    clean_values["role"],
                    clean_values["city"],
                    clean_values["language"],
                    clean_values["timezone"],
                    now,
                ),
            )
            for field, value in changed.items():
                conn.execute(
                    "INSERT INTO history(owner_id, kind, key, old_value, new_value, source, changed_at) "
                    "VALUES (?, 'profile', ?, ?, ?, ?, ?)",
                    (owner_id, field, current[field], value, source, now),
                )
        return self.get(owner_id)

    def set_preference(
        self,
        owner_id: str,
        key: str,
        value: str,
        *,
        source: str = "пользователь",
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        key = _clean(key, 80)
        value = _clean(value, 500)
        if key not in PREFERENCE_KEYS:
            raise ValueError("Неизвестное предпочтение")
        if not value:
            raise ValueError("Значение предпочтения не может быть пустым")
        if SECRET_PATTERN.search(value):
            raise ValueError("Похоже на секрет: значение не сохранено")
        old = next(
            (
                item["value"]
                for item in self.get(owner_id)["preferences"]
                if item["key"] == key
            ),
            "",
        )
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences(owner_id, key, value, source, confidence, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_id, key) DO UPDATE SET
                    value=excluded.value, source=excluded.source,
                    confidence=excluded.confidence, updated_at=excluded.updated_at
                """,
                (owner_id, key, value, source, max(0.0, min(1.0, confidence)), now),
            )
            if old != value:
                conn.execute(
                    "INSERT INTO history(owner_id, kind, key, old_value, new_value, source, changed_at) "
                    "VALUES (?, 'preference', ?, ?, ?, ?, ?)",
                    (owner_id, key, old, value, source, now),
                )
        return self.get(owner_id)

    def delete_preference(self, owner_id: str, key: str) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM preferences WHERE owner_id = ? AND key = ?",
                (owner_id, _clean(key, 80)),
            )
        return self.get(owner_id)

    def append_message(
        self, owner_id: str, session_id: str, role: str, content: str
    ) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        session_id = _clean(session_id, 80) or DEFAULT_SESSION_ID
        content = _clean(content, 4_000)
        if not content:
            raise ValueError("Сообщение не может быть пустым")
        if role not in {"user", "assistant"}:
            raise ValueError("Неизвестная роль")
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages(owner_id, session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (owner_id, session_id, role, content, _now()),
            )
            item = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return dict(item)

    def messages(
        self, owner_id: str, session_id: str, limit: int = 8
    ) -> list[dict[str, Any]]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        session_id = _clean(session_id, 80) or DEFAULT_SESSION_ID
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE owner_id = ? AND session_id = ? ORDER BY id DESC LIMIT ?",
                (owner_id, session_id, max(1, min(limit, 50))),
            ).fetchall()
        return [dict(item) for item in reversed(rows)]

    def reset_messages(self, owner_id: str, session_id: str) -> int:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        session_id = _clean(session_id, 80) or DEFAULT_SESSION_ID
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM messages WHERE owner_id = ? AND session_id = ?",
                (owner_id, session_id),
            )
        return cursor.rowcount

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT owner_id, name, role, city, updated_at FROM profiles "
                "ORDER BY name COLLATE NOCASE, owner_id"
            ).fetchall()
        result = []
        for row in rows:
            state = self.get(row["owner_id"])
            result.append(
                {
                    "owner_id": row["owner_id"],
                    "name": row["name"] or row["owner_id"],
                    "role": row["role"],
                    "city": row["city"],
                    "filled": state["filled"],
                    "preferences": len(state["preferences"]),
                    "preference_map": state["preference_map"],
                    "updated_at": row["updated_at"],
                }
            )
        return result

    def ensure_test_profiles(self) -> None:
        """Создать тестовые профили один раз и дополнить новые поля у существующих."""
        with self._connect() as conn:
            marker = conn.execute(
                "SELECT value FROM meta WHERE key = 'test_profiles_seeded'"
            ).fetchone()
        already_seeded = bool(marker and marker["value"] == "1")
        for item in TEST_PROFILES:
            owner = item["owner_id"]
            state = self.get(owner)
            exists = any(state["profile"].values()) or bool(state["preferences"])
            if not exists:
                if already_seeded:
                    continue
                self.save_profile(owner, item["profile"], source="тестовые данные")
                for key, value in item["preferences"].items():
                    self.set_preference(owner, key, value, source="тестовые данные", confidence=0.95)
                continue
            # Миграция: старым тестовым профилям добавить новые предпочтения.
            for key, value in item["preferences"].items():
                if key not in state["preference_map"]:
                    self.set_preference(owner, key, value, source="тестовые данные", confidence=0.95)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('test_profiles_seeded', '1') "
                "ON CONFLICT(key) DO UPDATE SET value='1'"
            )

    def delete_profile(self, owner_id: str) -> dict[str, Any]:
        owner_id = _clean(owner_id, 80) or DEFAULT_OWNER
        with self._connect() as conn:
            conn.execute("DELETE FROM preferences WHERE owner_id = ?", (owner_id,))
            conn.execute("DELETE FROM history WHERE owner_id = ?", (owner_id,))
            conn.execute("DELETE FROM messages WHERE owner_id = ?", (owner_id,))
            conn.execute("DELETE FROM profiles WHERE owner_id = ?", (owner_id,))
        return {"deleted": owner_id, "profiles": self.list_profiles()}

    def extract_updates(self, owner_id: str, text: str) -> list[dict[str, Any]]:
        """Извлечь устойчивые факты из реплики и сразу сохранить их."""
        text = _clean(text, 4_000)
        if not text:
            return []
        updates: list[dict[str, Any]] = []

        def profile(field: str, value: str) -> None:
            value = _clean(value, 200)
            if not value:
                return
            before = self.get(owner_id)["profile"][field]
            if value == before:
                return
            self.save_profile(owner_id, {field: value}, source="диалог")
            updates.append(
                {"kind": "profile", "key": field, "value": value, "source": "диалог"}
            )

        def preference(key: str, value: str) -> None:
            value = _clean(value, 500)
            if not value:
                return
            current = self.get(owner_id)["preference_map"].get(key, "")
            if value == current:
                return
            self.set_preference(owner_id, key, value, source="диалог", confidence=0.85)
            updates.append(
                {"kind": "preference", "key": key, "value": value, "source": "диалог"}
            )

        name = re.search(
            r"(?i)\b(?:меня зовут|мо[её] имя|зови меня)\s+([А-ЯЁA-Z][А-Яа-яЁёA-Za-z-]{1,40})",
            text,
        )
        if name:
            profile("name", name.group(1))

        role = re.search(
            r"(?i)\bя работаю\s+(?:как\s+|в роли\s+)?([^.,;\n]{2,80})", text
        )
        if role:
            profile("role", role.group(1))

        city = re.search(
            r"(?i)\b(?:(?:я\s+)?живу\s+в|мой город)\s+([А-ЯЁA-Z][А-Яа-яЁёA-Za-z -]{1,60})",
            text,
        )
        if city:
            profile("city", city.group(1).strip())

        if re.search(r"(?i)\bна\s+ты\b", text):
            preference("style", "обращение на «ты»")
        elif re.search(r"(?i)\bна\s+вы\b", text):
            preference("style", "обращение на «вы»")
        elif re.search(r"(?i)\bформальн", text):
            preference("style", "формальный")
        elif re.search(r"(?i)\bнеформальн", text):
            preference("style", "неформальный")

        if re.search(r"(?i)\b(?:отвечай\s+)?кратко\b", text):
            preference("format", "кратко")
        elif re.search(r"(?i)\bподробно\b", text):
            preference("format", "подробно")
        elif re.search(r"(?i)\bсписком\b", text):
            preference("format", "списком")
        elif re.search(r"(?i)\bтаблицей\b", text):
            preference("format", "таблицей")

        if re.search(r"(?i)\bбез\s+(?:примеров\s+)?кода\b", text):
            preference("code_examples", "без примеров кода")
        elif re.search(r"(?i)\b(?:с\s+)?(?:(?:примерами|примеры|пример)\s+кода)\b", text):
            preference("code_examples", "с примерами кода")

        if re.search(r"(?i)\bбез\s+(?:emoji|эмодзи)\b", text):
            preference("emoji", "без emoji")
        elif re.search(r"(?i)\b(?:с\s+)?(?:emoji|эмодзи)\b", text):
            preference("emoji", "с emoji")

        constraints: list[str] = []
        if re.search(r"(?i)\bбез\s+воды\b", text):
            constraints.append("без воды")
        avoid = re.search(
            r"(?i)\b(?:не используй|избегай)\s+([^.;\n]{2,120})", text
        )
        if avoid:
            constraints.append(avoid.group(1).strip())
        if constraints:
            preference("constraints", "; ".join(dict.fromkeys(constraints)))

        return updates
