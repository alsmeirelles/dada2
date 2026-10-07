"""Direct image assignments, drafts, submissions, and manager actions over real HTTP."""

import os
from collections.abc import AsyncIterator
from itertools import groupby

import httpx
import pytest
from sqlalchemy import delete, func, select

from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation import AnnotationSubmission, ResolvedAnnotation
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
from dada_api.models.consensus import OutboxEvent, ResolutionWorkItem, ReviewSubmission
from dada_api.models.dataset import DatasetSplit
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.label_import import AnnotationImport
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.user import User
from dada_api.services import datasets, resolution_foundation

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase5-assignment-password"
MEDIA_COUNT = 6
TRAINING_SIZE = 2
DRAFT = {
    "name": "Road defects",
    "description": None,
    "task_type": "detection",
    "test_set_size": 1,
    "validation_set_size": 1,
    "initial_training_size": TRAINING_SIZE,
    "iteration_batch_size": 2,
}
QUEUE_FIELDS = {
    "id",
    "batch_id",
    "batch_purpose",
    "media_id",
    "relative_path",
    "width",
    "height",
    "status",
    "version",
    "seeded_from_import",
    "updated_at",
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
        await session.execute(delete(ResolvedAnnotation))
        await session.execute(delete(AnnotationSubmission))
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


async def _create_user(username: str, *, administrator: bool = False) -> str:
    """Persist a user with the shared test password and return its identifier."""
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
        return user.id


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


def _image_bytes(index: int) -> bytes:
    """Return the stored bytes of one test image."""
    return f"image-{index}".encode() * 16


async def _add_media(project_id: str) -> None:
    """Persist media rows and their stored bytes directly.

    Ingestion has its own coverage; these tests need images to annotate and
    to serve through a signed link, not another upload round trip.
    """
    async with async_session_factory() as session:
        for index in range(MEDIA_COUNT):
            digest = f"{index:064x}"
            key = f"{project_id}/{digest[:2]}/{digest[2:4]}/{digest}"
            path = get_settings().media_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_image_bytes(index))
            content = ContentObject(
                project_id=project_id,
                sha256=digest,
                size_bytes=len(_image_bytes(index)),
                media_type="image/png",
                width=640,
                height=480,
                storage_key=key,
            )
            session.add(content)
            await session.flush()
            session.add(
                Media(
                    project_id=project_id,
                    content_object_id=content.id,
                    relative_path=f"camera/frame-{index:04d}.png",
                )
            )
        await session.commit()


async def _project(
    client: httpx.AsyncClient,
    token: str,
    *,
    members: tuple[str, ...] = (),
    consensus: bool = False,
    base: dict = DRAFT,
) -> dict:
    """Create, prepare, and activate a project; optionally with a consensus group."""
    created = await client.post("/api/v1/projects", headers=_auth(token), json=base)
    assert created.status_code == 201, created.text
    project = created.json()
    added = await client.post(
        f"/api/v1/projects/{project['id']}/classes",
        headers=_auth(token),
        json={"name": "pothole", "color": "#FF0000", "display_order": 0},
    )
    assert added.status_code == 201, added.text
    project["class_id"] = added.json()["id"]
    await _add_media(project["id"])

    project["member_ids"] = {}
    for username in members:
        joined = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": username, "role": "annotator"},
        )
        assert joined.status_code == 201, joined.text
        project["member_ids"][username] = joined.json()["user_id"]
    if consensus:
        saved = await client.put(
            f"/api/v1/projects/{project['id']}/annotation-policy",
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": [
                    *project["member_ids"].values(),
                    project["owner_id"],
                ],
                "required_consensus_annotations": 2,
                "required_consensus_reviewers": 1,
                "resolver": "two_stage_box_fusion",
                "parameters": {},
                "review_thresholds": {},
                "version": 1,
            },
        )
        assert saved.status_code == 200, saved.text

    prepared = await client.post(
        f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
        headers=_auth(token),
    )
    assert prepared.status_code == 201, prepared.text
    activated = await client.post(
        f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
    )
    assert activated.status_code == 200, activated.text
    return {**project, **activated.json()}


