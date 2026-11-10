from pathlib import Path

from app.storage import ContextStore


def test_store_persists_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "context.db"
    store = ContextStore(path)
    store.create_session("ctx-1", "Первый диалог")
    store.append("ctx-1", "user", "Привет")
    store.append("ctx-1", "assistant", "Здравствуйте")

    reopened = ContextStore(path)
    history = reopened.history("ctx-1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    session = reopened.get_session("ctx-1")
    assert session is not None
    assert session["message_count"] == 2


def test_store_history_limit_returns_latest_in_order(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "context.db")
    store.create_session("ctx-2")
    for index in range(5):
        store.append("ctx-2", "user", f"m{index}")

    history = store.history("ctx-2", limit=2)
    assert [item["content"] for item in history] == ["m3", "m4"]


def test_store_clear_and_delete(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "context.db")
    store.create_session("ctx-3")
    store.append("ctx-3", "user", "Привет")
    session = store.get_session("ctx-3")
    assert session is not None
    assert session["message_count"] == 1

    store.clear("ctx-3")
    assert store.history("ctx-3") == []
    session = store.get_session("ctx-3")
    assert session is not None
    assert session["message_count"] == 0

    assert store.delete("ctx-3") is True
    assert store.get_session("ctx-3") is None


def test_store_delete_all(tmp_path: Path) -> None:
    store = ContextStore(tmp_path / "context.db")
    store.create_session("ctx-a")
    store.create_session("ctx-b")
    store.append("ctx-a", "user", "one")
    store.append("ctx-b", "user", "two")
    sessions, messages = store.delete_all()
    assert sessions == 2
    assert messages == 2
    assert store.list_sessions() == []
    assert store.count_sessions() == 0
