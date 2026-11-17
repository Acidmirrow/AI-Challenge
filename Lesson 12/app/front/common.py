"""Адрес API урока 12 для отдельного фронта."""

from __future__ import annotations

import os

LESSON_12_API = os.getenv("LESSON_12_API_BASE_URL", "http://localhost:8012").rstrip("/")
