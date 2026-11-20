"""Адрес API урока 14 для отдельного фронта."""

from __future__ import annotations

import os

LESSON_14_API = os.getenv("LESSON_14_API_BASE_URL", "http://localhost:8014").rstrip("/")
