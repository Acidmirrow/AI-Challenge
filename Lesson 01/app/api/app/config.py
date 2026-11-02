from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # mock | openai | deepseek
    #   mock     — офлайн-демо, ключ не нужен
    #   openai   — любой OpenAI-совместимый endpoint (OpenAI, OpenRouter, vLLM, LM Studio, Ollama /v1)
    #   deepseek — нативный DeepSeek API со своим каталогом моделей
    provider: str = "mock"

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"

    # Name of the parameter used to control reasoning depth.
    # OpenAI: reasoning_effort. Set to "" for gateways that reject unknown params.
    reasoning_param: str = "reasoning_effort"

    # Name of the token-limit parameter. Empty = pick per model
    # (max_completion_tokens for reasoning models, max_tokens otherwise).
    max_tokens_param: str = ""
    include_usage: bool = True

    # Optional JSON file overriding the built-in model catalog.
    models_json: str = ""
    # Pull the model list from <base_url>/models in addition to the catalog.
    dynamic_models: bool = False

    # Web search for the model: off | auto | brave-html | brave-api | tavily | duckduckgo
    web_search_backend: str = "auto"
    tavily_api_key: str = ""
    brave_api_key: str = ""
    web_search_results: int = 5
    web_search_timeout_s: float = 12.0
    # how many top pages to read and how much text to hand to the model
    web_search_pages: int = 2
    web_search_page_chars: int = 3000

    http_timeout_s: float = 180.0
    cors_origins: str = "*"

    @property
    def api_key(self) -> str:
        return self.deepseek_api_key if self.provider == "deepseek" else self.openai_api_key

    @property
    def base_url(self) -> str:
        return self.deepseek_base_url if self.provider == "deepseek" else self.openai_base_url

    @property
    def provider_label(self) -> str:
        if self.provider == "mock":
            return "mock (offline demo)"
        return f"{self.provider} @ {self.base_url}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
