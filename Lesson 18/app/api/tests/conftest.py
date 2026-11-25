"""Настройки тестов урока 18: отдельная временная SQLite и выключенный автозапуск."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="lesson18-tests-"))
os.environ["SCHEDULER_DB_PATH"] = str(_TMP / "lesson18.db")
os.environ["SCHEDULER_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def clean_storage():
    """Каждый тест начинает с пустой базы."""
    path = Path(os.environ["SCHEDULER_DB_PATH"])
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    yield
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()


def pytest_sessionfinish(*_args) -> None:
    shutil.rmtree(_TMP, ignore_errors=True)
