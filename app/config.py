from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_DEFAULT_JWT_SECRET = "dev-only-not-for-production"
INSECURE_DEFAULT_WEBHOOK_TOKEN = "dev-only-webhook-token"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://corvin:corvin@localhost:5432/corvin"

    jwt_secret_key: str = INSECURE_DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    webhook_token: str = INSECURE_DEFAULT_WEBHOOK_TOKEN
    webhook_rate_limit_per_minute: int = 30

    # Data-residency guard: the build spec requires that incident data is
    # never sent to a non-EU-hosted LLM provider unless this is explicitly
    # flipped on. Default is the safe, restrictive choice.
    allow_non_eu_llm: bool = False
    llm_provider_region: str = "non-eu"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"

    default_timezone: str = "Europe/Brussels"
    hosting_region: str = "EU"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def insecure_defaults_in_use(self) -> list[str]:
        """Names of secrets still set to their shipped placeholder values."""
        found = []
        if self.jwt_secret_key == INSECURE_DEFAULT_JWT_SECRET:
            found.append("JWT_SECRET_KEY")
        if self.webhook_token == INSECURE_DEFAULT_WEBHOOK_TOKEN:
            found.append("WEBHOOK_TOKEN")
        return found


@lru_cache
def get_settings() -> Settings:
    return Settings()
