"""HEIC/HEIF ingestion with a lossless WebP rendition (P7-06) over real HTTP."""

import hashlib
import io
import os
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, select

from dada_api.core.config import get_settings
from dada_api.core.media_urls import signed_media_url
from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation_policy import (
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.upload import UploadChunk, UploadItem, UploadSession
from dada_api.models.user import User
from dada_api.services import renditions, storage

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

FIXTURES = Path(__file__).parent / "fixtures" / "heif"
PASSWORD = "phase7-heif-password"
DRAFT = {
    "name": "Belt photos",
    "description": None,
    "task_type": "segmentation",
    "initial_training_size": 1,
    "test_set_size": 1,
    "validation_set_size": 1,
    "iteration_batch_size": 1,
    "max_acquisition_iterations": 5,
}
VALID = [
    ("landscape-8bit.heic", "image/heic", (48, 32), "RGB"),
    ("landscape-8bit.heif", "image/heif", (48, 32), "RGB"),
    ("portrait-oriented.heic", "image/heic", (24, 40), "RGB"),
    ("alpha.heic", "image/heic", (30, 20), "RGBA"),
    ("ten-bit.heic", "image/heic", (26, 18), "RGB"),
]


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


async def _reset() -> None:
    """Remove every record and stored file these tests create."""
    async with async_session_factory() as session:
        for model in (
            IdempotencyRecord,
            UploadChunk,
            UploadItem,
            UploadSession,
            Media,
            ContentObject,
            AuditEntry,
            AnnotationPolicyAnnotator,
            AnnotationPolicyDefault,
            ProjectClass,
            ProjectMember,
            Project,
            User,
        ):
            await session.execute(delete(model))
        await session.commit()
    settings = get_settings()
    for root in (settings.media_root, settings.upload_parts_root):
        if root.exists():
            shutil.rmtree(root)


@pytest.fixture
async def database() -> AsyncIterator[None]:
    """Provide an empty database and empty storage around each test."""
    await _reset()
    yield
    await _reset()


async def _owner() -> str:
    """Persist the project owner and return an access token."""
    async with async_session_factory() as session:
        session.add(
            User(
                username="owner",
                display_name="Owner",
                password_hash=hash_password(PASSWORD),
                is_administrator=False,
                is_active=True,
            )
        )
        await session.commit()
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token", json={"username": "owner", "password": PASSWORD}
        )
    return response.json()["access_token"]


