from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from .properties import PropertiesSource


class Settings(BaseSettings):
    """Настройки урока 18: планировщик и SQLite-хранилище."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
        **_: Any,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            PropertiesSource(settings_cls),
        )

    scheduler_enabled: bool = True
    scheduler_snapshot_interval_s: float = 10.0
    scheduler_report_interval_s: float = 30.0
    scheduler_startup_delay_s: float = 1.0
    scheduler_report_window_minutes: int = 60
    scheduler_source: str = "demo-api"
    scheduler_db_path: str = "/srv/data/lesson18.db"

    cors_origins: str = "*"

    @property
    def snapshot_interval(self) -> float:
        return max(1.0, float(self.scheduler_snapshot_interval_s))

    @property
    def report_interval(self) -> float:
        return max(1.0, float(self.scheduler_report_interval_s))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
