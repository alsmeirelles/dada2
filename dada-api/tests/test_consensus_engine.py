"""Durable consensus runs and manager resolution routes, driven by the fake pipeline."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select

from dada_api.consensus import health, protocol
from dada_api.consensus.fake import ScriptedPipeline
from dada_api.core.config import get_settings
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
from dada_api.models.consensus import (
    OutboxEvent,
    ResolutionInput,
    ResolutionWorkItem,
    ReviewAssignment,
    ReviewSubmission,
)
from dada_api.models.dataset import DatasetSplit
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.label_import import AnnotationImport
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.resolution import (
    Adjudication,
    CalibrationSnapshot,
    PerformanceObservation,
    ResolutionLease,
    ResolutionObjectEvidence,
    ResolutionProposal,
    ResolutionRun,
    ResolverQuarantine,
)
from dada_api.models.user import User
from dada_api.services import (
    annotation_documents,
    performance,
    resolution_runs,
    resolver_quarantines,
)
from dada_api.services.resolver_quarantines import QuarantineError
from dada_api.workers.consensus import execute

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase6-engine-password"
DRAFT = {
    "name": "Pets",
    "description": None,
    "task_type": "detection",
    "test_set_size": 1,
    "validation_set_size": 1,
    "initial_training_size": 2,
    "iteration_batch_size": 2,
}
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
PIPELINES = {
    "classification": "statistical_class_consensus",
    "detection": "two_stage_detection_consensus",
    "segmentation": "two_stage_segmentation_consensus",
}


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def _reset_database() -> None:
    """Remove every record these tests create."""
    async with async_session_factory() as session:
        for model in (
            IdempotencyRecord,
            ResolverQuarantine,
            ResolvedAnnotation,
            AnnotationSubmission,
            AnnotationAssignment,
            AnnotationImport,
            BatchItem,
            AnnotationBatchAnnotator,
            AnnotationBatch,
            DatasetSplit,
            AuditEntry,
            AnnotationPolicyAnnotator,
            AnnotationPolicyDefault,
            ProjectClass,
            Media,
            ContentObject,
            ProjectMember,
            Project,
            User,
        ):
            await session.execute(delete(model))
        await session.commit()


@pytest.fixture
async def database() -> AsyncIterator[None]:
    """Provide an empty database around each test."""
    await _reset_database()
    yield
    await _reset_database()


async def _create_user(username: str) -> str:
    """Persist a user with the shared test password and return its ID."""
    async with async_session_factory() as session:
        user = User(
            username=username,
            display_name=username.title(),
            password_hash=hash_password(PASSWORD),
            is_administrator=False,
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
            "/api/v1/auth/token", json={"username": username, "password": PASSWORD}
        )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


async def _add_media(project_id: str, count: int = 6) -> None:
    """Persist media rows and their bytes directly."""
    async with async_session_factory() as session:
        for index in range(count):
            digest = f"{index + 100:064x}"
            key = f"{project_id}/{digest[:2]}/{digest[2:4]}/{digest}"
            path = get_settings().media_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"pixels" * 8)
            content = ContentObject(
                project_id=project_id,
                sha256=digest,
                size_bytes=48,
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
                    relative_path=f"pets/{index:04d}.png",
                )
            )
        await session.commit()


def _box(class_id: str, x: float = 10.0) -> dict:
    """Return one valid rectangle object."""
    return {
        "id": f"box-{x}",
        "class_id": class_id,
        "geometry": {"type": "rectangle", "coordinates": [x, 10.0, 40.0, 30.0]},
        "attributes": {},
    }


async def _consensus_project(
    client: httpx.AsyncClient, task_type: str = "detection"
) -> dict:
    """Create an active consensus project whose pool is annie, bob, owner."""
    owner = await _token("owner")
    created = await client.post(
        "/api/v1/projects",
        headers=_auth(owner),
        json={**DRAFT, "task_type": task_type},
    )
    project = created.json()
    project["class_ids"] = []
    for order, name in enumerate(("cat", "dog")):
        added = await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(owner),
            json={"name": name, "color": "#FF0000", "display_order": order},
        )
        project["class_ids"].append(added.json()["id"])
    project["class_id"] = project["class_ids"][0]
    await _add_media(project["id"])
    pool = []
    for username in ("annie", "bob"):
        joined = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner),
            json={"username": username, "role": "annotator"},
        )
        pool.append(joined.json()["user_id"])
    saved = await client.put(
        f"/api/v1/projects/{project['id']}/annotation-policy",
        headers=_auth(owner),
        json={
            "mode": "consensus",
            "annotator_ids": [*pool, project["owner_id"]],
            "required_consensus_annotations": 2,
            "required_consensus_reviewers": 1,
            "resolver": PIPELINES[task_type],
            "version": 1,
        },
    )
    assert saved.status_code == 200, saved.text
    prepared = await client.post(
        f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
        headers=_auth(owner),
    )
    assert prepared.status_code == 201, prepared.text
    activated = await client.post(
        f"/api/v1/projects/{project['id']}/activate", headers=_auth(owner)
    )
    assert activated.status_code == 200, activated.text
    return project


async def _start(client: httpx.AsyncClient, project_id: str, purpose: str) -> dict:
    """Start one batch of the project and return it."""
    owner = await _token("owner")
    listed = await client.get(
        f"/api/v1/projects/{project_id}/batches", headers=_auth(owner)
    )
    batch = next(item for item in listed.json()["items"] if item["purpose"] == purpose)
    started = await client.post(
        f"/api/v1/projects/{project_id}/batches/{batch['id']}/start",
        headers=_auth(owner),
    )
    assert started.status_code == 200, started.text
    return started.json()


async def _submit_all(client: httpx.AsyncClient, project: dict) -> None:
    """Have every annotator submit every image in their queue."""
    for username in ("annie", "bob", "owner"):
        token = await _token(username)
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments", headers=_auth(token)
        )
        for entry in queue.json()["items"]:
            submitted = await client.post(
                f"/api/v1/projects/{project['id']}/assignments/{entry['id']}/submit",
                headers=_auth(token),
                json={
                    "version": entry["version"],
                    "objects": [_box(project["class_id"])],
                },
            )
            assert submitted.status_code == 200, submitted.text


async def _ready_test_item(client: httpx.AsyncClient) -> tuple[dict, dict]:
    """Return a project whose one-image test batch has its readiness event."""
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    project = await _consensus_project(client)
    batch = await _start(client, project["id"], "test")
    await _submit_all(client, project)
    return project, batch


class Broker:
    """A broker stand-in that records every command the relay sends."""

    def __init__(self) -> None:
        self.commands: list[protocol.Command] = []

    def __call__(self, command: protocol.Command, run: ResolutionRun) -> None:
        """Record one dispatched command."""
        self.commands.append(command)


async def _relay(broker: Broker, now: datetime = NOW) -> dict:
    """Run one relay pass."""
    async with async_session_factory() as session:
        return await resolution_runs.relay_once(session, broker, now)


async def _execute(command: protocol.Command, fake: ScriptedPipeline) -> None:
    """Execute one attempt with the fake pipeline."""
    await execute(command, async_session_factory, run_pipeline=fake)


async def _rows(model: type, *conditions) -> list:
    """Return every row of a model matching the conditions."""
    async with async_session_factory() as session:
        return list(await session.scalars(select(model).where(*conditions)))


async def test_first_round_acceptance_creates_one_current_resolution(
    database: None,
) -> None:
    async with _client() as client:
        project, batch = await _ready_test_item(client)
    submissions_before = {
        row.id: row.content_hash for row in await _rows(AnnotationSubmission)
    }
    broker = Broker()

    report = await _relay(broker)
    assert report == {"created": 1, "recovered": 0, "dispatched": 1}
    assert broker.commands[0].attempt == 1
    await _execute(broker.commands[0], ScriptedPipeline("accept"))

    [run] = await _rows(ResolutionRun)
    [resolution] = await _rows(ResolvedAnnotation)
    [item] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
    [stored_batch] = await _rows(AnnotationBatch, AnnotationBatch.id == batch["id"])
    assert run.status == "succeeded"
    assert run.pipeline == "two_stage_detection_consensus"
    assert run.effective_limits["hard_seconds"] == 300
    assert resolution.source == "automatic_consensus"
    assert resolution.accepted_by is None
    assert resolution.version == 1
    assert [entry["id"] for entry in resolution.objects] == ["o1"]
    assert item.status == "resolved"
    assert stored_batch.status == "resolved"
    assert len(await _rows(ResolutionProposal)) == 1
    events = {
        row.event_type
        for row in await _rows(
            OutboxEvent, OutboxEvent.aggregate_type == "resolution_run"
        )
    }
    assert events == {"resolution.started", "resolution.completed"}
    assert {
        row.id: row.content_hash for row in await _rows(AnnotationSubmission)
    } == submissions_before
    system_actions = {
        row.action
        for row in await _rows(AuditEntry, AuditEntry.actor_user_id.is_(None))
    }
    assert system_actions == {"resolution.run_queued", "resolution.accepted"}
    assert await _relay(broker) == {"created": 0, "recovered": 0, "dispatched": 0}

    async with _client() as client:
        annie = await _token("annie")
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments", headers=_auth(annie)
        )
        detail = await client.get(
            f"/api/v1/projects/{project['id']}/assignments/"
            f"{queue.json()['items'][0]['id']}",
            headers=_auth(annie),
        )
    assert detail.json()["resolution"] == {
        "version": 1,
        "source": "automatic_consensus",
        "objects": resolution.objects,
    }
    assert "annotator" not in detail.text


async def test_duplicate_stale_and_concurrent_results_accept_once(
    database: None,
) -> None:
    async with _client() as client:
        await _ready_test_item(client)
    broker = Broker()
    await _relay(broker)
    command = broker.commands[0]

    async with async_session_factory() as session:
        resolver_input = await resolution_runs.start_attempt(session, command, NOW)
    output = ScriptedPipeline("accept")(resolver_input)
    result = protocol.Result(
        run_id=command.run_id,
        attempt=command.attempt,
        configuration_fingerprint=command.configuration_fingerprint,
        input_fingerprint=command.input_fingerprint,
        outcome="proposal",
        output=output,
        output_checksum=protocol.fingerprint(output.model_dump(mode="json")),
        started_at=NOW,
        finished_at=NOW,
    )
    stale = result.model_copy(update={"attempt": command.attempt + 1})

    async def ingest(value: protocol.Result) -> None:
        async with async_session_factory() as session:
            await resolution_runs.ingest(session, value, NOW)

    await ingest(stale)
    assert await _rows(ResolvedAnnotation) == []
    await asyncio.gather(ingest(result), ingest(result))
    await ingest(result)

    [resolution] = await _rows(ResolvedAnnotation)
    assert len(await _rows(ResolutionProposal)) == 1
    observations = await _rows(PerformanceObservation)
    keys = [row.observation_key for row in observations]
    assert observations
    assert {row.resolution_id for row in observations} == {resolution.id}
    assert len(keys) == len(set(keys))
    async with async_session_factory() as session:
        assert await resolution_runs.start_attempt(session, command, NOW) is None


async def test_low_agreement_reaches_a_reviewer_then_a_second_round(
    database: None,
) -> None:
    async with _client() as client:
        project, _ = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("review"))

        [work_item] = await _rows(ResolutionWorkItem)
        [review] = await _rows(ReviewAssignment)
        [item] = await _rows(BatchItem, BatchItem.id == work_item.batch_item_id)
        assert work_item.status == "pending_review"
        assert work_item.reason == "class_tie"
        assert work_item.candidate_context == {"region": [0.0, 0.0, 10.0, 10.0]}
        assert item.status == "in_review"
        assert review.reviewer_id == project["owner_id"]

        owner = await _token("owner")
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"decision": "no_object"}},
        )
        assert submitted.status_code == 200, submitted.text

    review_input = (await _rows(ResolutionInput, ResolutionInput.run_number == 2))[0]
    assert review_input.source_inputs[-1]["kind"] == "review"
    assert review_input.candidate_mapping["candidates"][0]["key"] == "c-fake-0"
    await _relay(broker)
    second = broker.commands[-1]
    fake = ScriptedPipeline("review")
    await _execute(second, fake)

    assert fake.calls[0].sources[-1].kind == "review"
    assert fake.calls[0].candidates[0]["key"] == "c-fake-0"
    runs = sorted(await _rows(ResolutionRun), key=lambda run: run.sequence)
    assert [(run.trigger, run.status) for run in runs] == [
        ("initial", "review_required"),
        ("review", "succeeded"),
    ]
    [resolution] = await _rows(ResolvedAnnotation)
    assert resolution.version == 1
    [closed] = await _rows(ResolutionWorkItem)
    assert closed.status == "resolved"


async def test_a_second_failure_goes_to_an_expert(database: None) -> None:
    async with _client() as client:
        project, batch = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("review"))
        [review] = await _rows(ReviewAssignment)
        owner = await _token("owner")
        await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"decision": "no_object"}},
        )
    await _relay(broker)
    await _execute(broker.commands[-1], ScriptedPipeline("disagree"))

    [work_item] = await _rows(ResolutionWorkItem)
    [item] = await _rows(BatchItem, BatchItem.id == work_item.batch_item_id)
    [stored_batch] = await _rows(AnnotationBatch, AnnotationBatch.id == batch["id"])
    assert work_item.status == "review_required"
    assert len(await _rows(ReviewAssignment)) == 1
    assert item.status == "review_required"
    assert stored_batch.status == "review_required"
    assert await _rows(ResolvedAnnotation) == []


@pytest.mark.parametrize(
    ("outcome", "failure_code", "reason"),
    [
        ("invalid", "resolver_output_invalid", "resolver_output_invalid"),
        ("timeout", "resource_limit", "worker_failed"),
        ("unavailable", "resolver_unavailable", "resolver_unavailable"),
        ("error", "resolver_output_invalid", "resolver_output_invalid"),
    ],
)
async def test_permanent_failures_hand_the_image_to_an_expert(
    database: None, outcome: str, failure_code: str, reason: str
) -> None:
    async with _client() as client:
        await _ready_test_item(client)
    broker = Broker()
    await _relay(broker)
    await _execute(broker.commands[0], ScriptedPipeline(outcome))

    [run] = await _rows(ResolutionRun)
    [work_item] = await _rows(ResolutionWorkItem)
    [item] = await _rows(BatchItem, BatchItem.id == run.batch_item_id)
    assert (run.status, run.failure_code) == ("failed", failure_code)
    assert (work_item.scope, work_item.candidate_key) == ("image", "image")
    assert (work_item.status, work_item.reason) == ("review_required", reason)
    assert await _rows(ReviewAssignment) == []
    assert item.status == "review_required"
    assert await _rows(ResolvedAnnotation) == []


async def test_a_vanished_worker_is_retried_with_backoff_then_fails(
    database: None,
) -> None:
    async with _client() as client:
        await _ready_test_item(client)
    broker = Broker()
    await _relay(broker)
    async with async_session_factory() as session:
        assert await resolution_runs.start_attempt(session, broker.commands[0], NOW)

    after_timeout = NOW + timedelta(seconds=300) + timedelta(seconds=61)
    assert (await _relay(broker, after_timeout))["recovered"] == 1
    assert len(broker.commands) == 1
    [run] = await _rows(ResolutionRun)
    assert run.status == "queued"
    assert run.next_attempt_at == after_timeout + timedelta(minutes=1)

    second_try = after_timeout + timedelta(minutes=1)
    assert (await _relay(broker, second_try))["dispatched"] == 1
    assert broker.commands[-1].attempt == 2
    async with async_session_factory() as session:
        assert (
            await resolution_runs.start_attempt(session, broker.commands[0], second_try)
            is None
        )

    third_try = second_try + timedelta(seconds=361) + timedelta(minutes=5)
    await _relay(broker, third_try)
    await _relay(broker, third_try + timedelta(minutes=5))
    assert broker.commands[-1].attempt == 3
    await _relay(broker, third_try + timedelta(minutes=12))

    [run] = await _rows(ResolutionRun)
    assert (run.status, run.failure_code, run.attempt) == ("failed", "worker_failed", 3)
    [work_item] = await _rows(ResolutionWorkItem)
    assert work_item.reason == "worker_failed"


async def test_an_obsolete_generation_never_becomes_a_run(database: None) -> None:
    async with _client() as client:
        project, _ = await _ready_test_item(client)
        owner = await _token("owner")
        annie = await _token("annie")
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments",
            headers=_auth(annie),
            params={"state": "submitted"},
        )
        reopened = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/"
            f"{queue.json()['items'][0]['id']}/reopen",
            headers=_auth(owner),
        )
        assert reopened.status_code == 200, reopened.text

    broker = Broker()
    assert (await _relay(broker))["created"] == 0
    assert await _rows(ResolutionRun) == []
    [event] = await _rows(OutboxEvent)
    assert event.published_at == NOW


async def test_reopening_during_review_retires_the_old_generation(
    database: None,
) -> None:
    async with _client() as client:
        project, _ = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("review"))
        owner = await _token("owner")
        annie = await _token("annie")
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments",
            headers=_auth(annie),
            params={"state": "submitted"},
        )
        reopened = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/"
            f"{queue.json()['items'][0]['id']}/reopen",
            headers=_auth(owner),
        )
        assert reopened.status_code == 200, reopened.text
        reviews = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments",
            headers=_auth(owner),
        )

    [work_item] = await _rows(ResolutionWorkItem)
    [review] = await _rows(ReviewAssignment)
    assert work_item.status == "cancelled"
    assert review.status == "cancelled"
    assert reviews.json()["items"] == []


async def test_the_relay_respects_the_per_project_cap(database: None) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client)
        for purpose in ("test", "validation", "initial_training"):
            await _start(client, project["id"], purpose)
        await _submit_all(client, project)

    broker = Broker()
    report = await _relay(broker)
    assert report["created"] == 4
    assert report["dispatched"] == 2
    await _execute(broker.commands[0], ScriptedPipeline("accept"))
    assert (await _relay(broker))["dispatched"] == 1


async def test_repeated_invalid_output_quarantines_the_pipeline(
    database: None,
) -> None:
    async with _client() as client:
        await _ready_test_item(client)
    broker = Broker()
    await _relay(broker)
    [run] = await _rows(ResolutionRun)
    async with async_session_factory() as session:
        for sequence in range(2, 6):
            session.add(
                ResolutionRun(
                    project_id=run.project_id,
                    batch_item_id=run.batch_item_id,
                    resolution_input_id=run.resolution_input_id,
                    sequence=sequence,
                    trigger="manual_retry",
                    pipeline=run.pipeline,
                    pipeline_version=run.pipeline_version,
                    configuration=run.configuration,
                    configuration_fingerprint=f"earlier-{sequence}",
                    input_fingerprint=run.input_fingerprint,
                    dependency_versions={},
                    queue=run.queue,
                    status="failed",
                    attempt=1,
                    effective_limits=run.effective_limits,
                    failure_code="resolver_output_invalid",
                    finished_at=datetime.now(UTC) - timedelta(minutes=2),
                )
            )
        await session.commit()

    await execute(
        broker.commands[0],
        async_session_factory,
        run_pipeline=ScriptedPipeline("invalid"),
    )
    [quarantine] = await _rows(ResolverQuarantine)
    assert (quarantine.identifier, quarantine.version) == (
        "two_stage_detection_consensus",
        "1.0.0",
    )
    async with _client() as client:
        capabilities = (await client.get("/api/v1/capabilities")).json()
    assert (
        capabilities["consensus_pipelines"]["detection"]["unavailable_reason"]
        == "quarantined"
    )


async def test_operators_release_a_quarantine_only_after_its_health_fixture(
    database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_user("annie")
    async with async_session_factory() as session:
        session.add(
            User(
                username="ops",
                display_name="Ops",
                password_hash=hash_password(PASSWORD),
                is_administrator=True,
                is_active=True,
                version=1,
            )
        )
        await session.commit()
    key = "two_stage_detection_consensus@1.0.0"
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        await resolver_quarantines.quarantine(session, key, "Faulty boxes.", "ops", now)
    async with _client() as client:
        blocked = (await client.get("/api/v1/capabilities")).json()

    refusals = []
    for key_given, username, healthy in (
        ("two_stage_detection_consensus@0.9.0", "ops", True),
        (key, "annie", True),
        (key, "ops", False),
    ):
        monkeypatch.setattr(health, "passes", lambda task_type, ok=healthy: ok)
        async with async_session_factory() as session:
            with pytest.raises(QuarantineError) as refused:
                await resolver_quarantines.release(
                    session, key_given, "Fixed.", username, now
                )
        refusals.append(str(refused.value))
    monkeypatch.undo()
    async with async_session_factory() as session:
        await resolver_quarantines.release(session, key, "Fixed.", "ops", now)
    async with _client() as client:
        restored = (await client.get("/api/v1/capabilities")).json()

    assert blocked["consensus_pipelines"]["detection"]["unavailable_reason"] == (
        "quarantined"
    )
    assert refusals == [
        "No installed pipeline is 'two_stage_detection_consensus@0.9.0'.",
        "'annie' is not an active administrator.",
        f"The health fixture of {key!r} failed.",
    ]
    assert restored["consensus_pipelines"]["detection"]["unavailable_reason"] is None
    [quarantine] = await _rows(ResolverQuarantine)
    assert quarantine.release_reason == "Fixed."
    assert quarantine.released_by is not None
    actions = [entry.action for entry in await _rows(AuditEntry)]
    assert actions == ["resolver.quarantined", "resolver.quarantine_released"]


async def test_concurrent_final_reviews_open_exactly_one_second_round(
    database: None,
) -> None:
    async with _client() as client:
        project, _ = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("review_two"))
        reviews = await _rows(ReviewAssignment)
        assert len(reviews) == 2
        owner = await _token("owner")
        responses = await asyncio.gather(
            *(
                client.post(
                    f"/api/v1/projects/{project['id']}/review-assignments/"
                    f"{review.id}/submit",
                    headers=_auth(owner),
                    json={"version": 1, "evidence": {"decision": "no_object"}},
                )
                for review in reviews
            )
        )
    assert [response.status_code for response in responses] == [200, 200]
    async with async_session_factory() as session:
        second_rounds = await session.scalar(
            select(func.count())
            .select_from(ResolutionInput)
            .where(ResolutionInput.run_number == 2)
        )
    assert second_rounds == 1


async def _evidence(client: httpx.AsyncClient, project: dict, item_id: str) -> dict:
    """Return an image's evidence as the owner."""
    owner = await _token("owner")
    response = await client.get(
        f"/api/v1/projects/{project['id']}/batch-items/{item_id}/evidence",
        headers=_auth(owner),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _expected(evidence: dict) -> dict:
    """Return the expected-version fields of a manager action."""
    versions = evidence["versions"]
    return {
        "expected_evidence_generation": versions["evidence_generation"],
        "expected_configuration_fingerprint": versions["configuration_fingerprint"],
        "expected_resolution_version": versions["resolution_version"],
    }


async def _failed_case(client: httpx.AsyncClient) -> tuple[dict, dict, dict]:
    """Return a project, its test batch, and the evidence of a failed image."""
    project, batch = await _ready_test_item(client)
    broker = Broker()
    await _relay(broker)
    await _execute(broker.commands[0], ScriptedPipeline("invalid"))
    [item] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
    return project, batch, await _evidence(client, project, item.id)


async def _add_manager(client: httpx.AsyncClient, project: dict) -> str:
    """Add the user mia to the project as a manager and return her token."""
    await _create_user("mia")
    owner = await _token("owner")
    joined = await client.post(
        f"/api/v1/projects/{project['id']}/members",
        headers=_auth(owner),
        json={"username": "mia", "role": "manager"},
    )
    assert joined.status_code == 201, joined.text
    return await _token("mia")


async def test_queue_and_evidence_are_complete_and_manager_only(
    database: None,
) -> None:
    async with _client() as client:
        project, batch, evidence = await _failed_case(client)
        owner, annie = await _token("owner"), await _token("annie")
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/resolutions",
            headers=_auth(owner),
        )
        empty = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/resolutions",
            headers=_auth(owner),
            params={"state": "pending_review"},
        )
        hidden_queue = await client.get(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/resolutions",
            headers=_auth(annie),
        )
        hidden_evidence = await client.get(
            f"/api/v1/projects/{project['id']}/batch-items/"
            f"{evidence['batch_item_id']}/evidence",
            headers=_auth(annie),
        )

    assert queue.status_code == 200, queue.text
    [entry] = queue.json()["items"]
    assert entry["reason"] == "resolver_output_invalid"
    assert entry["scope"] == "image"
    assert entry["submissions"] == 2
    assert entry["resolver"] == "two_stage_detection_consensus"
    assert entry["class_strategy"] == "categorical_vote"
    assert empty.json()["items"] == []
    assert hidden_queue.status_code == 403
    assert hidden_evidence.status_code == 403

    assert evidence["status"] == "review_required"
    assert sorted(entry["annotator_name"] for entry in evidence["submissions"]) == [
        "Annie",
        "Bob",
    ]
    assert all(entry["current_generation"] for entry in evidence["submissions"])
    [run] = evidence["runs"]
    assert run["failure_code"] == "resolver_output_invalid"
    assert run["proposal"] is None
    assert evidence["versions"]["evidence_generation"] == 1
    assert evidence["versions"]["resolution_version"] == 0
    assert (
        evidence["versions"]["configuration_fingerprint"]
        == (run["configuration_fingerprint"])
    )
    assert len(evidence["contributors"]) == 2


