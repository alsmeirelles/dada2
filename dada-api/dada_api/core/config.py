"""Application configuration loaded from environment variables."""

from functools import lru_cache
import os


class Settings:
    """Runtime settings for the DADA API."""

    app_name: str = "DADA API"
    api_v1_prefix: str = "/api/v1"
    environment: str
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    seed_admin_username: str | None
    seed_admin_password: str | None

    def __init__(self) -> None:
        """Load settings from process environment."""
        self.environment = os.getenv("DADA_ENVIRONMENT", "development")
        self.database_url = os.getenv(
            "DADA_DATABASE_URL",
            "postgresql+asyncpg://dada:dada@localhost:5432/dada",
        )
        self.jwt_secret_key = os.getenv(
            "DADA_JWT_SECRET_KEY",
            "change-this-development-secret",
        )
        self.jwt_algorithm = os.getenv("DADA_JWT_ALGORITHM", "HS256")
        self.access_token_expire_minutes = int(
            os.getenv("DADA_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
        )
        self.seed_admin_username = os.getenv("DADA_SEED_ADMIN_USERNAME")
        self.seed_admin_password = os.getenv("DADA_SEED_ADMIN_PASSWORD")

        if (
            self.environment.lower() == "production"
            and self.jwt_secret_key == "change-this-development-secret"
        ):
            raise RuntimeError("DADA_JWT_SECRET_KEY must be set in production.")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""
    return Settings()
