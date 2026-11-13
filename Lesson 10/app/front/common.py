"""Общие настройки фронта урока 10."""

from __future__ import annotations

import os

LESSON_10_API = os.getenv("LESSON_10_API_BASE_URL", "http://localhost:8010").rstrip("/")