async def test_an_adjudication_closes_a_failed_image(database: None) -> None:
    async with _client() as client:
        project, batch, evidence = await _failed_case(client)
        owner = await _token("owner")
        [case] = evidence["work_items"]
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        body = {
            **_expected(evidence),
            "action": "replace",
            "objects": [_box(project["class_id"], 25.0)],
            "rationale": "The resolver output was outside the image.",
        }
        without_lease = await client.post(
            f"{base}/adjudicate", headers=_auth(owner), json=body
        )
        leased = await client.post(f"{base}/lease", headers=_auth(owner))
        stale = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={**body, "expected_resolution_version": 3},
        )
        wrong_configuration = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={**body, "expected_configuration_fingerprint": "other"},
        )
        no_rationale = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={**body, "rationale": None},
        )
        adjudicated = await client.post(
            f"{base}/adjudicate", headers=_auth(owner), json=body
        )
        again = await client.post(f"{base}/adjudicate", headers=_auth(owner), json=body)

    assert without_lease.json()["error"]["code"] == "lease_required"
    assert leased.status_code == 200, leased.text
    assert stale.json()["error"]["code"] == "version_conflict"
    assert wrong_configuration.json()["error"]["code"] == "resolution_config_conflict"
    assert no_rationale.json()["error"]["code"] == "rationale_required"
    assert adjudicated.status_code == 200, adjudicated.text
    resolution = adjudicated.json()["resolution"]
    assert resolution["version"] == 1
    assert resolution["source"] == "expert_adjudication"
    assert resolution["objects"][0]["id"] == "o1"
    assert again.json()["error"]["code"] == "work_item_closed"

    [stored] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
    [stored_batch] = await _rows(AnnotationBatch, AnnotationBatch.id == batch["id"])
    [lease] = await _rows(ResolutionLease)
    assert stored.status == "resolved"
    assert stored_batch.status == "resolved"
    assert lease.released_at is not None
    assert {row.action for row in await _rows(AuditEntry)} >= {
        "resolution.adjudicated",
        "resolution.accepted",
    }


