"""Opaque, signed cursor encoding for deterministic pagination."""

import base64
import hashlib
import hmac
import json
from typing import Any

from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError


def encode_cursor(values: dict[str, Any]) -> str:
    """Encode and authenticate JSON-safe pagination values."""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    signature = hmac.new(
        get_settings().effective_cursor_secret.encode(), payload, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(payload + signature).rstrip(b"=").decode()


def decode_cursor(cursor: str) -> dict[str, Any]:
    """Decode a cursor or raise a stable invalid-request error."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        combined = base64.urlsafe_b64decode(padded.encode())
        payload, supplied_signature = combined[:-32], combined[-32:]
        expected_signature = hmac.new(
            get_settings().effective_cursor_secret.encode(), payload, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ValueError
        return decoded
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise ApiError(
            400, "invalid_cursor", "The pagination cursor is invalid."
        ) from error
