"""Адрес API урока 13 для отдельного фронта."""

from __future__ import annotations

import os

LESSON_13_API = os.getenv("LESSON_13_API_BASE_URL", "http://localhost:8013").rstrip("/")