async def _raw_documents() -> dict[str, tuple]:
    """Return every raw submission and review as stored, keyed by ID."""
    submissions = {
        row.id: (row.content_hash, row.objects)
        for row in await _rows(AnnotationSubmission)
    }
    reviews = {
        row.id: (row.content_hash, row.evidence)
        for row in await _rows(ReviewSubmission)
    }
    return {**submissions, **reviews}


async def test_an_expert_edits_from_a_raw_submission_without_changing_it(
    database: None,
) -> None:
    async with _client() as client:
        project, _, evidence = await _failed_case(client)
        raw_before = await _raw_documents()
        owner = await _token("owner")
        [case] = evidence["work_items"]
        source = evidence["submissions"][0]
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        await client.post(f"{base}/lease", headers=_auth(owner))
        body = {
            **_expected(evidence),
            "action": "edit_submission",
            "objects": [_box(project["class_id"], 12.0)],
            "rationale": "Moved the box onto the object.",
        }
        foreign = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={**body, "source_submission_id": str(uuid4())},
        )
        adjudicated = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={**body, "source_submission_id": source["id"]},
        )

    assert foreign.json()["error"]["code"] == "invalid_source"
    assert adjudicated.status_code == 200, adjudicated.text
    resolution = adjudicated.json()["resolution"]
    assert resolution["source"] == "expert_adjudication"
    assert resolution["objects"][0]["geometry"]["coordinates"][0] == 12.0
    [decision] = await _rows(Adjudication)
    assert decision.source_submission_id == source["id"]
    assert await _raw_documents() == raw_before
    for row in await _rows(AnnotationSubmission):
        assert annotation_documents.content_hash(row.objects) == row.content_hash


