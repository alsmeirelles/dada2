"""Phase 7 acquisition loop: settings, random and active-learning iterations,
worker attempts, retries, stale results, and stopping, over real HTTP."""

import json
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from dada_api.active_learning.contract import (
    AdapterError,
    BaseModelAdapter,
    BatchRequest,
    BatchResult,
    ManifestRef,
    read_manifest,
)
from dada_api.active_learning.deterministic import DeterministicAdapter
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
from dada_api.models.consensus import OutboxEvent
from dada_api.models.dataset import DatasetSplit
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.label_import import AnnotationImport
from dada_api.models.learning import LearningRun, ModelEvaluation
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.user import User
from dada_api.services import learning_runs
from dada_api.workers import learning

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase7-learning-password"
MEDIA_COUNT = 8
DRAFT = {
    "name": "Belt",
    "description": None,
    "task_type": "detection",
    "test_set_size": 1,
    "validation_set_size": 1,
    "initial_training_size": 2,
    "iteration_batch_size": 2,
    "max_acquisition_iterations": 5,
}
LEARNING = {
    **DRAFT,
    "acquisition_strategy": "active_learning",
    "max_acquisition_iterations": 2,
}


class Broker:
    """Collects the commands the relay sends instead of a Celery broker."""

    def __init__(self) -> None:
        self.commands: list[learning_runs.Command] = []

    def __call__(self, command: learning_runs.Command, _: LearningRun) -> None:
        self.commands.append(command)


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


async def _reset_database() -> None:
    """Remove every record these tests create."""
    async with async_session_factory() as session:
        for model in (
            IdempotencyRecord,
            ResolvedAnnotation,
            AnnotationSubmission,
            AnnotationAssignment,
            ModelEvaluation,
            AnnotationImport,
            BatchItem,
            AnnotationBatchAnnotator,
            AnnotationBatch,
            LearningRun,
            OutboxEvent,
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


async def _user(username: str) -> str:
    """Persist a user and return an access token for it."""
    async with async_session_factory() as session:
        session.add(
            User(
                username=username,
                display_name=username.title(),
                password_hash=hash_password(PASSWORD),
                is_administrator=False,
                is_active=True,
                version=1,
            )
        )
        await session.commit()
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token", json={"username": username, "password": PASSWORD}
        )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _add_media(project_id: str) -> None:
    """Persist media rows and their bytes directly."""
    async with async_session_factory() as session:
        for index in range(MEDIA_COUNT):
            digest = f"{index + 100:064x}"
            key = f"{project_id}/{digest[:2]}/{digest[2:4]}/{digest}"
            path = get_settings().media_root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"belt-{index}".encode())
            content = ContentObject(
                project_id=project_id,
                sha256=digest,
                size_bytes=len(f"belt-{index}"),
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
                    relative_path=f"belt/frame-{index:04d}.png",
                )
            )
        await session.commit()


async def _project(client: httpx.AsyncClient, token: str, body: dict) -> dict:
    """Create, prepare, and activate a project with one class and media."""
    created = await client.post("/api/v1/projects", headers=_auth(token), json=body)
    assert created.status_code == 201, created.text
    project = created.json()
    added = await client.post(
        f"/api/v1/projects/{project['id']}/classes",
        headers=_auth(token),
        json={"name": "bottle", "color": "#00FF00", "display_order": 0},
    )
    assert added.status_code == 201, added.text
    project["class_id"] = added.json()["id"]
    await _add_media(project["id"])
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


