"""Signed image links that authorise one media item for a bounded time."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from dada_api.core import media_urls
from dada_api.core.errors import ApiError

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def parts(url: str) -> tuple[str, int, str]:
    split = urlsplit(url)
    query = parse_qs(split.query)
    media_id = split.path.split("/")[-2]
    return media_id, int(query["expires"][0]), query["signature"][0]


def test_a_signed_link_names_its_media_and_verifies_until_it_expires() -> None:
    url = media_urls.signed_media_url("media-1", NOW)
    media_id, expires, signature = parts(url)

    assert url.startswith("/api/v1/media/media-1/content?")
    assert media_id == "media-1"
    assert expires == int((NOW + media_urls.MEDIA_URL_TTL).timestamp())
    media_urls.verify_media_url(media_id, expires, signature, NOW)


def test_an_expired_link_is_refused() -> None:
    _, expires, signature = parts(media_urls.signed_media_url("media-1", NOW))
    later = NOW + media_urls.MEDIA_URL_TTL + timedelta(seconds=1)

    with pytest.raises(ApiError) as refused:
        media_urls.verify_media_url("media-1", expires, signature, later)

    assert refused.value.status_code == 403
    assert refused.value.code == "invalid_media_url"


def test_a_link_cannot_be_moved_to_another_media_or_expiry() -> None:
    _, expires, signature = parts(media_urls.signed_media_url("media-1", NOW))

    for media_id, moved_expiry in (("media-2", expires), ("media-1", expires + 60)):
        with pytest.raises(ApiError):
            media_urls.verify_media_url(media_id, moved_expiry, signature, NOW)