async def test_a_contributor_must_explain_and_may_be_barred(database: None) -> None:
    async with _client() as client:
        project, batch = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("review"))
        [review] = await _rows(ReviewAssignment)
        owner = await _token("owner")
        await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"decision": "no_object"}},
        )
        await _relay(broker)
        await _execute(broker.commands[-1], ScriptedPipeline("disagree"))
        [item] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
        evidence = await _evidence(client, project, item.id)
        [case] = evidence["work_items"]
        url = (
            f"/api/v1/projects/{project['id']}/resolution-work-items/"
            f"{case['id']}/adjudicate"
        )
        body = {**_expected(evidence), "action": "accept_proposal"}
        unexplained = await client.post(url, headers=_auth(owner), json=body)

        async with async_session_factory() as session:
            stored_batch = await session.get(AnnotationBatch, batch["id"])
            stored_batch.require_independent_adjudicator = True
            await session.commit()
        barred = await client.post(
            url, headers=_auth(owner), json={**body, "rationale": "I reviewed it."}
        )
        async with async_session_factory() as session:
            stored_batch = await session.get(AnnotationBatch, batch["id"])
            stored_batch.require_independent_adjudicator = False
            await session.commit()
        accepted = await client.post(
            url, headers=_auth(owner), json={**body, "rationale": "I reviewed it."}
        )

    assert unexplained.json()["error"]["code"] == "rationale_required"
    assert unexplained.json()["error"]["details"]["contributor_conflict"] is True
    assert barred.status_code == 403
    assert barred.json()["error"]["code"] == "adjudicator_not_independent"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["adjudication"]["contributor_conflict"] is True
    assert accepted.json()["resolution"]["objects"] == []


