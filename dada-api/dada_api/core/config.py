"""Application configuration loaded from dotenv and environment variables."""

from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field, SecretStr
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
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_host_port: int = 5432
    postgres_user: str = "dada"
    postgres_password: SecretStr = Field(default=SecretStr("dada"), repr=False)
    postgres_db: str = "dada"
    jwt_secret_key: SecretStr = Field(
        default=SecretStr("change-this-development-secret"),
        repr=False,
    )
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    seed_admin_username: str | None = None
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

    def model_post_init(self, _: object) -> None:
        """Validate settings that depend on multiple values."""
        if self.seed_service_username is None:
            self.seed_service_username = self.postgres_user

        if (
            self.environment.lower() == "production"
            and self.jwt_secret_key.get_secret_value()
            == "change-this-development-secret"
        ):
            raise RuntimeError("DADA_JWT_SECRET_KEY must be set in production.")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
