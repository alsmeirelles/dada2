"""Phase 3 resumable ingestion, media, and purge behaviour over real HTTP."""

import hashlib
import io
import os
import shutil
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import delete, func, select

from dada_api.core.config import get_settings
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
from dada_api.models.project import Project, ProjectClass, ProjectMember, ProjectRole
from dada_api.models.upload import UploadChunk, UploadItem, UploadSession
from dada_api.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase3-test-password"

DRAFT = {
    "name": "Bridge cracks",
    "description": None,
    "task_type": "detection",
    "initial_training_size": 1,
    "test_set_size": 1,
    "iteration_batch_size": 1,
}


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def _reset_database() -> None:
    """Remove every record the Phase 3 tests create."""
    async with async_session_factory() as session:
        await session.execute(delete(IdempotencyRecord))
        await session.execute(delete(UploadChunk))
        await session.execute(delete(UploadItem))
        await session.execute(delete(UploadSession))
        await session.execute(delete(Media))
        await session.execute(delete(ContentObject))
        await session.execute(delete(AuditEntry))
        await session.execute(delete(AnnotationPolicyAnnotator))
        await session.execute(delete(AnnotationPolicyDefault))
        await session.execute(delete(ProjectClass))
        await session.execute(delete(ProjectMember))
        await session.execute(delete(Project))
        await session.execute(delete(User))
        await session.commit()


def _reset_storage() -> None:
    """Empty both configured storage roots."""
    settings = get_settings()
    for root in (settings.media_root, settings.upload_parts_root):
        if root.exists():
            shutil.rmtree(root)


@pytest.fixture
async def database() -> AsyncIterator[None]:
    """Provide an empty database and empty storage around each test."""
    await _reset_database()
    _reset_storage()
    yield
    await _reset_database()
    _reset_storage()


@pytest.fixture
def relaxed_limits() -> Iterator[None]:
    """Temporarily shrink the advertised upload limits."""
    settings = get_settings()
    original = (settings.max_project_files, settings.max_file_bytes)
    yield
    settings.max_project_files, settings.max_file_bytes = original


async def _create_user(username: str) -> User:
    """Persist a user with the shared test password."""
    async with async_session_factory() as session:
        user = User(
            username=username,
            display_name=username.title(),
            password_hash=hash_password(PASSWORD),
            is_administrator=False,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _token(username: str) -> str:
    """Log in and return the access token."""
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token",
            json={"username": username, "password": PASSWORD},
        )
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


def _png(color: tuple[int, int, int] = (255, 0, 0), size: tuple[int, int] = (8, 6)):
    """Return the bytes of a small PNG image."""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _entry(
    client_file_id: str,
    relative_path: str,
    data: bytes,
    *,
    media_type: str = "image/png",
    size_bytes: int | None = None,
    sha256: str | None = None,
) -> dict:
    """Build one manifest entry, allowing deliberate mismatches for tests."""
    return {
        "client_file_id": client_file_id,
        "relative_path": relative_path,
        "file_name": relative_path.rsplit("/", 1)[-1],
        "media_type": media_type,
        "size_bytes": len(data) if size_bytes is None else size_bytes,
        "sha256": hashlib.sha256(data).hexdigest() if sha256 is None else sha256,
    }


async def _project(client: httpx.AsyncClient, token: str) -> dict:
    """Create a project through the API."""
    response = await client.post(
        "/api/v1/projects",
        headers={**_auth(token), "Idempotency-Key": "phase3-project"},
        json=DRAFT,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _manifest(
    client: httpx.AsyncClient,
    token: str,
    project_id: str,
    files: list[dict],
    *,
    key: str = "phase3-upload",
) -> httpx.Response:
    """Create an upload session from a manifest."""
    return await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        headers={**_auth(token), "Idempotency-Key": key},
        json={"files": files},
    )


async def _put_chunk(
    client: httpx.AsyncClient,
    token: str,
    upload_id: str,
    client_file_id: str,
    data: bytes,
    *,
    offset: int = 0,
    checksum: str | None = None,
) -> httpx.Response:
    """Send one chunk of an upload item."""
    return await client.put(
        f"/api/v1/uploads/{upload_id}/files/{client_file_id}",
        headers={
            **_auth(token),
            "Content-Type": "application/octet-stream",
            "Upload-Offset": str(offset),
            "X-Chunk-SHA256": (
                hashlib.sha256(data).hexdigest() if checksum is None else checksum
            ),
        },
        content=data,
    )