async def test_a_retry_never_displaces_an_accepted_resolution(database: None) -> None:
    async with _client() as client:
        project, batch = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("accept"))
        [item] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
        evidence = await _evidence(client, project, item.id)
        owner = await _token("owner")
        url = f"/api/v1/projects/{project['id']}/batch-items/{item.id}/resolve"
        body = {**_expected(evidence), "rationale": "Re-check with the same settings."}
        stale = await client.post(
            url,
            headers=_auth(owner),
            json={**body, "expected_configuration_fingerprint": None},
        )
        unexplained = await client.post(
            url, headers=_auth(owner), json={**body, "rationale": ""}
        )
        queued = await client.post(url, headers=_auth(owner), json=body)
        duplicate = await client.post(url, headers=_auth(owner), json=body)

    assert stale.json()["error"]["code"] == "resolution_config_conflict"
    assert unexplained.status_code == 422
    assert queued.status_code == 202, queued.text
    assert queued.json()["trigger"] == "manual_retry"
    assert duplicate.json()["error"]["code"] == "resolution_in_progress"

    await _relay(broker)
    await _execute(broker.commands[-1], ScriptedPipeline("disagree"))
    [current] = await _rows(ResolvedAnnotation)
    [stored] = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
    assert current.version == 1
    assert stored.status == "resolved"
    assert await _rows(ResolutionWorkItem) == []

    async with _client() as client:
        evidence = await _evidence(client, project, item.id)
        accepted_retry = await client.post(
            url,
            headers=_auth(owner),
            json={**_expected(evidence), "rationale": "Try again."},
        )
    assert accepted_retry.status_code == 202, accepted_retry.text
    await _relay(broker)
    await _execute(broker.commands[-1], ScriptedPipeline("accept"))
    versions = sorted(await _rows(ResolvedAnnotation), key=lambda row: row.version)
    assert [row.version for row in versions] == [1, 2]
    assert versions[0].superseded_at is not None
    assert versions[1].superseded_at is None


async def test_a_retry_configuration_is_validated_and_recorded(
    database: None,
) -> None:
    async with _client() as client:
        project, batch, evidence = await _failed_case(client)
        owner = await _token("owner")
        url = (
            f"/api/v1/projects/{project['id']}/batch-items/"
            f"{evidence['batch_item_id']}/resolve"
        )
        body = {**_expected(evidence), "rationale": "Stricter matching."}
        weak = await client.post(
            url,
            headers=_auth(owner),
            json={
                **body,
                "configuration": {
                    "review_thresholds": {
                        "minimum_support": {"numerator": 1, "denominator": 2}
                    }
                },
            },
        )
        stricter = await client.post(
            url,
            headers=_auth(owner),
            json={**body, "configuration": {"parameters": {"matching_iou": 0.7}}},
        )

    assert weak.json()["error"]["code"] == "invalid_resolver_configuration"
    assert stricter.status_code == 202, stricter.text
    assert stricter.json()["configuration"]["parameters"]["matching_iou"] == 0.7
    [stored_batch] = await _rows(AnnotationBatch, AnnotationBatch.id == batch["id"])
    assert stored_batch.parameters["matching_iou"] == 0.5


async def test_leases_block_other_editors_and_can_be_revoked(database: None) -> None:
    async with _client() as client:
        project, _, evidence = await _failed_case(client)
        mia = await _add_manager(client, project)
        owner = await _token("owner")
        [case] = evidence["work_items"]
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        mine = await client.post(f"{base}/lease", headers=_auth(owner))
        renewed = await client.post(f"{base}/lease", headers=_auth(owner))
        taken = await client.post(f"{base}/lease", headers=_auth(mia))
        blocked = await client.post(
            f"{base}/adjudicate",
            headers=_auth(mia),
            json={
                **_expected(evidence),
                "action": "replace",
                "objects": [],
                "rationale": "Nothing is there.",
            },
        )
        unexplained = await client.post(
            f"{base}/lease/revoke", headers=_auth(mia), json={"reason": ""}
        )
        revoked = await client.post(
            f"{base}/lease/revoke",
            headers=_auth(mia),
            json={"reason": "The owner left for the day."},
        )
        acquired = await client.post(f"{base}/lease", headers=_auth(mia))

        async with async_session_factory() as session:
            lease = await session.scalar(
                select(ResolutionLease).where(ResolutionLease.released_at.is_(None))
            )
            lease.cap_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        capped = await client.post(f"{base}/lease", headers=_auth(mia))
        async with async_session_factory() as session:
            lease = await session.scalar(
                select(ResolutionLease).where(ResolutionLease.released_at.is_(None))
            )
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        after_expiry = await client.post(f"{base}/lease", headers=_auth(owner))

    assert mine.status_code == 200, mine.text
    assert renewed.json()["acquired_at"] == mine.json()["acquired_at"]
    assert taken.json()["error"]["code"] == "lease_held"
    assert blocked.json()["error"]["code"] == "lease_required"
    assert unexplained.status_code == 422
    assert revoked.status_code == 204
    assert acquired.status_code == 200, acquired.text
    assert capped.json()["error"]["code"] == "lease_cap_reached"
    assert after_expiry.status_code == 200, after_expiry.text
    revocations = await _rows(
        AuditEntry, AuditEntry.action == "resolution_lease.revoked"
    )
    assert len(revocations) == 1


