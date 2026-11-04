"""Java-style ``*.properties`` configuration for the API.

Two files are read at startup (paths overridable with env vars):

* ``/srv/config/app.properties``     — обычная конфигурация, лежит в git
* ``/srv/config/secrets.properties`` — токены, в git НЕ попадает, монтируется при деплое

Keys may be written as ``deepseek.api.key``, ``DEEPSEEK_API_KEY`` or
``deepseek-api-key`` — all normalise to the ``deepseek_api_key`` setting.
Priority: параметры процесса > переменные окружения > .env > docker secrets >
properties-файлы.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import PydanticBaseSettingsSource

DEFAULT_APP_FILE = "/srv/config/app.properties"
DEFAULT_SECRETS_FILE = "/srv/config/secrets.properties"

_KEY_RE = re.compile(r"^\s*(?P<key>[^=:\s]+)\s*[=:]?\s*(?P<value>.*)$")


def config_paths() -> list[Path]:
    """Files to read, in increasing priority order (later wins)."""
    app_file = Path(os.getenv("CONFIG_FILE", DEFAULT_APP_FILE))
    secrets_file = Path(os.getenv("SECRETS_FILE", DEFAULT_SECRETS_FILE))
    return [app_file, secrets_file]


def normalize_key(key: str) -> str:
    return re.sub(r"[.\-\s]+", "_", key.strip()).lower()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_properties(path: Path) -> dict[str, str]:
    """Minimal ``key=value`` parser: ``#``/``!`` comments, quoting, ``:`` separator."""
    if not path.is_file():
        return {}
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line[0] in "#!":
            continue
        match = _KEY_RE.match(line)
        if not match:
            continue
        key, value = match.group("key"), _unquote(match.group("value").strip())
        data[normalize_key(key)] = value
    return data


def merge_properties_files(paths: list[Path] | None = None) -> dict[str, str]:
    """Merge files in priority order (later overrides earlier)."""
    merged: dict[str, str] = {}
    for path in config_paths() if paths is None else paths:
        merged.update(parse_properties(path))
    return merged


def loaded_files() -> list[str]:
    """Existing config files — reported in /api/health for deploy debugging."""
    return [str(p) for p in config_paths() if p.is_file()]


class PropertiesSource(PydanticBaseSettingsSource):
    """pydantic-settings source backed by the properties files."""

    def __init__(self, settings_cls: type, paths: list[Path] | None = None):
        super().__init__(settings_cls)
        self._paths = paths

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:  # noqa: D102
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        known = set(self.settings_cls.model_fields)
        return {k: v for k, v in merge_properties_files(self._paths).items() if k in known}