async def _annotate_everything(
    client: httpx.AsyncClient,
    token: str,
    project_id: str,
    objects: list[dict] | None = None,
) -> None:
    """Start every preparing batch and submit every open assignment."""
    listed = await client.get(
        f"/api/v1/projects/{project_id}/batches", headers=_auth(token)
    )
    for batch in listed.json()["items"]:
        if batch["status"] == "preparing":
            started = await client.post(
                f"/api/v1/projects/{project_id}/batches/{batch['id']}/start",
                headers=_auth(token),
            )
            assert started.status_code == 200, started.text
    queue = await client.get(
        f"/api/v1/projects/{project_id}/assignments", headers=_auth(token)
    )
    for item in queue.json()["items"]:
        if item["status"] == "submitted":
            continue
        submitted = await client.post(
            f"/api/v1/projects/{project_id}/assignments/{item['id']}/submit",
            headers=_auth(token),
            json={"version": item["version"], "objects": objects or []},
        )
        assert submitted.status_code == 200, submitted.text


async def _relay(broker: Broker | None = None, now: datetime | None = None) -> dict:
    """Run one learning relay pass."""
    async with async_session_factory() as session:
        return await learning_runs.relay_once(
            session, broker or Broker(), now or datetime.now(UTC)
        )


async def _execute(
    command: learning_runs.Command, adapter: BaseModelAdapter | None = None
) -> None:
    """Run one worker attempt with an in-process adapter."""
    await learning.execute(
        command,
        async_session_factory,
        load_adapter=lambda *_: adapter or DeterministicAdapter(),
    )


async def _runs(project_id: str) -> list[LearningRun]:
    """Return a project's runs in iteration and attempt order."""
    async with async_session_factory() as session:
        return list(
            await session.scalars(
                select(LearningRun)
                .where(LearningRun.project_id == project_id)
                .order_by(LearningRun.iteration, LearningRun.attempt)
            )
        )


async def _iterations(client: httpx.AsyncClient, token: str, project_id: str) -> dict:
    """Return the project's iteration page."""
    response = await client.get(
        f"/api/v1/projects/{project_id}/iterations", headers=_auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _manifest(run: LearningRun, name: str) -> dict:
    """Read one of a run's snapshots back from disk."""
    return read_manifest(
        str(get_settings().media_root), ManifestRef(**run.snapshots[name])
    )


async def test_learning_settings_receive_defaults_and_are_validated(
    database: None,
) -> None:
    token = await _user("owner")
    async with _client() as client:
        created = await client.post(
            "/api/v1/projects", headers=_auth(token), json=LEARNING
        )
        unknown = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**LEARNING, "learning_solution": "missing"},
        )
        wrong_metric = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**LEARNING, "evaluation_metric": "accuracy"},
        )
        bad_configuration = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**LEARNING, "learning_configuration": {"unknown": 1}},
        )
        random_with_settings = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={**DRAFT, "metric_target": 0.5},
        )
        no_limit = await client.post(
            "/api/v1/projects",
            headers=_auth(token),
            json={
                key: value
                for key, value in DRAFT.items()
                if key != "max_acquisition_iterations"
            },
        )
        project = created.json()
        changed = await client.patch(
            f"/api/v1/projects/{project['id']}",
            headers=_auth(token),
            json={
                "version": 1,
                "metric_target": 0.8,
                "evaluation_interval": 3,
                "max_acquisition_iterations": 4,
            },
        )
        to_random = await client.patch(
            f"/api/v1/projects/{project['id']}",
            headers=_auth(token),
            json={"version": 2, "acquisition_strategy": "random"},
        )

    assert created.status_code == 201, created.text
    assert {
        key: project[key]
        for key in (
            "learning_solution",
            "learning_solution_version",
            "learning_configuration",
            "evaluation_metric",
            "evaluation_interval",
            "metric_target",
            "max_acquisition_iterations",
            "completion_reason",
        )
    } == {
        "learning_solution": "deterministic",
        "learning_solution_version": "1.0.0",
        "learning_configuration": {"retain_helper_models": False},
        "evaluation_metric": "map50",
        "evaluation_interval": 1,
        "metric_target": None,
        "max_acquisition_iterations": 2,
        "completion_reason": None,
    }
    assert unknown.json()["error"]["code"] == "learning_solution_unknown"
    assert wrong_metric.json()["error"]["code"] == "evaluation_metric_invalid"
    assert bad_configuration.json()["error"]["code"] == "learning_configuration_invalid"
    assert random_with_settings.status_code == 422
    assert no_limit.status_code == 422
    assert changed.status_code == 200, changed.text
    assert changed.json()["metric_target"] == 0.8
    assert changed.json()["evaluation_interval"] == 3
    assert changed.json()["max_acquisition_iterations"] == 4
    assert to_random.json()["learning_solution"] is None
    assert to_random.json()["max_acquisition_iterations"] == 4

    async with async_session_factory() as session:
        entries = list(
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.action == "project.learning_settings_changed")
                .order_by(AuditEntry.created_at)
            )
        )
    assert entries[0].after["metric_target"] == 0.8
    assert entries[1].after["learning_solution"] is None


