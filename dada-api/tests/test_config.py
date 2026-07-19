"""Settings validation tests."""

import pytest

from dada_api.core.config import Settings


def test_production_rejects_default_secret() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(
            environment="production",
            cors_origins="https://app.example.test",
            jwt_secret_key="change-this-development-secret",
        )


def test_production_rejects_localhost_cors() -> None:
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        Settings(
            environment="production",
            jwt_secret_key="a-production-secret",
            cors_origins="http://localhost:5173",
        )
