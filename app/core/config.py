from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "wawayu-ai-service"
    app_env: str = "development"
    log_level: str = "INFO"

    ai_provider: str = "openai_compatible"
    ai_model: str = "gpt-4o-mini"
    ai_base_url: str | None = None
    ai_api_key: SecretStr | None = None
    ai_timeout_seconds: float = 30.0
    ai_structured_output_method: Literal[
        "function_calling", "json_schema"
    ] = "function_calling"
    ai_service_api_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