def _dispositions(payload: dict) -> dict[str, str]:
    """Map each item's client identifier to its disposition."""
    return {item["client_file_id"]: item["disposition"] for item in payload["items"]}


def _reasons(payload: dict) -> dict[str, str | None]:
    """Map each item's client identifier to its rejection reason."""
    return {item["client_file_id"]: item["reason"] for item in payload["items"]}


async def test_upload_completes_and_appears_in_media(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "camera-a/one.png", image)]
        )
        assert created.status_code == 201, created.text
        session_body = created.json()
        assert _dispositions(session_body) == {"f1": "upload_required"}

        chunk = await _put_chunk(client, token, session_body["id"], "f1", image)
        assert chunk.status_code == 200, chunk.text
        assert chunk.json()["received_bytes"] == len(image)
        assert chunk.headers["Upload-Offset"] == str(len(image))

        completed = await client.post(
            f"/api/v1/uploads/{session_body['id']}/complete",
            headers={**_auth(token), "Idempotency-Key": "phase3-complete"},
            json={},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "completed"

        listing = await client.get(
            f"/api/v1/projects/{project['id']}/media", headers=_auth(token)
        )
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["relative_path"] == "camera-a/one.png"
        assert (items[0]["width"], items[0]["height"]) == (8, 6)
        assert items[0]["sha256"] == hashlib.sha256(image).hexdigest()


async def test_upload_survives_an_api_restart(database: None) -> None:
    from dada_api.main import create_app

    await _create_user("owner")
    token = await _token("owner")
    image = _png(size=(20, 20))
    half = len(image) // 2

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "part.png", image)]
        )
        upload_id = created.json()["id"]
        first = await _put_chunk(client, token, upload_id, "f1", image[:half])
        assert first.status_code == 200

    restarted = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()),
        base_url="http://testserver",
    )
    async with restarted as client:
        status = await client.get(f"/api/v1/uploads/{upload_id}", headers=_auth(token))
        assert status.status_code == 200
        item = status.json()["items"][0]
        assert item["received_bytes"] == half

        resumed = await _put_chunk(
            client, token, upload_id, "f1", image[half:], offset=half
        )
        assert resumed.status_code == 200
        assert resumed.json()["received_bytes"] == len(image)

        completed = await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "restart-complete"},
            json={},
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"


async def test_corrupt_chunk_is_rejected_and_not_persisted(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]

        response = await _put_chunk(
            client, token, upload_id, "f1", image, checksum="0" * 64
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "checksum_mismatch"

        status = await client.get(f"/api/v1/uploads/{upload_id}", headers=_auth(token))
        assert status.json()["items"][0]["received_bytes"] == 0

    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(UploadChunk)) == 0


async def test_declared_digest_must_match_the_assembled_file(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()
    tampered = image[:-1] + bytes([image[-1] ^ 0xFF])

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]
        accepted = await _put_chunk(client, token, upload_id, "f1", tampered)
        assert accepted.status_code == 200, accepted.text

        completed = await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "bad-digest"},
            json={},
        )
        assert completed.status_code == 422
        assert completed.json()["error"]["code"] == "checksum_mismatch"

    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Media)) == 0
        upload = await session.get(UploadSession, upload_id)
        assert upload is not None
        assert upload.status == "failed"


async def test_a_non_image_payload_is_refused(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    payload = b"this is not an image at all"

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", payload)]
        )
        upload_id = created.json()["id"]
        assert (
            await _put_chunk(client, token, upload_id, "f1", payload)
        ).status_code == 200

        completed = await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "not-an-image"},
            json={},
        )
        assert completed.status_code == 422
        assert completed.json()["error"]["code"] == "invalid_image"


async def test_duplicate_content_is_stored_once_under_two_paths(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client,
            token,
            project["id"],
            [_entry("f1", "a/one.png", image), _entry("f2", "b/one.png", image)],
        )
        upload_id = created.json()["id"]
        for client_file_id in ("f1", "f2"):
            assert (
                await _put_chunk(client, token, upload_id, client_file_id, image)
            ).status_code == 200

        completed = await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "dup-complete"},
            json={},
        )
        assert completed.status_code == 200

        listing = await client.get(
            f"/api/v1/projects/{project['id']}/media", headers=_auth(token)
        )
        paths = [item["relative_path"] for item in listing.json()["items"]]
        assert paths == ["a/one.png", "b/one.png"]

    async with async_session_factory() as session:
        assert (
            await session.scalar(select(func.count()).select_from(ContentObject)) == 1
        )


