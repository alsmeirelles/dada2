"""Short-lived signed URLs that let a browser load one image without a bearer token."""

import hashlib
import hmac
from datetime import datetime, timedelta

from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError

MEDIA_URL_TTL = timedelta(hours=1)


def _signature(media_id: str, expires: int) -> str:
    """Return the HMAC binding one media item to one expiry time."""
    message = f"media:{media_id}:{expires}".encode()
    secret = get_settings().jwt_secret_key.get_secret_value().encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def signed_media_url(media_id: str, now: datetime) -> str:
    """Return an API-relative URL that serves one image until it expires.

    The URL authorises exactly one media item for a bounded time, so it can be
    placed in an ``<img>`` or SVG ``<image>`` element where no header can be
    sent, without ever putting an access token in a URL.

    Args:
        media_id: Media item the URL grants.
        now: Current server time.

    Returns:
        The path and query string, relative to the API origin.
    """
    expires = int((now + MEDIA_URL_TTL).timestamp())
    signature = _signature(media_id, expires)
    return f"/api/v1/media/{media_id}/content?expires={expires}&signature={signature}"


def verify_media_url(
    media_id: str, expires: int, signature: str, now: datetime
) -> None:
    """Refuse a media URL that was not issued by this API or has expired.

    Raises:
        ApiError: 403 when the signature does not match or the time has passed.
    """
    if expires < now.timestamp() or not hmac.compare_digest(
        signature, _signature(media_id, expires)
    ):
        raise ApiError(
            403, "invalid_media_url", "The image link is invalid or has expired."
        )
