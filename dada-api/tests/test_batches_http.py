"""Phase 4 activation, dataset freezing, and annotation batches over real HTTP."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, func, select

from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation_policy import (
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.batch import (
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationBatchAnnotator,
    BatchItem,
)
from dada_api.models.bootstrap import BootstrapRecord
from dada_api.models.dataset import DatasetSplit, SplitName
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase4-batch-password"
MEDIA_COUNT = 12
TEST_SET_SIZE = 4
TRAINING_SIZE = 5

DRAFT = {
    "name": "Road defects",
    "description": None,
    "task_type": "detection",
    "initial_training_size": TRAINING_SIZE,
    "test_set_size": TEST_SET_SIZE,
    "iteration_batch_size": 3,
}


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def _reset_database() -> None:
    """Remove every record these tests create."""
    async with async_session_factory() as session:
        await session.execute(delete(IdempotencyRecord))
        await session.execute(delete(AnnotationAssignment))
        await session.execute(delete(BatchItem))
        await session.execute(delete(AnnotationBatchAnnotator))
        await session.execute(delete(AnnotationBatch))
        await session.execute(delete(DatasetSplit))
        await session.execute(delete(AuditEntry))
        await session.execute(delete(AnnotationPolicyAnnotator))
        await session.execute(delete(AnnotationPolicyDefault))
        await session.execute(delete(ProjectClass))
        await session.execute(delete(Media))
        await session.execute(delete(ContentObject))
        await session.execute(delete(BootstrapRecord))
        await session.execute(delete(RefreshSession))
        await session.execute(delete(ProjectMember))
        await session.execute(delete(Project))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture
async def database() -> AsyncIterator[None]:
    """Provide an empty database around each test."""
    await _reset_database()
    yield
    await _reset_database()


async def _create_user(username: str, *, administrator: bool = False) -> User:
    """Persist a user with the shared test password."""
    async with async_session_factory() as session:
        user = User(
            username=username,
            display_name=username.title(),
            password_hash=hash_password(PASSWORD),
            is_administrator=administrator,
            is_active=True,
            version=1,
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
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


async def _add_media(project_id: str, count: int = MEDIA_COUNT) -> None:
    """Persist verified media rows directly.

    Ingestion has its own coverage. These tests need a dataset to select from,
    not another upload round trip.
    """
    async with async_session_factory() as session:
        for index in range(count):
            digest = f"{index:064x}"
            content = ContentObject(
                project_id=project_id,
                sha256=digest,
                size_bytes=1024 + index,
                media_type="image/jpeg",
                width=640,
                height=480,
                storage_key=f"{project_id}/{digest[:2]}/{digest[2:4]}/{digest}",
            )
            session.add(content)
            await session.flush()
            session.add(
                Media(
                    project_id=project_id,
                    content_object_id=content.id,
                    relative_path=f"camera-a/frame-{index:04d}.jpg",
                )
            )
        await session.commit()


async def _ready_project(
    client: httpx.AsyncClient,
    token: str,
    **overrides: object,
) -> dict:
    """Create a project with a class and a dataset, ready to activate."""
    created = await client.post(
        "/api/v1/projects", headers=_auth(token), json={**DRAFT, **overrides}
    )
    assert created.status_code == 201, created.text
    project = created.json()

    added = await client.post(
        f"/api/v1/projects/{project['id']}/classes",
        headers=_auth(token),
        json={"name": "pothole", "color": "#FF0000", "display_order": 0},
    )
    assert added.status_code == 201, added.text
    await _add_media(project["id"])
    return project


async def _activate(client: httpx.AsyncClient, token: str, project_id: str) -> dict:
    """Activate a project and return its representation."""
    response = await client.post(
        f"/api/v1/projects/{project_id}/activate", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _batches(
    client: httpx.AsyncClient, token: str, project_id: str
) -> dict[str, dict]:
    """Return a project's batches keyed by purpose."""
    response = await client.get(
        f"/api/v1/projects/{project_id}/batches", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return {item["purpose"]: item for item in response.json()["items"]}


async def test_activation_freezes_the_split_and_opens_two_batches(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        activated = await _activate(client, token, project["id"])
        assert activated["status"] == "active"

        by_purpose = await _batches(client, token, project["id"])

    assert set(by_purpose) == {"test", "initial_training"}
    assert by_purpose["test"]["total_items"] == TEST_SET_SIZE
    assert by_purpose["initial_training"]["total_items"] == TRAINING_SIZE
    for batch in by_purpose.values():
        assert batch["status"] == "preparing"
        assert batch["total_assignments"] == 0
        assert batch["selection_strategy"] == "random"
        assert batch["selection_seed"] > 0
        assert len(batch["selection_input_fingerprint"]) == 64

    async with async_session_factory() as session:
        splits = list(await session.scalars(select(DatasetSplit)))

    assert len(splits) == MEDIA_COUNT
    assert sum(1 for row in splits if row.split == SplitName.test) == TEST_SET_SIZE


async def test_test_media_never_reaches_the_training_batch(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _activate(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])

    async with async_session_factory() as session:
        held_out = set(
            await session.scalars(
                select(DatasetSplit.media_id).where(
                    DatasetSplit.split == SplitName.test
                )
            )
        )
        training_media = set(
            await session.scalars(
                select(BatchItem.media_id).where(
                    BatchItem.batch_id == by_purpose["initial_training"]["id"]
                )
            )
        )
        test_media = set(
            await session.scalars(
                select(BatchItem.media_id).where(
                    BatchItem.batch_id == by_purpose["test"]["id"]
                )
            )
        )

    assert test_media == held_out
    assert not training_media & held_out


async def test_activation_is_refused_twice_and_before_prerequisites(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        created = await client.post(
            "/api/v1/projects", headers=_auth(token), json=DRAFT
        )
        project = created.json()

        incomplete = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        assert incomplete.status_code == 409
        assert incomplete.json()["error"]["code"] == "activation_incomplete"
        assert set(incomplete.json()["error"]["details"]["missing"]) == {
            "classes",
            "media",
        }

        await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(token),
            json={"name": "pothole", "color": "#FF0000", "display_order": 0},
        )
        await _add_media(project["id"])
        await _activate(client, token, project["id"])

        again = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "project_not_draft"


async def test_single_mode_start_creates_one_unclaimed_assignment_per_item(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _activate(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])
        batch = by_purpose["initial_training"]

        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert started.status_code == 200, started.text
    body = started.json()
    assert body["status"] == "annotating"
    assert body["started_at"] is not None
    assert body["total_items"] == TRAINING_SIZE
    assert body["total_assignments"] == TRAINING_SIZE
    assert body["submitted_assignments"] == 0

    async with async_session_factory() as session:
        owners = list(await session.scalars(select(AnnotationAssignment.annotator_id)))

    assert owners == [None] * TRAINING_SIZE


async def _consensus_project(
    client: httpx.AsyncClient, token: str, members: list[str]
) -> dict:
    """Create an activated project whose default policy is consensus."""
    project = await _ready_project(client, token)
    annotator_ids = []
    for username in members:
        added = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": username, "role": "annotator"},
        )
        assert added.status_code == 201, added.text
        annotator_ids.append(added.json()["user_id"])

    saved = await client.put(
        f"/api/v1/projects/{project['id']}/annotation-policy",
        headers=_auth(token),
        json={
            "mode": "consensus",
            "annotator_ids": annotator_ids,
            "resolver": "two_stage_box_fusion",
            "parameters": {},
            "review_thresholds": {"agreement": 0.7},
            "version": 1,
        },
    )
    assert saved.status_code == 200, saved.text
    await _activate(client, token, project["id"])
    project["annotator_ids"] = annotator_ids
    return project


async def test_consensus_start_creates_one_assignment_per_group_member(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        project = await _consensus_project(client, token, ["annie", "bob"])
        by_purpose = await _batches(client, token, project["id"])
        batch = by_purpose["initial_training"]
        assert batch["mode"] == "consensus"
        assert batch["annotator_ids"] == project["annotator_ids"]
        assert batch["resolver"] == "two_stage_box_fusion"
        assert batch["review_thresholds"] == {"agreement": 0.7}

        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert started.status_code == 200, started.text
    assert started.json()["total_items"] == TRAINING_SIZE
    assert started.json()["total_assignments"] == TRAINING_SIZE * 2

    async with async_session_factory() as session:
        pairs = [
            (row.batch_item_id, row.annotator_id)
            for row in await session.scalars(
                select(AnnotationAssignment)
                .join(BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id)
                .where(BatchItem.batch_id == batch["id"])
            )
        ]

    assert len(pairs) == len(set(pairs)) == TRAINING_SIZE * 2
    assert {annotator for _, annotator in pairs} == set(project["annotator_ids"])


async def test_a_failed_start_creates_no_assignments(database: None) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        project = await _consensus_project(client, token, ["annie", "bob"])
        by_purpose = await _batches(client, token, project["id"])
        batch = by_purpose["initial_training"]

        removed = await client.delete(
            f"/api/v1/projects/{project['id']}/members/{project['annotator_ids'][0]}",
            headers=_auth(token),
        )
        assert removed.status_code == 204, removed.text

        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert started.status_code == 422, started.text
    assert started.json()["error"]["code"] == "invalid_consensus_group"

    async with async_session_factory() as session:
        assignments = await session.scalar(
            select(func.count()).select_from(AnnotationAssignment)
        )

    assert assignments == 0

    async with _client() as client:
        after = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(token),
        )

    assert after.json()["status"] == "preparing"
    assert after.json()["started_at"] is None


async def test_batch_policy_is_editable_while_preparing_and_locked_after_start(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        project = await _consensus_project(client, token, ["annie", "bob"])
        by_purpose = await _batches(client, token, project["id"])
        batch = by_purpose["test"]

        edited = await client.patch(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(token),
            json={
                "mode": "single",
                "annotator_ids": [],
                "resolver": None,
                "parameters": {},
                "review_thresholds": {},
            },
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["mode"] == "single"
        assert edited.json()["annotator_ids"] == []

        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )
        assert started.status_code == 200, started.text

        locked = await client.patch(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(token),
            json={
                "mode": "single",
                "annotator_ids": [],
                "resolver": None,
                "parameters": {},
                "review_thresholds": {},
            },
        )
        restarted = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert locked.status_code == 409
    assert locked.json()["error"]["code"] == "policy_locked"
    assert restarted.status_code == 409
    assert restarted.json()["error"]["code"] == "batch_already_started"


async def test_editing_the_project_default_leaves_a_snapshot_untouched(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        project = await _consensus_project(client, token, ["annie", "bob"])
        before = (await _batches(client, token, project["id"]))["test"]

        changed = await client.put(
            f"/api/v1/projects/{project['id']}/annotation-policy",
            headers=_auth(token),
            json={
                "mode": "single",
                "annotator_ids": [],
                "resolver": None,
                "parameters": {},
                "review_thresholds": {},
                "version": 2,
            },
        )
        assert changed.status_code == 200, changed.text

        after = (await _batches(client, token, project["id"]))["test"]

    assert before["mode"] == after["mode"] == "consensus"
    assert after["annotator_ids"] == project["annotator_ids"]
    assert after["source_policy_version"] == 2


async def test_batch_routes_enforce_the_project_role_matrix(database: None) -> None:
    await _create_user("owner")
    await _create_user("viv")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _activate(client, token, project["id"])
        batch = (await _batches(client, token, project["id"]))["test"]

        added = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": "viv", "role": "viewer"},
        )
        assert added.status_code == 201, added.text
        viewer_token = await _token("viv")

        readable = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(viewer_token),
        )
        start_refused = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(viewer_token),
        )
        patch_refused = await client.patch(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(viewer_token),
            json={
                "mode": "single",
                "annotator_ids": [],
                "resolver": None,
                "parameters": {},
                "review_thresholds": {},
            },
        )

    assert readable.status_code == 200
    assert start_refused.status_code == 403
    assert patch_refused.status_code == 403


async def test_a_batch_of_another_project_is_not_reachable(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        first = await _ready_project(client, token)
        await _activate(client, token, first["id"])
        batch = (await _batches(client, token, first["id"]))["test"]

        second = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**DRAFT, "name": "Second project"},
        )
        assert second.status_code == 201

        response = await client.get(
            f"/api/v1/projects/{second.json()['id']}/batches/{batch['id']}",
            headers=_auth(token),
        )

    assert response.status_code == 404