async def test_known_content_is_reported_as_already_present(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        first = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = first.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image)
        await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "present-complete"},
            json={},
        )

        second = await _manifest(
            client,
            token,
            project["id"],
            [_entry("f2", "copy.png", image)],
            key="second-manifest",
        )
        assert _dispositions(second.json()) == {"f2": "already_present"}

        completed = await client.post(
            f"/api/v1/uploads/{second.json()['id']}/complete",
            headers={**_auth(token), "Idempotency-Key": "present-complete-2"},
            json={},
        )
        assert completed.status_code == 200

        listing = await client.get(
            f"/api/v1/projects/{project['id']}/media", headers=_auth(token)
        )
        assert len(listing.json()["items"]) == 2


async def test_offset_conflicts_and_idempotent_chunk_retries(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png(size=(20, 20))
    half = len(image) // 2

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]

        skipped = await _put_chunk(
            client, token, upload_id, "f1", image[half:], offset=half
        )
        assert skipped.status_code == 409
        assert skipped.json()["error"]["code"] == "offset_mismatch"
        assert skipped.json()["error"]["details"]["expected_offset"] == 0

        assert (
            await _put_chunk(client, token, upload_id, "f1", image[:half])
        ).status_code == 200
        replay = await _put_chunk(client, token, upload_id, "f1", image[:half])
        assert replay.status_code == 200
        assert replay.json()["received_bytes"] == half


async def test_unsafe_paths_are_rejected_by_the_manifest(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client,
            token,
            project["id"],
            [
                _entry("absolute", "/etc/passwd.png", image),
                _entry("traversal", "../../secret.png", image),
                _entry("first", "café/one.png", image),
                _entry("collision", "café/one.png", image),
                _entry("control", "bad\x00name.png", image),
            ],
        )
        assert created.status_code == 201, created.text
        dispositions = _dispositions(created.json())
        reasons = _reasons(created.json())

        assert dispositions["absolute"] == "rejected"
        assert dispositions["traversal"] == "rejected"
        assert dispositions["control"] == "rejected"
        assert dispositions["first"] == "upload_required"
        assert dispositions["collision"] == "rejected"
        assert reasons["collision"] == "invalid_relative_path"


async def test_size_and_media_type_limits_are_enforced(
    database: None, relaxed_limits: None
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()
    settings = get_settings()

    async with _client() as client:
        project = await _project(client, token)

        settings.max_file_bytes = len(image) - 1
        oversized = await _manifest(
            client, token, project["id"], [_entry("big", "big.png", image)]
        )
        assert _reasons(oversized.json())["big"] == "file_too_large"

        settings.max_file_bytes = 100 * 1024 * 1024
        wrong_type = await _manifest(
            client,
            token,
            project["id"],
            [_entry("gif", "one.gif", image, media_type="image/gif")],
            key="wrong-type",
        )
        assert _reasons(wrong_type.json())["gif"] == "unsupported_media_type"

        settings.max_project_files = 1
        too_many = await _manifest(
            client,
            token,
            project["id"],
            [_entry("a", "a.png", image), _entry("b", "b.png", image)],
            key="too-many",
        )
        assert too_many.status_code == 422
        assert too_many.json()["error"]["code"] == "too_many_files"


async def test_manifest_and_completion_replay_the_original_response(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        files = [_entry("f1", "one.png", image)]
        first = await _manifest(client, token, project["id"], files)
        replay = await _manifest(client, token, project["id"], files)
        assert replay.status_code == 201
        assert replay.json()["id"] == first.json()["id"]

        upload_id = first.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image)
        headers = {**_auth(token), "Idempotency-Key": "complete-once"}
        done = await client.post(
            f"/api/v1/uploads/{upload_id}/complete", headers=headers, json={}
        )
        again = await client.post(
            f"/api/v1/uploads/{upload_id}/complete", headers=headers, json={}
        )
        assert done.status_code == again.status_code == 200
        assert again.json()["status"] == "completed"

    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Media)) == 1


async def test_completion_refuses_an_unfinished_file(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png(size=(20, 20))

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image[: len(image) // 2])

        completed = await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "incomplete"},
            json={},
        )
        assert completed.status_code == 409
        assert completed.json()["error"]["code"] == "upload_not_complete"
        assert completed.json()["error"]["details"]["pending"] == ["f1"]