async def test_a_cancelled_run_hands_the_image_to_an_expert(database: None) -> None:
    async with _client() as client:
        project, batch = await _ready_test_item(client)
        broker = Broker()
        await _relay(broker)
        [run] = await _rows(ResolutionRun)
        owner = await _token("owner")
        url = f"/api/v1/projects/{project['id']}/resolution-runs/{run.id}/cancel"
        cancelled = await client.post(
            url, headers=_auth(owner), json={"rationale": "Wrong settings."}
        )
        await _execute(broker.commands[0], ScriptedPipeline("accept"))
        finished = await client.post(
            url, headers=_auth(owner), json={"rationale": "Again."}
        )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "queued"
    [stored] = await _rows(ResolutionRun)
    [case] = await _rows(ResolutionWorkItem)
    assert (stored.status, stored.failure_code) == ("cancelled", "cancelled")
    assert (case.reason, case.status) == ("expert_required", "review_required")
    assert await _rows(ResolvedAnnotation) == []
    assert finished.json()["error"]["code"] == "run_not_active"


async def test_an_expert_decision_outranks_a_later_automatic_run(
    database: None,
) -> None:
    async with _client() as client:
        project, batch, evidence = await _failed_case(client)
        owner = await _token("owner")
        [case] = evidence["work_items"]
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        await client.post(f"{base}/lease", headers=_auth(owner))
        adjudicated = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={
                **_expected(evidence),
                "action": "replace",
                "objects": [_box(project["class_id"], 30.0)],
                "rationale": "Drawn by the expert.",
            },
        )
        assert adjudicated.status_code == 200, adjudicated.text
        evidence = await _evidence(client, project, evidence["batch_item_id"])
        retried = await client.post(
            f"/api/v1/projects/{project['id']}/batch-items/"
            f"{evidence['batch_item_id']}/resolve",
            headers=_auth(owner),
            json={**_expected(evidence), "rationale": "Compare with automation."},
        )
        assert retried.status_code == 202, retried.text
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[-1], ScriptedPipeline("accept"))

        current = [
            row for row in await _rows(ResolvedAnnotation) if row.superseded_at is None
        ]
        assert [(row.version, row.source) for row in current] == [
            (1, "expert_adjudication")
        ]
        evidence = await _evidence(client, project, evidence["batch_item_id"])
        held = next(
            entry
            for entry in evidence["work_items"]
            if entry["status"] == "review_required"
        )
        assert held["reason"] == "expert_required"
        url = (
            f"/api/v1/projects/{project['id']}/resolution-work-items/"
            f"{held['id']}/adjudicate"
        )
        body = {**_expected(evidence), "action": "accept_proposal"}
        unexplained = await client.post(url, headers=_auth(owner), json=body)
        accepted = await client.post(
            url,
            headers=_auth(owner),
            json={**body, "rationale": "The automatic result is right."},
        )

    assert unexplained.json()["error"]["code"] == "rationale_required"
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["resolution"]["version"] == 2


def _label(class_id: str) -> dict:
    """Return one classification label object."""
    return {
        "id": f"label-{class_id}",
        "class_id": class_id,
        "geometry": None,
        "attributes": {},
    }


async def test_classification_resolves_end_to_end_through_review(
    database: None,
) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client, "classification")
        cat, dog = project["class_ids"]
        await _start(client, project["id"], "test")
        for username, classes in (("annie", [cat]), ("bob", [cat, dog])):
            token = await _token(username)
            queue = await client.get(
                f"/api/v1/projects/{project['id']}/assignments", headers=_auth(token)
            )
            [entry] = queue.json()["items"]
            submitted = await client.post(
                f"/api/v1/projects/{project['id']}/assignments/{entry['id']}/submit",
                headers=_auth(token),
                json={
                    "version": entry["version"],
                    "objects": [_label(class_id) for class_id in classes],
                },
            )
            assert submitted.status_code == 200, submitted.text

        broker = Broker()
        await _relay(broker)
        await execute(broker.commands[0], async_session_factory)
        [case] = await _rows(ResolutionWorkItem)
        assert (case.scope, case.candidate_key, case.reason) == (
            "image",
            "image",
            "class_tie",
        )
        [review] = await _rows(ReviewAssignment)
        owner = await _token("owner")
        opened = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}",
            headers=_auth(owner),
        )
        assert opened.json()["candidate_context"] == {}
        unknown = await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"class_ids": ["no-such-class"]}},
        )
        reviewed = await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(owner),
            json={"version": 1, "evidence": {"class_ids": [cat]}},
        )
        assert unknown.json()["error"]["code"] == "invalid_review_evidence"
        assert reviewed.status_code == 200, reviewed.text
        raw_before = await _raw_documents()

    await _relay(broker)
    await execute(broker.commands[-1], async_session_factory)
    [resolution] = await _rows(ResolvedAnnotation)
    assert resolution.source == "automatic_consensus"
    assert [entry["class_id"] for entry in resolution.objects] == [cat]
    assert await _raw_documents() == raw_before
    [proposal, final] = sorted(
        await _rows(ResolutionProposal), key=lambda row: row.created_at
    )
    assert final.diagnostics["observation_matrix"][dog] == {
        review.reviewer_id: "negative",
        **{
            rater: outcome
            for rater, outcome in proposal.diagnostics["observation_matrix"][
                dog
            ].items()
        },
    }


async def _classification_ready(
    client: httpx.AsyncClient, documents: dict[str, list[int]]
) -> dict:
    """Return a classification project whose test image both annotators
    submitted, with class positions given per annotator."""
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    project = await _consensus_project(client, "classification")
    await _start(client, project["id"], "test")
    for username, positions in documents.items():
        token = await _token(username)
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments", headers=_auth(token)
        )
        [entry] = queue.json()["items"]
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/{entry['id']}/submit",
            headers=_auth(token),
            json={
                "version": entry["version"],
                "objects": [
                    _label(project["class_ids"][position]) for position in positions
                ],
            },
        )
        assert submitted.status_code == 200, submitted.text
    return project


async def test_acceptance_records_observations_once_and_supersession_closes_them(
    database: None,
) -> None:
    async with _client() as client:
        project = await _classification_ready(client, {"annie": [0], "bob": [0]})
        cat, dog = project["class_ids"]
        broker = Broker()
        await _relay(broker)
        await execute(broker.commands[0], async_session_factory)

        observations = await _rows(PerformanceObservation)
        assert {
            (row.observation_key.split(":")[2], row.outcome, row.metric_value)
            for row in observations
        } == {(cat, "retained", 1.0), (dog, "not_applicable", 1.0)}
        assert len(observations) == 4
        assert {row.project_id for row in observations} == {project["id"]}
        assert {row.evaluation_source for row in observations} == {
            "automated_consensus"
        }
        assert not any(row.weighting_eligible for row in observations)
        evidence_rows = await _rows(ResolutionObjectEvidence)
        assert {(row.outcome, row.canonical_object_id) for row in evidence_rows} == {
            ("retained", "o1")
        }

        [run] = await _rows(ResolutionRun)
        [item] = await _rows(BatchItem, BatchItem.id == run.batch_item_id)
        owner = await _token("owner")
        evidence = await _evidence(client, project, item.id)
        retried = await client.post(
            f"/api/v1/projects/{project['id']}/batch-items/{item.id}/resolve",
            headers=_auth(owner),
            json={**_expected(evidence), "rationale": "Replay."},
        )
        assert retried.status_code == 202, retried.text
        await _relay(broker)
        await execute(broker.commands[-1], async_session_factory)
        report = await client.get(
            f"/api/v1/projects/{project['id']}/annotator-performance",
            headers=_auth(owner),
        )
        hidden = await client.get(
            f"/api/v1/projects/{project['id']}/annotator-performance",
            headers=_auth(await _token("annie")),
        )

    rows = await _rows(PerformanceObservation)
    assert len(rows) == 8
    assert sum(row.summary_eligible for row in rows) == 4
    assert report.status_code == 200, report.text
    assert {entry["annotator_name"] for entry in report.json()["items"]} == {
        "Annie",
        "Bob",
    }
    assert all(entry["suppressed"] for entry in report.json()["items"])
    assert all(entry["outcomes"] is None for entry in report.json()["items"])
    assert hidden.status_code == 403


