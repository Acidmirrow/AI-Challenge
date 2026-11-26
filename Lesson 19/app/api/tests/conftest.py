"""Общие настройки тестов урока 19: отдельная папка для saveToFile."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="lesson19-tests-"))
_OUTPUT = _TMP / "output"
os.environ["PIPELINE_OUTPUT_DIR"] = str(_OUTPUT)


@pytest.fixture(autouse=True)
def clean_output():
    shutil.rmtree(_OUTPUT, ignore_errors=True)
    _OUTPUT.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(_OUTPUT, ignore_errors=True)


def pytest_sessionfinish(*_args) -> None:
    shutil.rmtree(_TMP, ignore_errors=True)
