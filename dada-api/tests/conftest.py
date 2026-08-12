"""Shared test configuration."""

import os

os.environ.setdefault("DADA_ENVIRONMENT", "test")
os.environ.setdefault(
    "DADA_JWT_SECRET_KEY", "test-secret-that-is-not-used-in-production"
)
os.environ.setdefault("DADA_CURSOR_SECRET_KEY", "test-cursor-secret")
os.environ.setdefault("DADA_CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("DADA_REFRESH_COOKIE_SECURE", "false")
