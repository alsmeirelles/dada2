"""Storage adapter and path-safety unit tests, independent of HTTP."""

import pytest

from dada_api.core.config import get_settings
from dada_api.services import storage
from dada_api.services.ingestion import normalize_relative_path


@pytest.mark.parametrize(
    "raw",
    [
        "/etc/passwd",
        "../secret.png",
        "a/../../b.png",
        "C:/windows/system32.png",
        "",
        "   ",
        "a//b.png",
        "bad\x00name.png",
        "line\nbreak.png",
    ],
)
def test_unsafe_relative_paths_are_refused(raw: str) -> None:
    assert normalize_relative_path(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("camera-a/day-01/frame.png", "camera-a/day-01/frame.png"),
        ("camera-a\\day-01\\frame.png", "camera-a/day-01/frame.png"),
        ("  spaced/frame.png  ", "spaced/frame.png"),
    ],
)
def test_safe_relative_paths_are_normalised(raw: str, expected: str) -> None:
    assert normalize_relative_path(raw) == expected


def test_unicode_spellings_of_one_name_collapse_to_one_path() -> None:
    decomposed = "cafe\u0301/one.png"
    composed = "caf\u00e9/one.png"
    assert normalize_relative_path(decomposed) == normalize_relative_path(composed)


def test_media_storage_key_fans_out_by_digest() -> None:
    digest = "ab" + "c" * 62
    key = storage.media_storage_key("project-1", digest)
    assert key == f"project-1/ab/cc/{digest}"


def test_storage_paths_cannot_escape_their_root() -> None:
    root = get_settings().upload_parts_root
    with pytest.raises(ValueError, match="escapes its configured root"):
        storage._resolve_within(root, "..", "..", "escaped")


def test_configured_roots_are_absolute_and_distinct() -> None:
    settings = get_settings()
    assert settings.media_root.is_absolute()
    assert settings.upload_parts_root.is_absolute()
    assert settings.media_root != settings.upload_parts_root
