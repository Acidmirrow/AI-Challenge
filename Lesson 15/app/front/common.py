"""Адрес API урока 15 для отдельного фронта."""

from __future__ import annotations

import os

LESSON_15_API = os.getenv("LESSON_15_API_BASE_URL", "http://localhost:8015").rstrip("/")
