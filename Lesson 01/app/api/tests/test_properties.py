"""Properties-file configuration: parsing, layering and secret handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.properties import loaded_files, merge_properties_files, parse_properties


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_parser_handles_comments_quotes_and_separators(tmp_path: Path) -> None:
    path = write(
        tmp_path / "app.properties",
        """
# комментарий
! тоже комментарий
provider = deepseek
deepseek.api.key = "sk-quoted"
web-search-backend: bing
empty.value =
unknown.key = 1
""",
    )
    data = parse_properties(path)
    assert data["provider"] == "deepseek"
    assert data["deepseek_api_key"] == "sk-quoted"
    assert data["web_search_backend"] == "bing"
    assert data["empty_value"] == ""
    assert "unknown_key" in data  # фильтрация по полям — забота source'а


def test_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert parse_properties(tmp_path / "nope.properties") == {}


def test_later_files_win(tmp_path: Path) -> None:
    app = write(tmp_path / "app.properties", "provider=mock\ndeepseek.api.key=from-app\n")
    secrets = write(tmp_path / "secrets.properties", "deepseek.api.key=from-secrets\n")
    merged = merge_properties_files([app, secrets])
    assert merged["provider"] == "mock"
    assert merged["deepseek_api_key"] == "from-secrets"


def test_settings_read_properties(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROVIDER", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = write(tmp_path / "app.properties", "provider = deepseek\nweb.search.backend = bing\n")
    secrets = write(tmp_path / "secrets.properties", "deepseek.api.key = sk-from-file\n")
    monkeypatch.setenv("CONFIG_FILE", str(app))
    monkeypatch.setenv("SECRETS_FILE", str(secrets))

    settings = Settings()
    assert settings.provider == "deepseek"
    assert settings.web_search_backend == "bing"
    assert settings.deepseek_api_key == "sk-from-file"
    assert settings.api_key == "sk-from-file"


def test_environment_overrides_properties(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = write(tmp_path / "app.properties", "provider = mock\ndeepseek.api.key = from-file\n")
    monkeypatch.setenv("CONFIG_FILE", str(app))
    monkeypatch.setenv("SECRETS_FILE", str(tmp_path / "none.properties"))
    monkeypatch.setenv("PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")

    settings = Settings()
    assert settings.provider == "deepseek"
    assert settings.deepseek_api_key == "sk-from-env"


def test_unknown_keys_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = write(tmp_path / "app.properties", "provider = mock\ntotally.unknown = boom\n")
    monkeypatch.setenv("CONFIG_FILE", str(app))
    monkeypatch.setenv("SECRETS_FILE", str(tmp_path / "none.properties"))
    monkeypatch.delenv("PROVIDER", raising=False)
    assert Settings().provider == "mock"


def test_loaded_files_reports_existing_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = write(tmp_path / "app.properties", "provider=mock\n")
    monkeypatch.setenv("CONFIG_FILE", str(app))
    monkeypatch.setenv("SECRETS_FILE", str(tmp_path / "missing.properties"))
    files = loaded_files()
    assert files == [str(app)]


def test_real_config_files_are_secret_free() -> None:
    """app.properties is committed — it must never contain a token."""
    committed = Path("/srv/config/app.properties")
    if not committed.is_file():
        pytest.skip("mounted config dir not available")
    text = committed.read_text(encoding="utf-8")
    assert "sk-" not in text
    assert parse_properties(committed)["provider"] in {"mock", "openai", "deepseek"}