async def test_random_acquisition_opens_iterations_until_the_pool_runs_out(
    database: None,
) -> None:
    token = await _user("owner")
    async with _client() as client:
        project = await _project(client, token, DRAFT)
        assert (await _relay())["opened"] == 0
        await _annotate_everything(client, token, project["id"])
        first_pass = await _relay()
        first = await _iterations(client, token, project["id"])
        await _annotate_everything(client, token, project["id"])
        await _relay()
        await _annotate_everything(client, token, project["id"])
        await _relay()
        statistics = await client.get(
            f"/api/v1/projects/{project['id']}/statistics", headers=_auth(token)
        )
        reread = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        final = await _iterations(client, token, project["id"])

    assert first_pass["opened"] == 1
    [opened] = first["items"]
    assert opened["number"] == 1
    assert opened["status"] == "preparing"
    assert opened["strategy"] == "random"
    assert opened["selected_count"] == 2
    assert opened["total_count"] == 2
    assert first["current_iteration"]["id"] == opened["id"]

    assert [item["status"] for item in final["items"]] == ["ready", "ready"]
    assert reread.json()["status"] == "completed"
    assert reread.json()["completion_reason"] == "pool_exhausted"
    assert statistics.json()["completed_iterations"] == 2
    assert statistics.json()["evaluations"] == []

    async with async_session_factory() as session:
        acquisitions = list(
            await session.scalars(
                select(AnnotationBatch).where(
                    AnnotationBatch.project_id == project["id"],
                    AnnotationBatch.purpose == "acquisition",
                )
            )
        )
        splits = {
            row.media_id: row.split
            for row in await session.scalars(
                select(DatasetSplit).where(DatasetSplit.project_id == project["id"])
            )
        }
        chosen = list(
            await session.scalars(
                select(BatchItem.media_id).where(
                    BatchItem.batch_id.in_([batch.id for batch in acquisitions])
                )
            )
        )
        events = list(
            await session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == "learning.batch_resolved.v1"
                )
            )
        )
    assert all(batch.model_run_id for batch in acquisitions)
    assert len(chosen) == len(set(chosen)) == 4
    assert {splits[media_id] for media_id in chosen} == {"train"}
    assert len(events) == 5
    assert all(event.published_at is not None for event in events)


async def test_random_acquisition_stops_at_the_iteration_limit(database: None) -> None:
    token = await _user("owner")
    async with _client() as client:
        project = await _project(
            client, token, {**DRAFT, "max_acquisition_iterations": 1}
        )
        await _annotate_everything(client, token, project["id"])
        await _relay()
        await _annotate_everything(client, token, project["id"])
        await _relay()
        reread = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
    assert reread.json()["status"] == "completed"
    assert reread.json()["completion_reason"] == "max_iterations"
    assert len(await _runs(project["id"])) == 1


