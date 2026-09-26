"""Dataset preparation, activation, the training pool, and batches over real HTTP."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, func, select, update

from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation_policy import (
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.batch import (
    ITEM_RESOLVED,
    AnnotationAssignment,
    AnnotationBatch,
    AnnotationBatchAnnotator,
    BatchItem,
    BatchStatus,
)
from dada_api.models.bootstrap import BootstrapRecord
from dada_api.models.dataset import DatasetSplit, SplitName
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.label_import import AnnotationImport
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User
from dada_api.services import datasets, selection

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase4-batch-password"
MEDIA_COUNT = 12
TEST_SET_SIZE = 4
VALIDATION_SET_SIZE = 2
TRAINING_SIZE = 5
ITERATION_SIZE = 3
TRAIN_SPLIT_SIZE = MEDIA_COUNT - TEST_SET_SIZE - VALIDATION_SET_SIZE

DRAFT = {
    "name": "Road defects",
    "description": None,
    "task_type": "detection",
    "initial_training_size": TRAINING_SIZE,
    "test_set_size": TEST_SET_SIZE,
    "validation_set_size": VALIDATION_SET_SIZE,
    "iteration_batch_size": ITERATION_SIZE,
}
STATIC = {
    "name": "Static inventory",
    "description": None,
    "task_type": "detection",
    "dataset_layout": "single_batch",
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
        await session.execute(delete(AnnotationImport))
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
    *,
    base: dict = DRAFT,
    **overrides: object,
) -> dict:
    """Create a project with a class and a dataset, ready to prepare."""
    created = await client.post(
        "/api/v1/projects", headers=_auth(token), json={**base, **overrides}
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


async def _activate_prepared(
    client: httpx.AsyncClient, token: str, project_id: str
) -> dict:
    """Activate an already prepared project."""
    response = await client.post(
        f"/api/v1/projects/{project_id}/activate", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _prepare(client: httpx.AsyncClient, token: str, project_id: str) -> dict:
    """Prepare a draft's dataset layout and return the layout summary."""
    response = await client.post(
        f"/api/v1/projects/{project_id}/dataset-layout/prepare", headers=_auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _layout(client: httpx.AsyncClient, token: str, project_id: str) -> dict:
    """Return a project's dataset layout summary."""
    response = await client.get(
        f"/api/v1/projects/{project_id}/dataset-layout", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _activate(client: httpx.AsyncClient, token: str, project_id: str) -> dict:
    """Prepare and activate a project, returning its representation."""
    await _prepare(client, token, project_id)
    return await _activate_prepared(client, token, project_id)


async def _batches(
    client: httpx.AsyncClient, token: str, project_id: str
) -> dict[str, dict]:
    """Return a project's batches keyed by purpose."""
    response = await client.get(
        f"/api/v1/projects/{project_id}/batches", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return {item["purpose"]: item for item in response.json()["items"]}


async def test_preparation_freezes_three_splits_and_opens_the_initial_batches(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        layout = await _prepare(client, token, project["id"])
        draft = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        assert draft.json()["status"] == "draft"
        assert draft.json()["dataset_prepared_at"] is not None

        activated = await _activate_prepared(client, token, project["id"])
        assert activated["status"] == "active"

        by_purpose = await _batches(client, token, project["id"])

    assert layout["dataset_layout"] == "split"
    assert layout["train_size"] == TRAIN_SPLIT_SIZE
    assert layout["validation_size"] == VALIDATION_SET_SIZE
    assert layout["test_size"] == TEST_SET_SIZE
    assert layout["first_training_batch_size"] == TRAINING_SIZE
    assert layout["training_pool_size"] == TRAIN_SPLIT_SIZE - TRAINING_SIZE
    assert len(layout["batch_ids"]) == 3

    assert set(by_purpose) == {"test", "validation", "initial_training"}
    assert by_purpose["test"]["total_items"] == TEST_SET_SIZE
    assert by_purpose["validation"]["total_items"] == VALIDATION_SET_SIZE
    assert by_purpose["initial_training"]["total_items"] == TRAINING_SIZE
    assert by_purpose["initial_training"]["requested_size"] == TRAINING_SIZE
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
    assert (
        sum(1 for row in splits if row.split == SplitName.validation)
        == VALIDATION_SET_SIZE
    )
    assert sum(1 for row in splits if row.split == SplitName.train) == TRAIN_SPLIT_SIZE


async def test_held_out_media_never_reaches_the_training_batch(database: None) -> None:
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
                    DatasetSplit.split.in_((SplitName.validation, SplitName.test))
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
        validation_media = set(
            await session.scalars(
                select(BatchItem.media_id).where(
                    BatchItem.batch_id == by_purpose["validation"]["id"]
                )
            )
        )

    assert test_media | validation_media == held_out
    assert not test_media & validation_media
    assert not training_media & held_out


async def test_percentage_sizes_are_resolved_and_fixed_at_preparation(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(
            client,
            token,
            test_set_size=None,
            test_set_percentage=25,
            validation_set_size=None,
            validation_set_percentage=20,
        )
        activated = await _activate(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])

    assert activated["test_set_size"] == 3
    assert activated["test_set_percentage"] == 25
    assert activated["validation_set_size"] == 3
    assert by_purpose["test"]["total_items"] == 3
    assert by_purpose["validation"]["total_items"] == 3
    assert by_purpose["initial_training"]["total_items"] == TRAINING_SIZE


async def test_an_omitted_first_batch_size_uses_the_iteration_size(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token, initial_training_size=None)
        assert project["initial_training_size"] is None
        layout = await _prepare(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])

    assert layout["first_training_batch_size"] == ITERATION_SIZE
    assert layout["training_pool_size"] == TRAIN_SPLIT_SIZE - ITERATION_SIZE
    assert by_purpose["initial_training"]["total_items"] == ITERATION_SIZE
    assert by_purpose["initial_training"]["requested_size"] == ITERATION_SIZE


async def test_split_draws_are_reproducible_from_their_batches(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _prepare(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])

    async with async_session_factory() as session:
        media_ids = list(
            await session.scalars(
                select(Media.id)
                .where(Media.project_id == project["id"])
                .order_by(Media.relative_path, Media.id)
            )
        )
        items = {
            purpose: set(
                await session.scalars(
                    select(BatchItem.media_id).where(BatchItem.batch_id == batch["id"])
                )
            )
            for purpose, batch in by_purpose.items()
        }

    test = by_purpose["test"]
    assert test["selection_input_fingerprint"] == selection.fingerprint(media_ids)
    assert items["test"] == set(
        selection.choose(media_ids, TEST_SET_SIZE, test["selection_seed"])
    )

    after_test = [media_id for media_id in media_ids if media_id not in items["test"]]
    validation = by_purpose["validation"]
    assert validation["selection_input_fingerprint"] == selection.fingerprint(
        after_test
    )
    assert items["validation"] == set(
        selection.choose(after_test, VALIDATION_SET_SIZE, validation["selection_seed"])
    )

    train = [media_id for media_id in after_test if media_id not in items["validation"]]
    training = by_purpose["initial_training"]
    assert items["initial_training"] == set(
        selection.choose(train, TRAINING_SIZE, training["selection_seed"])
    )


async def test_the_training_pool_keeps_unselected_and_returned_train_media(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project_body = await _ready_project(client, token)
        await _prepare(client, token, project_body["id"])
        training = (await _batches(client, token, project_body["id"]))[
            "initial_training"
        ]

    async with async_session_factory() as session:
        project = await session.get(Project, project_body["id"])
        assert project is not None
        train = set(
            await session.scalars(
                select(DatasetSplit.media_id).where(
                    DatasetSplit.split == SplitName.train
                )
            )
        )
        selected = list(
            await session.scalars(
                select(BatchItem.media_id).where(BatchItem.batch_id == training["id"])
            )
        )
        assert set(await datasets.eligible_training_pool(session, project)) == (
            train - set(selected)
        )

        resolved = selected[0]
        await session.execute(
            update(BatchItem)
            .where(BatchItem.media_id == resolved)
            .values(status=ITEM_RESOLVED)
        )
        await session.execute(
            update(AnnotationBatch)
            .where(AnnotationBatch.id == training["id"])
            .values(status=BatchStatus.failed)
        )
        await session.commit()

        assert set(await datasets.eligible_training_pool(session, project)) == (
            train - {resolved}
        )


async def test_first_acquisition_waits_for_accepted_resolutions(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project_body = await _ready_project(client, token)
        await _activate(client, token, project_body["id"])
        by_purpose = await _batches(client, token, project_body["id"])
        for batch in by_purpose.values():
            started = await client.post(
                f"/api/v1/projects/{project_body['id']}/batches/{batch['id']}/start",
                headers=_auth(token),
            )
            assert started.status_code == 200, started.text

    async with async_session_factory() as session:
        project = await session.get(Project, project_body["id"])
        assert project is not None
        assert not await datasets.first_acquisition_ready(session, project)

        await session.execute(update(AnnotationAssignment).values(status="submitted"))
        await session.commit()
        assert not await datasets.first_acquisition_ready(session, project)

        remaining = await session.scalar(select(BatchItem.id).limit(1))
        await session.execute(
            update(BatchItem)
            .where(BatchItem.id != remaining)
            .values(status=ITEM_RESOLVED)
        )
        await session.commit()
        assert not await datasets.first_acquisition_ready(session, project)

        await session.execute(update(BatchItem).values(status=ITEM_RESOLVED))
        await session.commit()
        assert await datasets.first_acquisition_ready(session, project)


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
            "dataset_layout",
        }

        await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(token),
            json={"name": "pothole", "color": "#FF0000", "display_order": 0},
        )
        await _add_media(project["id"])
        unprepared = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        assert unprepared.status_code == 409
        assert unprepared.json()["error"]["details"]["missing"] == ["dataset_layout"]

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


async def test_a_single_batch_project_annotates_every_image_once(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        refused = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**STATIC, "acquisition_strategy": "active_learning"},
        )
        assert refused.status_code == 422

        project = await _ready_project(client, token, base=STATIC)
        assert project["dataset_layout"] == "single_batch"
        assert project["acquisition_strategy"] == "random"
        assert project["iteration_batch_size"] is None

        annotator_ids = []
        for username in ("annie", "bob"):
            added = await client.post(
                f"/api/v1/projects/{project['id']}/members",
                headers=_auth(token),
                json={"username": username, "role": "annotator"},
            )
            annotator_ids.append(added.json()["user_id"])
        saved = await client.put(
            f"/api/v1/projects/{project['id']}/annotation-policy",
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": annotator_ids,
                "resolver": "two_stage_box_fusion",
                "parameters": {},
                "review_thresholds": {},
                "version": 1,
            },
        )
        assert saved.status_code == 200, saved.text

        layout = await _prepare(client, token, project["id"])
        await _activate_prepared(client, token, project["id"])
        by_purpose = await _batches(client, token, project["id"])
        batch = by_purpose["initial_annotation"]
        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert set(by_purpose) == {"initial_annotation"}
    assert layout["train_size"] == layout["validation_size"] == layout["test_size"] == 0
    assert layout["first_training_batch_size"] is None
    assert layout["training_pool_size"] == 0
    assert started.status_code == 200, started.text
    assert started.json()["total_items"] == MEDIA_COUNT
    assert started.json()["total_assignments"] == MEDIA_COUNT * 2

    async with async_session_factory() as session:
        splits = await session.scalar(select(func.count()).select_from(DatasetSplit))
        stored = await session.get(Project, project["id"])
        assert stored is not None
        await session.execute(update(BatchItem).values(status=ITEM_RESOLVED))
        await session.commit()
        ready = await datasets.first_acquisition_ready(session, stored)

    assert splits == 0
    assert ready is False


async def test_preparation_is_draft_only_and_resettable(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(
            client,
            token,
            test_set_size=None,
            test_set_percentage=25,
        )
        not_prepared = await client.delete(
            f"/api/v1/projects/{project['id']}/dataset-layout", headers=_auth(token)
        )
        await _prepare(client, token, project["id"])
        twice = await client.post(
            f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )

        reset = await client.delete(
            f"/api/v1/projects/{project['id']}/dataset-layout", headers=_auth(token)
        )
        after_reset = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        layout = await _layout(client, token, project["id"])

        await _activate(client, token, project["id"])
        active_reset = await client.delete(
            f"/api/v1/projects/{project['id']}/dataset-layout", headers=_auth(token)
        )
        active_prepare = await client.post(
            f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )

    assert not_prepared.status_code == 409
    assert not_prepared.json()["error"]["code"] == "dataset_not_prepared"
    assert twice.status_code == 409
    assert twice.json()["error"]["code"] == "dataset_already_prepared"
    assert reset.status_code == 204
    assert after_reset.json()["dataset_prepared_at"] is None
    assert after_reset.json()["test_set_size"] is None
    assert layout["batch_ids"] == []
    assert layout["train_size"] == 0
    assert active_reset.json()["error"]["code"] == "project_not_draft"
    assert active_prepare.json()["error"]["code"] == "project_not_draft"


async def test_preparation_checks_capacity_for_the_first_batch_only(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        fits = await _ready_project(client, token, initial_training_size=6)
        prepared = await client.post(
            f"/api/v1/projects/{fits['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )
        too_big = await _ready_project(
            client, token, name="Too big", initial_training_size=7
        )
        refused = await client.post(
            f"/api/v1/projects/{too_big['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )

    assert prepared.status_code == 201, prepared.text
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "preparation_incomplete"
    assert refused.json()["error"]["details"]["missing"] == ["insufficient_media"]


async def test_changing_the_class_index_map_resets_preparation(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _prepare(client, token, project["id"])
        classes = await client.get(
            f"/api/v1/projects/{project['id']}/classes", headers=_auth(token)
        )
        pothole = classes.json()["items"][0]

        renamed = await client.patch(
            f"/api/v1/projects/{project['id']}/classes/{pothole['id']}",
            headers=_auth(token),
            json={"name": "hole", "version": pothole["version"]},
        )
        after_rename = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )

        reordered = await client.patch(
            f"/api/v1/projects/{project['id']}/classes/{pothole['id']}",
            headers=_auth(token),
            json={"display_order": 3, "version": renamed.json()["version"]},
        )
        after_reorder = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        layout = await _layout(client, token, project["id"])

    assert renamed.status_code == 200, renamed.text
    assert after_rename.json()["dataset_prepared_at"] is not None
    assert reordered.status_code == 200, reordered.text
    assert after_reorder.json()["dataset_prepared_at"] is None
    assert layout["batch_ids"] == []

    async with async_session_factory() as session:
        reasons = [
            entry.after["reason"]
            for entry in await session.scalars(
                select(AuditEntry).where(AuditEntry.action == "dataset.reset")
            )
        ]

    assert reasons == ["classes_changed"]


async def test_a_prepared_draft_cannot_distribute_assignments(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await _prepare(client, token, project["id"])
        batch = (await _batches(client, token, project["id"]))["test"]
        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(token),
        )

    assert started.status_code == 409
    assert started.json()["error"]["code"] == "project_not_active"


async def test_preparation_follows_the_project_role_matrix(database: None) -> None:
    await _create_user("owner")
    await _create_user("anna")
    token = await _token("owner")

    async with _client() as client:
        project = await _ready_project(client, token)
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": "anna", "role": "annotator"},
        )
        annotator_token = await _token("anna")

        refused = await client.post(
            f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
            headers=_auth(annotator_token),
        )
        readable = await client.get(
            f"/api/v1/projects/{project['id']}/dataset-layout",
            headers=_auth(annotator_token),
        )

    assert refused.status_code == 403
    assert readable.status_code == 200
