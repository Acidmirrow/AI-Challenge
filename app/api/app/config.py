from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # mock | openai   (openai == any OpenAI-compatible endpoint: OpenAI, OpenRouter,
    # DeepSeek, vLLM, LM Studio, Ollama's /v1 shim, ...)
    provider: str = "mock"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # Name of the parameter used to control reasoning depth.
    # OpenAI: reasoning_effort. Set to "" for gateways that reject unknown params.
    reasoning_param: str = "reasoning_effort"

    # Name of the token-limit parameter. OpenAI reasoning models want
    # max_completion_tokens, most gateways only accept max_tokens.
    max_tokens_param: str = ""
    include_usage: bool = True

    # Optional JSON file overriding the built-in model catalog.
    models_json: str = ""
    # Pull the model list from <base_url>/models in addition to the catalog.
    dynamic_models: bool = False

    http_timeout_s: float = 180.0
    cors_origins: str = "*"

    @property
    def provider_label(self) -> str:
        return {
            "mock": "mock (offline demo)",
            "openai": f"openai-compatible @ {self.openai_base_url}",
        }.get(self.provider, self.provider)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