async def test_active_learning_runs_through_the_worker_to_its_final_evaluation(
    database: None,
) -> None:
    token = await _user("owner")
    broker = Broker()
    async with _client() as client:
        project = await _project(client, token, LEARNING)
        await _annotate_everything(client, token, project["id"])
        opened = await _relay(broker)
        queued = await _iterations(client, token, project["id"])
        await _execute(broker.commands[0])
        selected = await _iterations(client, token, project["id"])
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        await _execute(broker.commands[1])
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        await _execute(broker.commands[2])
        statistics = await client.get(
            f"/api/v1/projects/{project['id']}/statistics", headers=_auth(token)
        )
        reread = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        final = await _iterations(client, token, project["id"])

    assert opened == {"opened": 1, "expired": 0, "dispatched": 1}
    assert queued["items"][0]["status"] == "training"
    first = selected["items"][0]
    assert first["status"] == "preparing"
    assert first["strategy"] == "active_learning"
    assert first["solution"] == "deterministic"
    assert first["selected_count"] == 2
    assert first["evaluations"] == []

    runs = await _runs(project["id"])
    assert [(run.iteration, run.purpose, run.status) for run in runs] == [
        (1, "selection", "succeeded"),
        (2, "selection", "succeeded"),
        (3, "final_evaluation", "succeeded"),
    ]
    assert runs[0].evaluation is None
    assert runs[1].evaluation["metric"] == "map50"
    assert runs[2].evaluation["final"] is True
    assert set(runs[2].snapshots) == {"training", "validation", "test"}

    training = _manifest(runs[1], "training")
    pool = _manifest(runs[1], "pool")
    validation = _manifest(runs[1], "validation")
    assert training["info"]["schema"] == "dada-coco-pai/1"
    assert len(training["images"]) == 4
    assert {image["annotation_status"] for image in training["images"]} == {
        "EXHAUSTIVELY_LABELED"
    }
    assert len(pool["images"]) == 2
    assert len(validation["images"]) == 1
    held_out = {image["id"] for image in validation["images"]}
    assert held_out.isdisjoint(image["id"] for image in training["images"])
    assert held_out.isdisjoint(image["id"] for image in pool["images"])
    assert training["categories"] == [
        {"id": 0, "name": "bottle", "class_id": project["class_id"]}
    ]

    assert [item["status"] for item in final["items"]] == ["ready", "ready", "ready"]
    assert final["items"][2]["purpose"] == "final_evaluation"
    assert reread.json()["status"] == "completed"
    assert reread.json()["completion_reason"] == "max_iterations"
    evaluations = statistics.json()["evaluations"]
    assert [(item["iteration"], item["split"]) for item in evaluations] == [
        (2, "validation"),
        (3, "validation"),
        (3, "test"),
    ]
    assert evaluations[-1]["value"] == 1.0
    assert evaluations[0]["model"] == {"name": "deterministic", "version": "1.0.0"}
    artifacts = get_settings().media_root / project["id"] / "learning" / "runs"
    assert not any(artifacts.glob("iteration-*"))


async def test_a_met_metric_target_stops_with_a_test_evaluation(
    database: None,
) -> None:
    token = await _user("owner")
    broker = Broker()
    async with _client() as client:
        project = await _project(
            client,
            token,
            {**LEARNING, "metric_target": 0.5, "max_acquisition_iterations": 5},
        )
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        await _execute(broker.commands[0])
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        await _execute(broker.commands[1])
        reread = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        page = await _iterations(client, token, project["id"])

    runs = await _runs(project["id"])
    assert set(runs[1].snapshots) == {"training", "pool", "validation", "test"}
    assert runs[1].result["stop_reason"] == "metric_target"
    assert runs[1].result["selected"] == 0
    assert reread.json()["completion_reason"] == "metric_target"
    assert page["items"][1]["stop_reason"] == "metric_target"
    assert page["items"][1]["status"] == "ready"
    assert page["items"][1]["metrics"] == {"map50": 0.666667}


class Failing(BaseModelAdapter):
    """Reports a typed failure, as a solution that cannot run would."""

    def select_batch(self, request: BatchRequest, report_stage=None) -> BatchResult:
        report_stage("training")
        raise AdapterError("training_failed", "out of memory")


