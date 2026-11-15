"""Typed configuration. Every secret comes from the environment, never from code."""
from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDERS = {"", "change-me", "changeme", "secret", "dev-secret"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # development | test | production
    database_url: str = "postgresql+psycopg://sahil:sahil@localhost:5432/sahil"

    # Signing key for access tokens. Must be >= 32 random bytes.
    jwt_secret: str = ""
    jwt_issuer: str = "sahil-api"
    jwt_audience: str = "sahil-app"
    access_token_minutes: int = 10
    refresh_token_days: int = 14
    session_max_days: int = 30

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    trust_proxy_headers: bool = False
    max_body_bytes: int = 32 * 1024

    # Brute-force protection
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Transfer policy (amounts in fils; 1 BHD = 1000 fils)
    max_transfer_fils: int = 1_000_000
    daily_outgoing_limit_fils: int = 3_000_000
    max_topup_fils: int = 500_000
    daily_topup_limit_fils: int = 1_000_000

    # AI assistant. The key lives only on the server.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    assistant_timeout_seconds: int = 20

    seed_demo_data: bool = False
    rate_limit_enabled: bool = True

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test or production")
        return v

    @model_validator(mode="after")
    def _refuse_weak_secrets(self) -> "Settings":
        if self.jwt_secret.lower() in _PLACEHOLDERS or len(self.jwt_secret) < 32:
            raise ValueError(
                "JWT_SECRET is missing or too short. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        if self.environment == "production":
            if self.seed_demo_data:
                raise ValueError("SEED_DEMO_DATA must be off in production")
            if any(o.startswith("http://") for o in self.cors_list):
                raise ValueError("Production CORS origins must use https")
        return self

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def docs_enabled(self) -> bool:
        return self.environment != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
