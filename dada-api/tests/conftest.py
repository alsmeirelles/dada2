"""Shared test configuration."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("DADA_ENVIRONMENT", "test")
os.environ.setdefault(
    "DADA_JWT_SECRET_KEY", "test-secret-that-is-not-used-in-production"
)
os.environ.setdefault("DADA_CURSOR_SECRET_KEY", "test-cursor-secret")
os.environ.setdefault("DADA_CORS_ORIGINS", "http://localhost:5173")
os.environ.setdefault("DADA_REFRESH_COOKIE_SECURE", "false")

_STORAGE_ROOT = Path(tempfile.mkdtemp(prefix="dada-test-storage-"))
os.environ.setdefault("DADA_MEDIA_ROOT", str(_STORAGE_ROOT / "media"))
os.environ.setdefault("DADA_UPLOAD_PARTS_ROOT", str(_STORAGE_ROOT / "upload-parts"))