async def test_cancellation_purges_every_temporary_part(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image)

        parts = get_settings().upload_parts_root / upload_id
        assert parts.exists()

        cancelled = await client.delete(
            f"/api/v1/uploads/{upload_id}", headers=_auth(token)
        )
        assert cancelled.status_code == 204
        assert not parts.exists()

    async with async_session_factory() as session:
        assert await session.get(UploadSession, upload_id) is None
        assert await session.scalar(select(func.count()).select_from(UploadChunk)) == 0


async def test_an_expired_session_refuses_further_work(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]

        async with async_session_factory() as session:
            upload = await session.get(UploadSession, upload_id)
            assert upload is not None
            upload.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()

        response = await _put_chunk(client, token, upload_id, "f1", image)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "upload_session_expired"


async def test_project_deletion_purges_media_and_records(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        created = await _manifest(
            client, token, project["id"], [_entry("f1", "one.png", image)]
        )
        upload_id = created.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image)
        await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "delete-complete"},
            json={},
        )

        tree = get_settings().media_root / project["id"]
        assert tree.exists()

        deleted = await client.delete(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        assert deleted.status_code == 204
        assert not tree.exists()

        missing = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        assert missing.status_code == 404

    async with async_session_factory() as session:
        for model in (Media, ContentObject, UploadSession, UploadItem, AuditEntry):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_only_the_owner_may_delete_a_project(database: None) -> None:
    await _create_user("owner")
    await _create_user("manager")
    owner_token = await _token("owner")
    manager_token = await _token("manager")

    async with _client() as client:
        project = await _project(client, owner_token)
        added = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner_token),
            json={"username": "manager", "role": "manager"},
        )
        assert added.status_code == 201, added.text

        refused = await client.delete(
            f"/api/v1/projects/{project['id']}", headers=_auth(manager_token)
        )
        assert refused.status_code == 403


async def test_a_viewer_cannot_start_an_upload(database: None) -> None:
    await _create_user("owner")
    await _create_user("viewer")
    owner_token = await _token("owner")
    viewer_token = await _token("viewer")

    async with _client() as client:
        project = await _project(client, owner_token)
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner_token),
            json={"username": "viewer", "role": "viewer"},
        )

        refused = await _manifest(
            client, viewer_token, project["id"], [_entry("f1", "one.png", _png())]
        )
        assert refused.status_code == 403


async def test_activation_requires_classes_and_ingested_media(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    image = _png()

    async with _client() as client:
        project = await _project(client, token)
        blocked = await client.post(
            f"/api/v1/projects/{project['id']}/activate",
            headers={**_auth(token), "Idempotency-Key": "activate-1"},
            json={},
        )
        assert blocked.status_code == 409
        details = blocked.json()["error"]["details"]["missing"]
        assert "classes" in details
        assert "media" in details

        await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(token),
            json={"name": "crack", "color": "#FF0000", "display_order": 0},
        )
        created = await _manifest(
            client,
            token,
            project["id"],
            [
                _entry("f1", "one.png", image),
                _entry("f2", "two.png", _png(color=(0, 255, 0))),
            ],
        )
        upload_id = created.json()["id"]
        await _put_chunk(client, token, upload_id, "f1", image)
        await _put_chunk(client, token, upload_id, "f2", _png(color=(0, 255, 0)))
        await client.post(
            f"/api/v1/uploads/{upload_id}/complete",
            headers={**_auth(token), "Idempotency-Key": "activate-complete"},
            json={},
        )

        activated = await client.post(
            f"/api/v1/projects/{project['id']}/activate",
            headers={**_auth(token), "Idempotency-Key": "activate-2"},
            json={},
        )
        assert activated.status_code == 200, activated.text


async def test_member_roles_reach_ingestion_through_the_central_matrix(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annotator")
    owner_token = await _token("owner")
    annotator_token = await _token("annotator")

    async with _client() as client:
        project = await _project(client, owner_token)
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner_token),
            json={"username": "annotator", "role": "annotator"},
        )

        readable = await client.get(
            f"/api/v1/projects/{project['id']}/media", headers=_auth(annotator_token)
        )
        assert readable.status_code == 200

        refused = await _manifest(
            client, annotator_token, project["id"], [_entry("f1", "one.png", _png())]
        )
        assert refused.status_code == 403

    async with async_session_factory() as session:
        role = await session.scalar(
            select(ProjectMember.role).where(
                ProjectMember.project_id == project["id"],
                ProjectMember.user_id
                == (
                    await session.scalar(
                        select(User.id).where(User.username == "annotator")
                    )
                ),
            )
        )
        assert role is ProjectRole.annotator
