"""Адрес API урока 11 для отдельного фронта."""

from __future__ import annotations

import os

LESSON_11_API = os.getenv("LESSON_11_API_BASE_URL", "http://localhost:8011").rstrip("/")