class Invalid(DeterministicAdapter):
    """Returns a well-formed answer that does not fit its request."""

    def __init__(self, change: str) -> None:
        self.change = change

    def select_batch(self, request: BatchRequest, report_stage=None) -> BatchResult:
        result = super().select_batch(request, report_stage)
        if self.change == "solution":
            return result.model_copy(update={"solution_id": "another"})
        images = list(result.selection["images"])
        if self.change == "ineligible":
            images[0] = {**images[0], "id": "not-in-the-pool"}
        if self.change == "oversized":
            images = images + [{**images[0], "id": "extra"}]
        if self.change == "repeated":
            images = [images[0], images[0]]
        return result.model_copy(
            update={"selection": {**result.selection, "images": images}}
        )


async def test_failures_are_recorded_and_a_retry_reuses_the_snapshots(
    database: None,
) -> None:
    owner = await _user("owner")
    viewer = await _user("viewer")
    broker = Broker()
    async with _client() as client:
        project = await _project(client, owner, LEARNING)
        await _annotate_everything(client, owner, project["id"])
        await _relay(broker)
        joined = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner),
            json={"username": "viewer", "role": "annotator"},
        )
        assert joined.status_code == 201, joined.text
        await _execute(broker.commands[0], Failing())
        failed = await _iterations(client, owner, project["id"])
        iteration_id = failed["items"][0]["id"]
        forbidden = await client.post(
            f"/api/v1/projects/{project['id']}/iterations/{iteration_id}/retry",
            headers=_auth(viewer),
        )
        retried = await client.post(
            f"/api/v1/projects/{project['id']}/iterations/{iteration_id}/retry",
            headers=_auth(owner),
        )
        again = await client.post(
            f"/api/v1/projects/{project['id']}/iterations/{iteration_id}/retry",
            headers=_auth(owner),
        )
        await _relay(broker)
        await _execute(broker.commands[1])
        recovered = await _iterations(client, owner, project["id"])

    assert failed["items"][0]["status"] == "failed"
    assert failed["items"][0]["failure_code"] == "training_failed"
    assert failed["items"][0]["failure_detail"] == "out of memory"
    assert forbidden.status_code == 403
    assert retried.status_code == 202, retried.text
    assert retried.json()["attempt"] == 2
    assert retried.json()["status"] == "training"
    assert again.json()["error"]["code"] == "iteration_not_failed"
    assert recovered["items"][0]["id"] == iteration_id
    assert recovered["items"][0]["status"] == "preparing"

    first, second = await _runs(project["id"])
    assert second.attempt == 2
    assert second.snapshots == first.snapshots
    assert second.seed == first.seed
    assert second.configuration_fingerprint == first.configuration_fingerprint
    assert second.requested_by is not None


@pytest.mark.parametrize("change", ["solution", "ineligible", "oversized", "repeated"])
async def test_a_result_that_does_not_fit_its_request_fails_the_run(
    database: None, change: str
) -> None:
    token = await _user("owner")
    broker = Broker()
    async with _client() as client:
        project = await _project(client, token, LEARNING)
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        await _execute(broker.commands[0], Invalid(change))

    [run] = await _runs(project["id"])
    assert run.status == "failed"
    assert run.failure_code == "solution_output_invalid"
    async with async_session_factory() as session:
        acquisitions = await session.scalar(
            select(AnnotationBatch.id).where(
                AnnotationBatch.project_id == project["id"],
                AnnotationBatch.purpose == "acquisition",
            )
        )
    assert acquisitions is None