async def _upload(
    client: httpx.AsyncClient,
    token: str,
    project_id: str,
    files: list[tuple[str, str, bytes]],
) -> httpx.Response:
    """Upload files as one session and return the completion response."""
    created = await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        headers=_auth(token),
        json={
            "files": [
                {
                    "client_file_id": f"f{index}",
                    "relative_path": path,
                    "file_name": path.rsplit("/", 1)[-1],
                    "media_type": media_type,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for index, (path, media_type, data) in enumerate(files)
            ]
        },
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["id"]
    for index, (_, _, data) in enumerate(files):
        chunk = await client.put(
            f"/api/v1/uploads/{upload_id}/files/f{index}",
            headers={
                **_auth(token),
                "Content-Type": "application/octet-stream",
                "Upload-Offset": "0",
                "X-Chunk-SHA256": hashlib.sha256(data).hexdigest(),
            },
            content=data,
        )
        assert chunk.status_code == 200, chunk.text
    return await client.post(
        f"/api/v1/uploads/{upload_id}/complete", headers=_auth(token), json={}
    )


async def _project(client: httpx.AsyncClient, token: str) -> str:
    """Create a draft project and return its identifier."""
    response = await client.post("/api/v1/projects", headers=_auth(token), json=DRAFT)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_heif_sources_keep_their_digest_and_gain_an_exact_rendition(
    database: None,
) -> None:
    token = await _owner()
    files = [
        (f"photos/{name}", media_type, (FIXTURES / name).read_bytes())
        for name, media_type, _, _ in VALID
    ]
    async with _client() as client:
        project_id = await _project(client, token)
        completed = await _upload(client, token, project_id, files)
        listing = await client.get(
            f"/api/v1/projects/{project_id}/media", headers=_auth(token)
        )
        media = {item["relative_path"]: item for item in listing.json()["items"]}
        served = {}
        for path, item in media.items():
            url = signed_media_url(item["id"], datetime.now(UTC))
            served[path] = await client.get(url)

    assert completed.status_code == 200, completed.text
    for (path, media_type, data), (name, _, size, mode) in zip(
        files, VALID, strict=True
    ):
        item = media[path]
        digest = hashlib.sha256(data).hexdigest()
        assert item["sha256"] == digest
        assert item["media_type"] == media_type
        assert (item["width"], item["height"]) == size

        rendition = storage.media_path(
            storage.rendition_storage_key(project_id, digest)
        )
        source = storage.media_path(storage.media_storage_key(project_id, digest))
        assert source.read_bytes() == data
        with Image.open(rendition) as webp:
            assert webp.format == "WEBP"
            assert webp.size == size
            assert webp.mode == mode
            expected = renditions.canonical_image(FIXTURES / name)
            assert expected.size == size
            assert webp.tobytes() == expected.tobytes(), name

        response = served[path]
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"
        assert int(response.headers["content-length"]) == rendition.stat().st_size
        assert response.content == rendition.read_bytes()


def test_orientation_is_applied_once() -> None:
    image = renditions.canonical_image(FIXTURES / "portrait-oriented.heic")
    assert image.size == (24, 40)
    red, green, blue = image.getpixel((20, 3))
    assert red > 240 and green < 15 and blue < 15
    red, green, blue = image.getpixel((3, 3))
    assert red < 40 and 100 < green < 140 and blue > 180


async def test_spoofed_and_broken_heif_uploads_fail_without_media(
    database: None,
) -> None:
    token = await _owner()
    heic = (FIXTURES / "landscape-8bit.heic").read_bytes()
    png = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(png, format="PNG")
    async with _client() as client:
        project_id = await _project(client, token)
        png_as_heic = await _upload(
            client, token, project_id, [("a/png.heic", "image/heic", png.getvalue())]
        )
        heic_as_png = await _upload(
            client, token, project_id, [("a/heic.png", "image/png", heic)]
        )
        truncated = await _upload(
            client,
            token,
            project_id,
            [
                (
                    "a/truncated.heic",
                    "image/heic",
                    (FIXTURES / "truncated.heic").read_bytes(),
                )
            ],
        )

    for response in (png_as_heic, heic_as_png, truncated):
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "invalid_image"
    async with async_session_factory() as session:
        assert list(await session.scalars(select(Media))) == []
        assert list(await session.scalars(select(ContentObject))) == []


async def test_a_conversion_failure_fails_the_upload(
    database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(source: Path, target: Path) -> tuple[int, int]:
        raise renditions.ConversionError("encoder refused")

    monkeypatch.setattr(renditions, "write_rendition", refuse)
    token = await _owner()
    heic = (FIXTURES / "alpha.heic").read_bytes()
    async with _client() as client:
        project_id = await _project(client, token)
        response = await _upload(
            client, token, project_id, [("a/alpha.heic", "image/heic", heic)]
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "image_conversion_failed"
    digest = hashlib.sha256(heic).hexdigest()
    assert not storage.media_path(
        storage.rendition_storage_key(project_id, digest)
    ).exists()
    async with async_session_factory() as session:
        assert list(await session.scalars(select(Media))) == []


async def test_duplicate_heif_content_reuses_its_rendition(database: None) -> None:
    token = await _owner()
    heic = (FIXTURES / "ten-bit.heic").read_bytes()
    async with _client() as client:
        project_id = await _project(client, token)
        first = await _upload(
            client, token, project_id, [("a/one.heic", "image/heic", heic)]
        )
        rendition = storage.media_path(
            storage.rendition_storage_key(project_id, hashlib.sha256(heic).hexdigest())
        )
        written_at = rendition.stat().st_mtime_ns
        second = await _upload(
            client, token, project_id, [("b/two.heic", "image/heic", heic)]
        )

    assert first.status_code == second.status_code == 200
    assert rendition.stat().st_mtime_ns == written_at
    async with async_session_factory() as session:
        assert len(list(await session.scalars(select(Media)))) == 2
        assert len(list(await session.scalars(select(ContentObject)))) == 1
    renders = list(rendition.parent.iterdir())
    assert renders == [rendition]
