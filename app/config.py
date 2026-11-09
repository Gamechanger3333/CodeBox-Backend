"""Application settings, loaded from environment variables / .env.

Env var names are IDENTICAL to the original Node.js project, so an existing
.env file keeps working (DATABASE_URL, JWT_SECRET, GROQ_API_KEY, ...).
"""
from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_url: str = Field(alias="DATABASE_URL")
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_expires_in: str = Field("7d", alias="JWT_EXPIRES_IN")
    jwt_cookie_expires_in: int = Field(7, alias="JWT_COOKIE_EXPIRES_IN")  # days

    groq_api_key: str | None = Field(None, alias="GROQ_API_KEY")
    resend_api_key: str | None = Field(None, alias="RESEND_API_KEY")
    email_from: str | None = Field(None, alias="EMAIL_FROM")

    port: int = Field(5000, alias="PORT")
    node_env: str = Field("development", alias="NODE_ENV")
    frontend_url: str = Field("http://localhost:3000", alias="FRONTEND_URL")

    demo_user_email: str = Field("demo@codebox.com", alias="DEMO_USER_EMAIL")
    demo_user_password_seed: str = Field("Demo@1234", alias="DEMO_USER_PASSWORD_SEED")

    # RAG embeddings: "ollama" (local, default) or "gemini" (hosted free tier)
    embedding_provider: str = Field("ollama", alias="EMBEDDING_PROVIDER")
    ollama_url: str = Field("http://localhost:11434", alias="OLLAMA_URL")
    gemini_api_key: str | None = Field(None, alias="GEMINI_API_KEY")
    embedding_timeout_seconds: float = Field(300.0, alias="EMBEDDING_TIMEOUT_SECONDS")

    # Turn off in tests (all requests share one IP there).
    rate_limit_enabled: bool = Field(True, alias="RATE_LIMIT_ENABLED")

    @field_validator("groq_api_key", "resend_api_key", "email_from", "gemini_api_key", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        # `GROQ_API_KEY=` (empty) must behave like "not configured".
        return v or None

    @property
    def is_production(self) -> bool:
        return self.node_env == "production"

    @property
    def jwt_expires_seconds(self) -> int:
        return parse_duration_seconds(self.jwt_expires_in)


_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration_seconds(value: str) -> int:
    """'7d' -> 604800, '15m' -> 900, '3600' -> 3600 (plain number = seconds)."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhdw]?)\s*", value or "")
    if not m:
        raise ValueError(f"Invalid duration: {value!r} (use e.g. 7d, 12h, 15m)")
    return int(m.group(1)) * _UNITS.get(m.group(2) or "s", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