async def test_an_adjudicated_classification_is_eligible_for_weighting(
    database: None,
) -> None:
    async with _client() as client:
        project = await _classification_ready(client, {"annie": [0], "bob": [1]})
        cat, dog = project["class_ids"]
        broker = Broker()
        await _relay(broker)
        await _execute(broker.commands[0], ScriptedPipeline("invalid"))
        [run] = await _rows(ResolutionRun)
        [item] = await _rows(BatchItem, BatchItem.id == run.batch_item_id)
        evidence = await _evidence(client, project, item.id)
        [case] = evidence["work_items"]
        owner = await _token("owner")
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        await client.post(f"{base}/lease", headers=_auth(owner))
        decided = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={
                **_expected(evidence),
                "action": "replace",
                "objects": [_label(cat)],
                "rationale": "It is a cat.",
            },
        )
    assert decided.status_code == 200, decided.text
    rows = await _rows(PerformanceObservation)
    assert {row.evaluation_source for row in rows} == {"human_adjudication"}
    assert all(row.weighting_eligible for row in rows)
    names = {
        user.id: user.username
        for user in await _rows(User, User.username.in_(["annie", "bob"]))
    }
    outcomes = {
        (names[row.annotator_id], row.observation_key.split(":")[2], row.outcome)
        for row in rows
    }
    assert outcomes == {
        ("annie", cat, "retained"),
        ("annie", dog, "not_applicable"),
        ("bob", cat, "missed_object"),
        ("bob", dog, "false_positive"),
    }


async def _submit_documents(
    client: httpx.AsyncClient, project: dict, documents: dict[str, list[dict]]
) -> None:
    """Submit one document per annotator for the started test image."""
    for username, objects in documents.items():
        token = await _token(username)
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments", headers=_auth(token)
        )
        [entry] = queue.json()["items"]
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/{entry['id']}/submit",
            headers=_auth(token),
            json={"version": entry["version"], "objects": objects},
        )
        assert submitted.status_code == 200, submitted.text


def _polygon(class_id: str, x: float, size: float = 20.0) -> dict:
    """Return one square polygon object."""
    return {
        "id": f"poly-{x}",
        "class_id": class_id,
        "geometry": {
            "type": "polygon",
            "coordinates": [[x, 10.0, x + size, 10.0, x + size, 30.0, x, 30.0]],
        },
        "attributes": {},
    }


async def test_detection_resolves_with_box_agreement_observations(
    database: None,
) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client, "detection")
        await _start(client, project["id"], "test")
        cat = project["class_id"]
        await _submit_documents(
            client, project, {"annie": [_box(cat, 10.0)], "bob": [_box(cat, 12.0)]}
        )
    broker = Broker()
    await _relay(broker)
    await execute(broker.commands[0], async_session_factory)

    [resolution] = await _rows(ResolvedAnnotation)
    [entry] = resolution.objects
    assert entry["id"] == "o1"
    assert entry["geometry"]["coordinates"] == [11.0, 10.0, 40.0, 30.0]
    rows = await _rows(PerformanceObservation)
    assert {(row.outcome, row.metric_name) for row in rows} == {("retained", "box_iou")}
    assert all(0.9 < row.metric_value < 1.0 for row in rows)
    assert len(await _rows(ResolutionObjectEvidence)) == 2


async def test_a_reviewed_false_positive_is_recorded_without_a_zero_overlap(
    database: None,
) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client, "detection")
        await _start(client, project["id"], "test")
        await _submit_documents(
            client, project, {"annie": [_box(project["class_id"])], "bob": []}
        )
        broker = Broker()
        await _relay(broker)
        await execute(broker.commands[0], async_session_factory)
        [review] = await _rows(ReviewAssignment)
        opened = await client.get(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}",
            headers=_auth(await _token("owner")),
        )
        assert opened.json()["candidate_context"]["region"]
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/review-assignments/{review.id}/submit",
            headers=_auth(await _token("owner")),
            json={"version": 1, "evidence": {"decision": "no_object"}},
        )
        assert submitted.status_code == 200, submitted.text
    await _relay(broker)
    await execute(broker.commands[-1], async_session_factory)

    [resolution] = await _rows(ResolvedAnnotation)
    assert resolution.objects == []
    rows = await _rows(PerformanceObservation)
    assert {(row.outcome, row.metric_name, row.metric_value) for row in rows} == {
        ("false_positive", "existence", None)
    }


async def test_segmentation_resolves_with_mask_agreement_observations(
    database: None,
) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client, "segmentation")
        await _start(client, project["id"], "test")
        cat = project["class_id"]
        await _submit_documents(
            client,
            project,
            {"annie": [_polygon(cat, 10.0)], "bob": [_polygon(cat, 11.0)]},
        )
    broker = Broker()
    await _relay(broker)
    await execute(broker.commands[0], async_session_factory)

    [resolution] = await _rows(ResolvedAnnotation)
    [entry] = resolution.objects
    assert entry["geometry"]["type"] == "polygon"
    rows = await _rows(PerformanceObservation)
    assert {row.metric_name for row in rows} == {"mask_iou", "mask_dice"}
    assert {row.outcome for row in rows} == {"retained"}
    [summary, _] = performance.summarize(rows)
    assert summary["decisions"] == 1


async def _batch_of(client: httpx.AsyncClient, project: dict, purpose: str) -> dict:
    """Return the project's batch with the given purpose."""
    listed = await client.get(
        f"/api/v1/projects/{project['id']}/batches",
        headers=_auth(await _token("owner")),
    )
    return next(item for item in listed.json()["items"] if item["purpose"] == purpose)


def _conditional_policy(batch: dict, strategy: str) -> dict:
    """Return a batch policy body selecting a conditional class strategy."""
    return {
        "mode": "consensus",
        "annotator_ids": batch["annotator_ids"],
        "required_consensus_annotations": 2,
        "required_consensus_reviewers": 1,
        "resolver": "statistical_class_consensus",
        "parameters": {"class_strategy": {"strategy": strategy}},
    }


