from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://corvin:corvin@localhost:5432/corvin"

    jwt_secret_key: str = "dev-only-not-for-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    webhook_token: str = "dev-only-webhook-token"
    webhook_rate_limit_per_minute: int = 30

    # Data-residency guard: the build spec requires that incident data is
    # never sent to a non-EU-hosted LLM provider unless this is explicitly
    # flipped on. Default is the safe, restrictive choice.
    allow_non_eu_llm: bool = False
    llm_provider_region: str = "non-eu"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    default_timezone: str = "Europe/Brussels"
    hosting_region: str = "EU"


@lru_cache
def get_settings() -> Settings:
    return Settings()
