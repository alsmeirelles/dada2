"""Application configuration loaded from dotenv and environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


def resolve_env_file() -> Path | None:
    """Return the dotenv file path to use when one is available."""
    explicit_env_file = os.getenv("DADA_ENV_FILE")
    if explicit_env_file:
        return Path(explicit_env_file)

    candidate_paths = (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    )
    for candidate_path in candidate_paths:
        if candidate_path.exists():
            return candidate_path

    return None


class Settings(BaseSettings):
    """Runtime settings for the DADA API."""

    app_name: str = "DADA API"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_host_port: int = 5432
    postgres_user: str = "dada"
    postgres_password: SecretStr = Field(default=SecretStr("dada"), repr=False)
    postgres_db: str = "dada"
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    cursor_secret_key: SecretStr | None = Field(default=None, repr=False)
    supported_image_media_types: str = "image/jpeg,image/png,image/webp"
    max_file_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_project_files: int = Field(default=100_000, gt=0)
    upload_chunk_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    realtime_transport: str = "websocket"
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("change-this-development-secret"),
        repr=False,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = Field(default=14, gt=0)
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "lax"
    seed_admin_username: str | None = None
    seed_admin_display_name: str | None = None
    seed_admin_password: SecretStr | None = Field(default=None, repr=False)
    seed_service_username: str | None = None
    seed_service_password: SecretStr | None = Field(default=None, repr=False)

    model_config = SettingsConfigDict(
        env_prefix="DADA_",
        env_file=resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def sqlalchemy_database_url(self) -> str | URL:
        """Return the SQLAlchemy database URL.

        Explicit runtime ``DADA_DATABASE_URL`` values are returned as-is for
        managed deployments. Local development settings use ``URL.create`` so
        string representations mask the password by default.
        """
        if self.database_url:
            return self.database_url

        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_host_port,
            database=self.postgres_db,
        )

    @property
    def allowed_cors_origins(self) -> list[str]:
        """Return normalized configured browser origins."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def image_media_types(self) -> list[str]:
        """Return normalized advertised image media types."""
        return [
            media_type.strip().lower()
            for media_type in self.supported_image_media_types.split(",")
            if media_type.strip()
        ]

    @property
    def effective_cursor_secret(self) -> str:
        """Return the dedicated cursor secret or fall back to the JWT secret."""
        if self.cursor_secret_key is not None:
            return self.cursor_secret_key.get_secret_value()
        return self.jwt_secret_key.get_secret_value()

    @field_validator("refresh_cookie_samesite")
    @classmethod
    def normalize_cookie_samesite(cls, value: str) -> str:
        """Normalize and validate the refresh cookie SameSite policy."""
        normalized = value.strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("refresh_cookie_samesite must be lax, strict, or none")
        return normalized

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        """Normalize and validate the deployment environment name."""
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "staging", "production"}:
            raise ValueError(
                "environment must be development, test, staging, or production"
            )
        return normalized

    def model_post_init(self, _: object) -> None:
        """Validate settings that depend on multiple values."""
        if self.seed_service_username is None:
            self.seed_service_username = self.postgres_user

        if (
            self.environment == "production"
            and self.jwt_secret_key.get_secret_value()
            == "change-this-development-secret"
        ):
            raise RuntimeError("DADA_JWT_SECRET_KEY must be set in production.")
        if self.environment == "production" and any(
            "localhost" in origin for origin in self.allowed_cors_origins
        ):
            raise RuntimeError(
                "DADA_CORS_ORIGINS must not contain localhost in production."
            )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