async def test_conditional_strategies_report_and_enforce_their_evidence(
    database: None,
) -> None:
    for username in ("owner", "annie", "bob"):
        await _create_user(username)
    async with _client() as client:
        project = await _consensus_project(client, "classification")
        owner = await _token("owner")
        eligibility = await client.get(
            f"/api/v1/projects/{project['id']}/resolver-eligibility",
            headers=_auth(owner),
        )
        hidden = await client.get(
            f"/api/v1/projects/{project['id']}/resolver-eligibility",
            headers=_auth(await _token("annie")),
        )
        batch = await _batch_of(client, project, "test")
        patched = await client.patch(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(owner),
            json=_conditional_policy(batch, "dawid_skene"),
        )
        assert patched.status_code == 200, patched.text
        refused = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(owner),
        )

    verdicts = {entry["strategy"]: entry for entry in eligibility.json()["strategies"]}
    assert set(verdicts) == {"reliability_weighted_vote", "dawid_skene"}
    assert not any(entry["eligible"] for entry in verdicts.values())
    reliability_gaps = verdicts["reliability_weighted_vote"]["missing"]
    assert "decisions_per_rater" in {gap["requirement"] for gap in reliability_gaps}
    assert hidden.status_code == 403
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "resolver_unavailable"
    assert refused.json()["error"]["details"]["strategy"] == "dawid_skene"
    assert await _rows(AnnotationAssignment) == []


async def test_reliability_weights_are_frozen_from_adjudicated_evidence(
    database: None,
) -> None:
    async with _client() as client:
        project = await _classification_ready(client, {"annie": [0], "bob": [0]})
        cat, dog = project["class_ids"]
        broker = Broker()
        await _relay(broker)
        await execute(broker.commands[0], async_session_factory)
        [resolution] = await _rows(ResolvedAnnotation)
        users = {
            user.username: user.id
            for user in await _rows(User, User.username.in_(["owner", "annie", "bob"]))
        }
        async with async_session_factory() as session:
            for username, rater in users.items():
                for index in range(40):
                    reference = cat if index % 2 else None
                    wrong = None if reference else dog
                    session.add(
                        PerformanceObservation(
                            project_id=project["id"],
                            annotator_id=rater,
                            batch_item_id=resolution.batch_item_id,
                            resolution_id=resolution.id,
                            resolution_version=1,
                            observation_key=f"seed:{username}:{index}",
                            evaluation_source="human_adjudication",
                            task_type="classification",
                            submitted_class_id=reference if index % 10 else wrong,
                            canonical_class_id=reference,
                            outcome="retained",
                            metric_name="class_agreement",
                            metric_value=1.0,
                            weighting_eligible=True,
                            summary_eligible=True,
                        )
                    )
            await session.commit()

        owner = await _token("owner")
        eligibility = await client.get(
            f"/api/v1/projects/{project['id']}/resolver-eligibility",
            headers=_auth(owner),
        )
        batch = await _batch_of(client, project, "validation")
        await client.patch(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}",
            headers=_auth(owner),
            json=_conditional_policy(batch, "reliability_weighted_vote"),
        )
        started = await client.post(
            f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
            headers=_auth(owner),
        )
        assert started.status_code == 200, started.text
        validation_items = await _rows(BatchItem, BatchItem.batch_id == batch["id"])
        for username in ("annie", "bob", "owner"):
            token = await _token(username)
            queue = await client.get(
                f"/api/v1/projects/{project['id']}/assignments",
                headers=_auth(token),
                params={"state": "pending"},
            )
            for entry in queue.json()["items"]:
                await client.post(
                    f"/api/v1/projects/{project['id']}/assignments/"
                    f"{entry['id']}/submit",
                    headers=_auth(token),
                    json={"version": entry["version"], "objects": [_label(cat)]},
                )

    verdicts = {entry["strategy"]: entry for entry in eligibility.json()["strategies"]}
    assert verdicts["reliability_weighted_vote"]["eligible"] is True
    [stored_batch] = await _rows(AnnotationBatch, AnnotationBatch.id == batch["id"])
    [snapshot] = await _rows(CalibrationSnapshot)
    assert stored_batch.calibration_snapshot_id == snapshot.id
    assert set(snapshot.parameters) == {cat, dog}
    assert set(snapshot.parameters[cat]["weights"]) == set(users.values())

    await _relay(broker)
    await execute(broker.commands[-1], async_session_factory)
    validation_ids = {item.id for item in validation_items}
    resolved = [
        row
        for row in await _rows(ResolvedAnnotation)
        if row.batch_item_id in validation_ids
    ]
    assert [[entry["class_id"] for entry in row.objects] for row in resolved] == [[cat]]
    [proposal] = [
        row
        for row in await _rows(ResolutionProposal)
        if row.batch_item_id in validation_ids
    ]
    assert "weights" in proposal.candidates[0]["metrics"]["classes"][cat]


async def test_only_owners_and_managers_reach_the_resolution_routes(
    database: None,
) -> None:
    async with _client() as client:
        project, batch, evidence = await _failed_case(client)
        await _create_user("vic")
        await _create_user("outsider")
        joined = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(await _token("owner")),
            json={"username": "vic", "role": "viewer"},
        )
        assert joined.status_code == 201, joined.text
        [run] = evidence["runs"]
        [case] = evidence["work_items"]
        base = f"/api/v1/projects/{project['id']}"
        item = evidence["batch_item_id"]
        work = f"{base}/resolution-work-items/{case['id']}"
        routes = [
            ("get", f"{base}/batches/{batch['id']}/resolutions", None),
            ("get", f"{base}/batch-items/{item}/evidence", None),
            ("post", f"{base}/batch-items/{item}/resolve", {"rationale": "x"}),
            ("post", f"{base}/resolution-runs/{run['id']}/cancel", {"rationale": "x"}),
            ("post", f"{work}/adjudicate", {"action": "accept_proposal"}),
            ("post", f"{work}/lease", None),
            ("delete", f"{work}/lease", None),
            ("post", f"{work}/lease/revoke", {"reason": "x"}),
            ("get", f"{base}/annotator-performance", None),
            ("get", f"{base}/resolver-eligibility", None),
            ("get", f"{base}/annotation-policy/history", None),
        ]
        statuses = {}
        for username in ("annie", "vic", "outsider"):
            token = await _token(username)
            for method, url, body in routes:
                expected = {**_expected(evidence), **body} if body else None
                response = await client.request(
                    method.upper(), url, headers=_auth(token), json=expected
                )
                statuses[(username, method, url)] = response.status_code

    assert set(statuses.values()) == {403}
    assert len(statuses) == 33


async def test_deleting_a_project_removes_its_whole_resolution_history(
    database: None,
) -> None:
    async with _client() as client:
        project, _, evidence = await _failed_case(client)
        owner = await _token("owner")
        [case] = evidence["work_items"]
        base = f"/api/v1/projects/{project['id']}/resolution-work-items/{case['id']}"
        await client.post(f"{base}/lease", headers=_auth(owner))
        adjudicated = await client.post(
            f"{base}/adjudicate",
            headers=_auth(owner),
            json={
                **_expected(evidence),
                "action": "replace",
                "objects": [_box(project["class_id"], 20.0)],
                "rationale": "Drawn by the expert.",
            },
        )
        assert adjudicated.status_code == 200, adjudicated.text
        deleted = await client.delete(
            f"/api/v1/projects/{project['id']}", headers=_auth(owner)
        )

    assert deleted.status_code == 204, deleted.text
    for model in (
        ResolutionRun,
        ResolutionProposal,
        ResolvedAnnotation,
        ResolutionWorkItem,
        ResolutionLease,
        ResolutionObjectEvidence,
        PerformanceObservation,
        ResolutionInput,
        OutboxEvent,
        CalibrationSnapshot,
    ):
        assert await _rows(model) == [], model.__name__
