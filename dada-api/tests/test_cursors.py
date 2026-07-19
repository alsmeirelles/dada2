"""Opaque cursor signing tests."""

import pytest

from dada_api.core.cursors import decode_cursor, encode_cursor
from dada_api.core.errors import ApiError


def test_cursor_round_trip() -> None:
    cursor = encode_cursor({"created_at": "2026-07-19T00:00:00Z", "id": "abc"})
    assert decode_cursor(cursor) == {
        "created_at": "2026-07-19T00:00:00Z",
        "id": "abc",
    }


def test_tampered_cursor_is_rejected() -> None:
    cursor = encode_cursor({"id": "abc"})
    with pytest.raises(ApiError) as error:
        decode_cursor(cursor[:-1] + ("A" if cursor[-1] != "A" else "B"))
    assert error.value.code == "invalid_cursor"