async def test_duplicate_late_and_timed_out_results_change_nothing(
    database: None,
) -> None:
    token = await _user("owner")
    broker = Broker()
    async with _client() as client:
        project = await _project(client, token, LEARNING)
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        command = broker.commands[0]
        await _execute(command)
        await _execute(command)
        async with async_session_factory() as session:
            late = await learning_runs.ingest(
                session,
                command,
                learning_runs.Failure("worker_failed", "late"),
                datetime.now(UTC),
            )
        await _annotate_everything(client, token, project["id"])
        await _relay(broker)
        timed_out = broker.commands[1]
        async with async_session_factory() as session:
            request = await learning_runs.start_attempt(
                session, timed_out, datetime.now(UTC)
            )
        async with async_session_factory() as session:
            await learning_runs.record_stage(session, timed_out, "evaluating")
        staged = (await _runs(project["id"]))[1].stage
        expired = await _relay(
            broker,
            datetime.now(UTC)
            + timedelta(seconds=get_settings().learning_timeout_seconds + 120),
        )
        async with async_session_factory() as session:
            delayed = await learning_runs.ingest(
                session,
                timed_out,
                DeterministicAdapter().select_batch(request),
                datetime.now(UTC),
            )

    assert late is False
    assert request is not None
    assert staged == "evaluating"
    assert expired["expired"] == 1
    assert delayed is False
    first, second = await _runs(project["id"])
    assert first.status == "succeeded"
    assert second.status == "failed"
    assert second.failure_code == "worker_failed"
    async with async_session_factory() as session:
        acquisitions = list(
            await session.scalars(
                select(AnnotationBatch).where(
                    AnnotationBatch.project_id == project["id"],
                    AnnotationBatch.purpose == "acquisition",
                )
            )
        )
    assert len(acquisitions) == 1


async def test_closing_reports_unfinished_work_and_reconciles_a_missed_event(
    database: None,
) -> None:
    token = await _user("owner")
    async with _client() as client:
        project = await _project(client, token, DRAFT)
        await _annotate_everything(client, token, project["id"])
        await _relay()
        [first] = (await _iterations(client, token, project["id"]))["items"]
        url = f"/api/v1/projects/{project['id']}/iterations/{first['id']}/close"
        incomplete = await client.post(url, headers=_auth(token))
        await _annotate_everything(client, token, project["id"])
        async with async_session_factory() as session:
            for event in await session.scalars(select(OutboxEvent)):
                event.published_at = datetime.now(UTC)
            await session.commit()
        closed = await client.post(url, headers=_auth(token))
        repeated = await client.post(url, headers=_auth(token))
        page = await _iterations(client, token, project["id"])
        missing = await client.get(
            f"/api/v1/projects/{project['id']}/iterations/{project['id']}",
            headers=_auth(token),
        )

    assert incomplete.status_code == 409
    assert incomplete.json()["error"]["code"] == "iteration_incomplete"
    assert incomplete.json()["error"]["details"] == {"remaining_items": 2}
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "ready"
    assert repeated.status_code == 200
    assert [item["number"] for item in page["items"]] == [1, 2]
    assert missing.status_code == 404


async def test_a_manifest_carries_accepted_geometry_in_the_shared_format(
    database: None,
) -> None:
    token = await _user("owner")
    broker = Broker()
    async with _client() as client:
        project = await _project(client, token, LEARNING)
        box = {
            "id": "bottle-1",
            "class_id": project["class_id"],
            "geometry": {"type": "rectangle", "coordinates": [10.0, 20.0, 30.0, 40.0]},
            "attributes": {},
        }
        await _annotate_everything(client, token, project["id"], [box])
        await _relay(broker)

    [run] = await _runs(project["id"])
    training = _manifest(run, "training")
    async with async_session_factory() as session:
        resolutions = {
            resolution.id: resolution
            for resolution in await session.scalars(select(ResolvedAnnotation))
        }
    assert len(training["annotations"]) == 2
    for annotation in training["annotations"]:
        assert annotation["bbox"] == [10.0, 20.0, 30.0, 40.0]
        assert annotation["category_id"] == 0
        assert annotation["origin"] == "FULL_IMAGE"
        assert annotation["resolution_id"] in resolutions
        assert annotation["image_id"] in {image["id"] for image in training["images"]}
    stored = (
        get_settings().media_root / run.snapshots["training"]["path"]
    ).read_bytes()
    assert json.loads(stored) == training