async def _start(
    client: httpx.AsyncClient, token: str, project_id: str, purpose: str
) -> dict:
    """Start the project's batch with the given purpose and return it."""
    listed = await client.get(
        f"/api/v1/projects/{project_id}/batches", headers=_auth(token)
    )
    batch = next(item for item in listed.json()["items"] if item["purpose"] == purpose)
    started = await client.post(
        f"/api/v1/projects/{project_id}/batches/{batch['id']}/start",
        headers=_auth(token),
    )
    assert started.status_code == 200, started.text
    return started.json()


async def _queue(
    client: httpx.AsyncClient, token: str, project_id: str, **params: str
) -> dict:
    """Return the caller's assignment queue."""
    response = await client.get(
        f"/api/v1/projects/{project_id}/assignments",
        headers=_auth(token),
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _open(
    client: httpx.AsyncClient, token: str, project_id: str, assignment_id: str
) -> httpx.Response:
    """Open one assignment."""
    return await client.get(
        f"/api/v1/projects/{project_id}/assignments/{assignment_id}",
        headers=_auth(token),
    )


async def _write(
    client: httpx.AsyncClient,
    token: str,
    project_id: str,
    assignment_id: str,
    action: str,
    version: int,
    objects: list[dict],
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Save a draft (``draft``) or submit (``submit``) an assignment."""
    url = f"/api/v1/projects/{project_id}/assignments/{assignment_id}/{action}"
    body = {"version": version, "objects": objects}
    send = client.put if action == "draft" else client.post
    return await send(url, headers={**_auth(token), **(headers or {})}, json=body)


def _box(class_id: str, x: float = 10.0) -> dict:
    """Return one valid rectangle object."""
    return {
        "id": f"box-{x}",
        "class_id": class_id,
        "geometry": {"type": "rectangle", "coordinates": [x, 10.0, 40.0, 30.0]},
        "attributes": {},
    }


async def _item_statuses(batch_id: str) -> list[str]:
    """Return the status of every item in a batch."""
    async with async_session_factory() as session:
        return list(
            await session.scalars(
                select(BatchItem.status).where(BatchItem.batch_id == batch_id)
            )
        )


async def test_two_consensus_annotators_work_the_same_image_independently(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")
    annie, bob = await _token("annie"), await _token("bob")

    async with _client() as client:
        project = await _project(
            client, token, members=("annie", "bob"), consensus=True
        )
        batch = await _start(client, token, project["id"], "initial_training")
        annie_queue = await _queue(client, annie, project["id"])
        bob_queue = await _queue(client, bob, project["id"])
        mine = annie_queue["items"][0]
        theirs = next(
            item for item in bob_queue["items"] if item["media_id"] == mine["media_id"]
        )

        opened_by_annie = await _open(client, annie, project["id"], mine["id"])
        opened_by_bob = await _open(client, bob, project["id"], theirs["id"])
        annie_draft = await _write(
            client,
            annie,
            project["id"],
            mine["id"],
            "draft",
            1,
            [_box(project["class_id"])],
        )
        bob_draft = await _write(
            client,
            bob,
            project["id"],
            theirs["id"],
            "draft",
            1,
            [_box(project["class_id"], 50)],
        )
        annie_submit = await _write(
            client,
            annie,
            project["id"],
            mine["id"],
            "submit",
            2,
            [_box(project["class_id"])],
        )
        after_one = await _item_statuses(batch["id"])
        bob_submit = await _write(
            client,
            bob,
            project["id"],
            theirs["id"],
            "submit",
            2,
            [_box(project["class_id"], 50)],
        )
        after_both = await _item_statuses(batch["id"])
        progress = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(token),
        )

    assert len(annie_queue["items"]) == 1
    assert len(bob_queue["items"]) == TRAINING_SIZE
    assert annie_queue["counts"] == {
        "pending": 1,
        "in_progress": 0,
        "submitted": 0,
    }
    assert all(set(item) == QUEUE_FIELDS for item in annie_queue["items"])
    assert mine["id"] != theirs["id"]
    assert opened_by_annie.status_code == opened_by_bob.status_code == 200
    assert opened_by_annie.json()["media"]["id"] == opened_by_bob.json()["media"]["id"]
    assert annie_draft.status_code == bob_draft.status_code == 200
    assert annie_draft.json()["status"] == "in_progress"
    assert annie_draft.json()["version"] == 2
    assert annie_submit.status_code == bob_submit.status_code == 200
    assert annie_submit.json()["image_resolved"] is False
    assert bob_submit.json()["image_resolved"] is False
    assert sorted(after_one) == ["pending", "pending"]
    assert sorted(after_both) == ["awaiting_resolution", "pending"]
    assert progress.json()["status"] == "annotating"
    assert progress.json()["awaiting_resolution_items"] == 1
    assert progress.json()["resolved_items"] == 0
    assert progress.json()["submitted_assignments"] == 2

    async with async_session_factory() as session:
        resolutions = await session.scalar(
            select(func.count()).select_from(ResolvedAnnotation)
        )
        events = list(await session.scalars(select(OutboxEvent)))
    assert resolutions == 0
    assert len(events) == 1
    assert events[0].event_type == "consensus.initial_evidence_ready.v1"
    assert [entry["submission_id"] for entry in events[0].payload["inputs"]]


async def test_stale_drafts_and_duplicate_submissions_are_refused(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    key = {"Idempotency-Key": "submit-once-0001"}

    async with _client() as client:
        project = await _project(client, token)
        await _start(client, token, project["id"], "test")
        assignment = (await _queue(client, token, project["id"]))["items"][0]
        objects = [_box(project["class_id"])]

        first = await _write(
            client, token, project["id"], assignment["id"], "draft", 1, objects
        )
        stale = await _write(
            client, token, project["id"], assignment["id"], "draft", 1, objects
        )
        submitted = await _write(
            client, token, project["id"], assignment["id"], "submit", 2, objects, key
        )
        replayed = await _write(
            client, token, project["id"], assignment["id"], "submit", 2, objects, key
        )
        duplicate = await _write(
            client, token, project["id"], assignment["id"], "submit", 3, objects
        )
        late_draft = await _write(
            client, token, project["id"], assignment["id"], "draft", 3, objects
        )

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert stale.json()["error"]["details"] == {"expected_version": 2}
    assert submitted.status_code == 200, submitted.text
    assert replayed.status_code == 200
    assert replayed.headers["idempotency-replayed"] == "true"
    assert replayed.json() == submitted.json()
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "assignment_already_submitted"
    assert late_draft.json()["error"]["code"] == "assignment_already_submitted"

    async with async_session_factory() as session:
        revisions = list(await session.scalars(select(AnnotationSubmission.revision)))
    assert revisions == [1]


async def test_candidate_review_is_scoped_private_and_immutable(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    owner = await _token("owner")
    annie, bob = await _token("annie"), await _token("bob")

    async with _client() as client:
        project = await _project(
            client, owner, members=("annie", "bob"), consensus=True
        )
        await _start(client, owner, project["id"], "test")
        annie_assignment = (await _queue(client, annie, project["id"]))["items"][0]
        bob_assignment = (await _queue(client, bob, project["id"]))["items"][0]
        await _write(
            client,
            annie,
            project["id"],
            annie_assignment["id"],
            "submit",
            1,
            [_box(project["class_id"])],
        )
        await _write(
            client,
            bob,
            project["id"],
            bob_assignment["id"],
            "submit",
            1,
            [_box(project["class_id"], 20)],
        )

        async with async_session_factory() as session:
            event = await session.scalar(select(OutboxEvent))
            source_input = await resolution_foundation.create_initial_input(
                session, event.id
            )
            (
                work_item,
                assignments,
            ) = await resolution_foundation.create_review_work_item(
                session,
                source_input,
                candidate_key="candidate-0",
                candidate_ordinal=0,
                scope="candidate",
                candidate_context={
                    "class_id": project["class_id"],
                    "box": [10, 10, 40, 30],
                },
            )
            review_assignment_id = assignments[0].id
            source_input_id = source_input.id
            work_item_id = work_item.id
            await session.commit()

        queue = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments",
            headers=_auth(owner),
        )
        detail = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments/{review_assignment_id}",
            headers=_auth(owner),
        )
        forbidden = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments/{review_assignment_id}",
            headers=_auth(annie),
        )
        drafted = await client.put(
            f"/api/v1/projects/{project['id']}/review-assignments/{review_assignment_id}/draft",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"verdict": "accept"}},
        )
        stale = await client.put(
            f"/api/v1/projects/{project['id']}/review-assignments/{review_assignment_id}/draft",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"verdict": "reject"}},
        )
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review_assignment_id}/submit",
            headers={**_auth(owner), "Idempotency-Key": "candidate-review-submit-1"},
            json={"version": 2, "evidence": {"verdict": "accept"}},
        )

    assert queue.status_code == 200, queue.text
    assert [item["id"] for item in queue.json()["items"]] == [review_assignment_id]
    assert detail.status_code == 200, detail.text
    assert detail.json()["candidate_context"] == {
        "class_id": project["class_id"],
        "box": [10, 10, 40, 30],
    }
    assert "source_inputs" not in detail.text
    assert forbidden.status_code == 403
    assert drafted.json()["version"] == 2
    assert stale.json()["error"]["code"] == "version_conflict"
    assert submitted.status_code == 200, submitted.text

    async with async_session_factory() as session:
        evidence = await session.scalar(select(ReviewSubmission))
        stored_work = await session.get(ResolutionWorkItem, work_item_id)
    assert evidence.source_input_id == source_input_id
    assert evidence.work_item_id == work_item_id
    assert evidence.evidence == {"verdict": "accept"}
    assert stored_work.status == "review_ready"


async def test_only_the_assignee_reaches_an_assignment(database: None) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    await _create_user("root", administrator=True)
    await _create_user("viv")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(
            client, token, members=("annie", "bob"), consensus=True
        )
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": "viv", "role": "viewer"},
        )
        await _start(client, token, project["id"], "test")
        annie = await _token("annie")
        target = (await _queue(client, annie, project["id"]))["items"][0]["id"]

        refused = [
            await _open(client, await _token(username), project["id"], target)
            for username in ("bob", "owner", "root")
        ]
        written = await _write(
            client, await _token("bob"), project["id"], target, "draft", 1, []
        )
        viewer_queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments",
            headers=_auth(await _token("viv")),
        )

    assert [response.status_code for response in refused] == [403, 403, 403]
    assert {response.json()["error"]["code"] for response in refused} == {
        "assignment_not_owned"
    }
    assert written.status_code == 403
    assert viewer_queue.status_code == 403


async def test_single_mode_submissions_resolve_images_and_unlock_acquisition(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        started = [
            await _start(client, token, project["id"], purpose)
            for purpose in ("test", "validation", "initial_training")
        ]
        queue = await _queue(client, token, project["id"])
        results = [
            await _write(client, token, project["id"], item["id"], "submit", 1, [])
            for item in queue["items"]
        ]
        batches = await client.get(
            f"/api/v1/projects/{project['id']}/batches", headers=_auth(token)
        )

    purposes = [item["batch_purpose"] for item in queue["items"]]
    assert sorted(purposes) == [
        "initial_training",
        "initial_training",
        "test",
        "validation",
    ]
    assert len([purpose for purpose, _ in groupby(purposes)]) == 3
    assert [batch["purpose"] for batch in started] == [
        "test",
        "validation",
        "initial_training",
    ]
    assert all(result.status_code == 200 for result in results)
    assert all(result.json()["image_resolved"] for result in results)
    assert {batch["status"] for batch in batches.json()["items"]} == {"resolved"}

    async with async_session_factory() as session:
        resolutions = list(await session.scalars(select(ResolvedAnnotation)))
        stored = await session.get(Project, project["id"])
        ready = await datasets.first_acquisition_ready(session, stored)

    assert len(resolutions) == len(queue["items"])
    assert {resolution.source for resolution in resolutions} == {"single_submission"}
    assert all(resolution.submission_id for resolution in resolutions)
    assert ready is True


async def test_a_submission_must_meet_the_task_and_geometry_rules(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        await _start(client, token, project["id"], "test")
        assignment = (await _queue(client, token, project["id"]))["items"][0]
        outside = _box(project["class_id"], 620)
        unknown = {**_box(project["class_id"]), "class_id": "not-a-class"}
        refused = await _write(
            client,
            token,
            project["id"],
            assignment["id"],
            "submit",
            1,
            [outside, unknown],
        )
        infinite = await client.put(
            f"/api/v1/projects/{project['id']}/assignments/{assignment['id']}/draft",
            headers={**_auth(token), "Content-Type": "application/json"},
            content=(
                '{"version": 1, "objects": [{"id": "x", "class_id": "c", '
                '"geometry": {"type": "rectangle", '
                '"coordinates": [1, 1, Infinity, 1]}, "attributes": {}}]}'
            ),
        )
        draft = await _write(
            client, token, project["id"], assignment["id"], "draft", 1, [outside]
        )

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "invalid_document"
    assert refused.json()["error"]["details"]["errors"] == [
        {"object_id": outside["id"], "code": "out_of_bounds"},
        {"object_id": unknown["id"], "code": "unknown_class"},
    ]
    assert infinite.status_code == 422
    assert draft.status_code == 200


async def test_the_signed_image_link_serves_bytes_without_a_bearer(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        await _start(client, token, project["id"], "test")
        assignment = (await _queue(client, token, project["id"]))["items"][0]
        opened = (await _open(client, token, project["id"], assignment["id"])).json()
        url = opened["media"]["image_url"]
        served = await client.get(url)
        tampered = await client.get(url.replace("signature=", "signature=0"))

    index = int(opened["media"]["relative_path"][-8:-4])
    assert served.status_code == 200
    assert served.content == _image_bytes(index)
    assert served.headers["content-type"] == "image/png"
    assert tampered.status_code == 403
    assert tampered.json()["error"]["code"] == "invalid_media_url"


async def test_reopen_gives_submitted_work_back_as_a_new_revision(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")
    annie, bob = await _token("annie"), await _token("bob")

    async with _client() as client:
        project = await _project(
            client, token, members=("annie", "bob"), consensus=True
        )
        batch = await _start(client, token, project["id"], "test")
        mine = (await _queue(client, annie, project["id"]))["items"][0]
        theirs = (await _queue(client, bob, project["id"]))["items"][0]
        first = [_box(project["class_id"])]
        await _write(client, annie, project["id"], mine["id"], "submit", 1, first)
        await _write(client, bob, project["id"], theirs["id"], "submit", 1, first)
        before = await _item_statuses(batch["id"])

        reopened = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/{mine['id']}/reopen",
            headers=_auth(token),
        )
        after = await _item_statuses(batch["id"])
        stale_tab = await _write(
            client, annie, project["id"], mine["id"], "draft", 2, first
        )
        opened = (await _open(client, annie, project["id"], mine["id"])).json()
        corrected = await _write(
            client,
            annie,
            project["id"],
            mine["id"],
            "submit",
            3,
            [_box(project["class_id"], 90)],
        )

    assert before == ["awaiting_resolution"]
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"
    assert after == ["pending"]
    assert stale_tab.json()["error"]["code"] == "version_conflict"
    assert opened["objects"] == first
    assert opened["revision"] == 1
    assert corrected.json()["revision"] == 2
    assert await _item_statuses(batch["id"]) == ["awaiting_resolution"]
    async with async_session_factory() as session:
        item = await session.scalar(
            select(BatchItem).where(BatchItem.batch_id == batch["id"])
        )
        events = list(
            await session.scalars(select(OutboxEvent).order_by(OutboxEvent.generation))
        )
        with pytest.raises(ApiError) as stale_event:
            await resolution_foundation.create_initial_input(session, events[0].id)
    assert item.initial_evidence_generation == 2
    assert [event.generation for event in events] == [1, 2]
    assert stale_event.value.code == "stale_evidence_generation"


async def test_a_resolved_single_image_cannot_be_reopened(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        await _start(client, token, project["id"], "test")
        assignment = (await _queue(client, token, project["id"]))["items"][0]
        await _write(client, token, project["id"], assignment["id"], "submit", 1, [])
        reopened = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/{assignment['id']}/reopen",
            headers=_auth(token),
        )

    assert reopened.status_code == 409
    assert reopened.json()["error"]["code"] == "item_closed"


async def test_reassign_moves_work_without_sharing_it(database: None) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    await _create_user("carl")
    await _create_user("viv")
    token = await _token("owner")
    annie = await _token("annie")

    async with _client() as client:
        project = await _project(
            client, token, members=("annie", "bob", "carl"), consensus=True
        )
        viv = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(token),
            json={"username": "viv", "role": "viewer"},
        )
        await _start(client, token, project["id"], "test")
        mine = (await _queue(client, annie, project["id"]))["items"][0]
        bobs = (await _queue(client, await _token("bob"), project["id"]))["items"][0]
        await _write(
            client,
            annie,
            project["id"],
            mine["id"],
            "draft",
            1,
            [_box(project["class_id"])],
        )

        def reassign(assignment_id: str, annotator_id: str):
            return client.post(
                f"/api/v1/projects/{project['id']}/assignments/{assignment_id}/reassign",
                headers=_auth(token),
                json={"annotator_id": annotator_id},
            )

        moved = await reassign(mine["id"], project["member_ids"]["carl"])
        twice = await reassign(bobs["id"], project["member_ids"]["carl"])
        to_viewer = await reassign(bobs["id"], viv.json()["user_id"])
        annie_after = await _queue(client, annie, project["id"])
        annie_save = await _write(
            client, annie, project["id"], mine["id"], "draft", 2, []
        )
        carl_opened = (
            await _open(client, await _token("carl"), project["id"], moved.json()["id"])
        ).json()

    assert moved.status_code == 201, moved.text
    assert moved.json()["annotator_id"] == project["member_ids"]["carl"]
    assert moved.json()["status"] == "pending"
    assert twice.json()["error"]["code"] == "already_assigned"
    assert to_viewer.status_code == 422
    assert to_viewer.json()["error"]["code"] == "invalid_assignee"
    assert annie_after["items"] == []
    assert annie_save.json()["error"]["code"] == "assignment_not_active"
    assert carl_opened["objects"] == []

    async with async_session_factory() as session:
        kept = await session.get(AnnotationAssignment, mine["id"])
        audited = await session.scalar(
            select(func.count())
            .select_from(AuditEntry)
            .where(AuditEntry.action == "assignment.reassigned")
        )
    assert kept.status == "reassigned"
    assert kept.draft == [_box(project["class_id"])]
    assert audited == 1


async def test_cancelling_a_training_image_returns_it_to_the_pool(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        training = await _start(client, token, project["id"], "initial_training")
        test = await _start(client, token, project["id"], "test")

        async def items(batch_id: str) -> list[dict]:
            listed = await client.get(
                f"/api/v1/projects/{project['id']}/batches/{batch_id}/assignments",
                headers=_auth(token),
            )
            assert listed.status_code == 200, listed.text
            return listed.json()["items"]

        cancelled_item = (await items(training["id"]))[0]
        cancelled = await client.post(
            f"/api/v1/projects/{project['id']}/batch-items/"
            f"{cancelled_item['batch_item_id']}/cancel",
            headers=_auth(token),
        )
        held_out = await client.post(
            f"/api/v1/projects/{project['id']}/batch-items/"
            f"{(await items(test['id']))[0]['batch_item_id']}/cancel",
            headers=_auth(token),
        )
        after = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{training['id']}",
            headers=_auth(token),
        )
        remaining = [
            item
            for item in (await _queue(client, token, project["id"]))["items"]
            if item["batch_purpose"] == "initial_training"
        ]
        for item in remaining:
            await _write(client, token, project["id"], item["id"], "submit", 1, [])
        finished = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{training['id']}",
            headers=_auth(token),
        )
        listed = await items(training["id"])

    assert cancelled.status_code == 204, cancelled.text
    assert held_out.status_code == 409
    assert held_out.json()["error"]["code"] == "cancel_not_allowed"
    assert after.json()["total_items"] == TRAINING_SIZE - 1
    assert after.json()["cancelled_items"] == 1
    assert len(remaining) == TRAINING_SIZE - 1
    assert finished.json()["status"] == "resolved"
    assert {"cancelled", "submitted"} == {item["status"] for item in listed}
    assert "objects" not in listed[0]

    async with async_session_factory() as session:
        stored = await session.get(Project, project["id"])
        pool = await datasets.eligible_training_pool(session, stored)
    assert cancelled_item["media_id"] in pool


async def test_annotators_cannot_use_manager_actions(database: None) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")
    annie = await _token("annie")

    async with _client() as client:
        project = await _project(
            client, token, members=("annie", "bob"), consensus=True
        )
        batch = await _start(client, token, project["id"], "initial_training")
        mine = (await _queue(client, annie, project["id"]))["items"][0]
        base = f"/api/v1/projects/{project['id']}"
        responses = [
            await client.get(
                f"{base}/batches/{batch['id']}/assignments", headers=_auth(annie)
            ),
            await client.post(
                f"{base}/assignments/{mine['id']}/reopen", headers=_auth(annie)
            ),
            await client.post(
                f"{base}/assignments/{mine['id']}/reassign",
                headers=_auth(annie),
                json={"annotator_id": project["member_ids"]["bob"]},
            ),
            await client.post(
                f"{base}/batch-items/{mine['id']}/cancel", headers=_auth(annie)
            ),
        ]

    assert [response.status_code for response in responses] == [403] * 4


async def test_project_deletion_removes_submissions_and_resolutions(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _project(client, token)
        await _start(client, token, project["id"], "test")
        assignment = (await _queue(client, token, project["id"]))["items"][0]
        await _write(client, token, project["id"], assignment["id"], "submit", 1, [])
        deleted = await client.delete(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )

    assert deleted.status_code == 204, deleted.text
    async with async_session_factory() as session:
        for model in (AnnotationSubmission, ResolvedAnnotation, AnnotationAssignment):
            remaining = await session.scalar(select(func.count()).select_from(model))
            assert remaining == 0


async def test_the_acquisition_strategy_changes_only_on_split_projects(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        created = await client.post(
            "/api/v1/projects", headers=_auth(token), json=DRAFT
        )
        project = created.json()
        url = f"/api/v1/projects/{project['id']}"
        learning = await client.patch(
            url,
            headers=_auth(token),
            json={"acquisition_strategy": "active_learning", "version": 1},
        )
        stale = await client.patch(
            url,
            headers=_auth(token),
            json={"acquisition_strategy": "random", "version": 1},
        )
        static = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={
                "name": "Static",
                "description": None,
                "task_type": "detection",
                "dataset_layout": "single_batch",
            },
        )
        refused = await client.patch(
            f"/api/v1/projects/{static.json()['id']}",
            headers=_auth(token),
            json={"acquisition_strategy": "active_learning", "version": 1},
        )
        reread = await client.get(url, headers=_auth(token))

    assert learning.status_code == 200, learning.text
    assert learning.json()["acquisition_strategy"] == "active_learning"
    assert learning.json()["version"] == 2
    assert stale.json()["error"]["code"] == "version_conflict"
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "acquisition_strategy_not_allowed"
    assert reread.json()["acquisition_strategy"] == "active_learning"

    async with async_session_factory() as session:
        entry = await session.scalar(
            select(AuditEntry).where(
                AuditEntry.action == "project.acquisition_strategy_changed"
            )
        )
    assert entry.before == {"acquisition_strategy": "random"}
    assert entry.after == {"acquisition_strategy": "active_learning"}
