"""Label imports and seeded assignments over real HTTP."""

import hashlib
import json
import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, func, select

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
    AssignmentStatus,
    BatchItem,
    ItemStatus,
)
from dada_api.models.dataset import DatasetSplit
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.label_import import (
    AnnotationImport,
    AnnotationImportFile,
    ImportedSeedDocument,
)
from dada_api.models.media import ContentObject, Media
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.user import User
from dada_api.services import datasets, selection

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase41-import-password"
MEDIA_COUNT = 6
DRAFT = {
    "name": "Road defects",
    "description": None,
    "task_type": "detection",
    "test_set_size": 2,
    "validation_set_size": 1,
    "iteration_batch_size": 2,
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


async def _create_user(username: str) -> User:
    """Persist a user with the shared test password."""
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


def _path(index: int) -> str:
    """Return the relative path of the test image with this index."""
    return f"camera-a/frame-{index:04d}"


async def _add_media(project_id: str) -> None:
    """Persist verified 640x480 media rows directly."""
    async with async_session_factory() as session:
        for index in range(MEDIA_COUNT):
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
                    relative_path=f"{_path(index)}.jpg",
                )
            )
        await session.commit()


async def _prepared_project(
    client: httpx.AsyncClient,
    token: str,
    *,
    task_type: str = "detection",
    prepare: bool = True,
) -> dict:
    """Create a project with two classes and media, prepared unless told not to."""
    created = await client.post(
        "/api/v1/projects",
        headers=_auth(token),
        json={**DRAFT, "task_type": task_type},
    )
    assert created.status_code == 201, created.text
    project = created.json()
    class_ids = []
    for order, name in enumerate(("pothole", "crack")):
        added = await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(token),
            json={"name": name, "color": "#FF0000", "display_order": order},
        )
        assert added.status_code == 201, added.text
        class_ids.append(added.json()["id"])
    project["class_ids"] = class_ids
    await _add_media(project["id"])
    if prepare:
        prepared = await client.post(
            f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )
        assert prepared.status_code == 201, prepared.text
    return project


def _manifest(files: dict[str, bytes]) -> list[dict]:
    """Describe label files keyed by relative path."""
    return [
        {
            "client_file_id": f"file-{position}",
            "relative_path": path,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for position, (path, data) in enumerate(files.items())
    ]


async def _import(
    client: httpx.AsyncClient,
    token: str,
    project_id: str,
    files: dict[str, bytes],
    *,
    label_format: str = "yolo_detection",
) -> dict:
    """Create an import, upload every file, and validate it."""
    created = await client.post(
        f"/api/v1/projects/{project_id}/annotation-imports",
        headers=_auth(token),
        json={"format": label_format, "files": _manifest(files)},
    )
    assert created.status_code == 201, created.text
    import_id = created.json()["id"]
    for position, data in enumerate(files.values()):
        uploaded = await client.post(
            f"/api/v1/annotation-imports/{import_id}/files/file-{position}",
            headers={**_auth(token), "Content-Type": "application/octet-stream"},
            content=data,
        )
        assert uploaded.status_code == 200, uploaded.text
    validated = await client.post(
        f"/api/v1/annotation-imports/{import_id}/validate", headers=_auth(token)
    )
    assert validated.status_code == 200, validated.text
    return validated.json()


def _yolo_labels() -> dict[str, bytes]:
    """Return one YOLO sidecar per image, the last one explicitly empty."""
    labels = {
        f"{_path(index)}.txt": f"{index % 2} 0.5 0.5 0.25 0.5\n".encode()
        for index in range(MEDIA_COUNT - 1)
    }
    labels[f"{_path(MEDIA_COUNT - 1)}.txt"] = b""
    return labels


async def test_an_accepted_import_seeds_every_assignment_without_submitting(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("annie")
    await _create_user("bob")
    token = await _token("owner")

    async with _client() as client:
        project = await _prepared_project(client, token, prepare=False)
        annotator_ids = []
        for username in ("annie", "bob"):
            added = await client.post(
                f"/api/v1/projects/{project['id']}/members",
                headers=_auth(token),
                json={"username": username, "role": "annotator"},
            )
            annotator_ids.append(added.json()["user_id"])
        await client.put(
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
        prepared = await client.post(
            f"/api/v1/projects/{project['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )
        assert prepared.status_code == 201, prepared.text

        validated = await _import(client, token, project["id"], _yolo_labels())
        pending = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        accepted = await client.post(
            f"/api/v1/annotation-imports/{validated['id']}/accept",
            headers=_auth(token),
        )
        activated = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        batches = await client.get(
            f"/api/v1/projects/{project['id']}/batches", headers=_auth(token)
        )
        started = [
            await client.post(
                f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
                headers=_auth(token),
            )
            for batch in batches.json()["items"]
        ]

    assert validated["status"] == "validated"
    assert validated["report"] == {
        "labelled_images": MEDIA_COUNT,
        "objects": MEDIA_COUNT - 1,
        "unlabelled_images": 0,
        "errors": [],
    }
    assert pending.status_code == 409
    assert pending.json()["error"]["details"]["missing"] == ["label_import"]
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert activated.status_code == 200, activated.text
    assert all(response.status_code == 200 for response in started)
    assert all(response.json()["submitted_assignments"] == 0 for response in started)

    async with async_session_factory() as session:
        seeds = {
            seed.media_id: seed
            for seed in await session.scalars(select(ImportedSeedDocument))
        }
        rows = (
            await session.execute(
                select(AnnotationAssignment, BatchItem.media_id).join(
                    BatchItem, BatchItem.id == AnnotationAssignment.batch_item_id
                )
            )
        ).all()
        resolved = await session.scalar(
            select(func.count())
            .select_from(BatchItem)
            .where(BatchItem.status == ItemStatus.resolved)
        )
        stored = await session.get(Project, project["id"])
        assert stored is not None
        ready = await datasets.first_acquisition_ready(session, stored)

    assert len(seeds) == MEDIA_COUNT
    assert rows
    for assignment, media_id in rows:
        assert assignment.seed_document_id == seeds[media_id].id
        assert assignment.draft == seeds[media_id].document["objects"]
        assert assignment.status == AssignmentStatus.pending
    assert {assignment.annotator_id for assignment, _ in rows} == set(annotator_ids)
    assert resolved == 0
    assert ready is False

    rectangle = next(
        seed.document["objects"][0]
        for seed in seeds.values()
        if seed.document["objects"]
    )
    assert rectangle["geometry"]["type"] == "rectangle"
    assert rectangle["geometry"]["coordinates"] == pytest.approx(
        [240.0, 120.0, 160.0, 240.0]
    )
    assert rectangle["class_id"] in project["class_ids"]


async def test_an_import_records_its_provenance_without_label_content(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    labels = _yolo_labels()

    async with _client() as client:
        project = await _prepared_project(client, token)
        validated = await _import(client, token, project["id"], labels)
        await client.post(
            f"/api/v1/annotation-imports/{validated['id']}/accept",
            headers=_auth(token),
        )
        reread = await client.get(
            f"/api/v1/annotation-imports/{validated['id']}", headers=_auth(token)
        )

    body = reread.json()
    assert body["parser_version"] == "yolo-detection/1"
    assert body["accepted_at"] is not None
    assert {item["sha256"] for item in body["files"]} == {
        hashlib.sha256(data).hexdigest() for data in labels.values()
    }
    assert all(item["received"] for item in body["files"])

    async with async_session_factory() as session:
        stored = await session.get(AnnotationImport, validated["id"])
        assert stored is not None
        media_ids = list(
            await session.scalars(
                select(Media.id)
                .where(Media.project_id == project["id"])
                .order_by(Media.relative_path, Media.id)
            )
        )
        contents = set(await session.scalars(select(AnnotationImportFile.content)))
        audit = list(
            await session.scalars(
                select(AuditEntry)
                .where(AuditEntry.target_type == "annotation_import")
                .order_by(AuditEntry.created_at)
            )
        )

    assert stored.class_index_map == {
        "0": project["class_ids"][0],
        "1": project["class_ids"][1],
    }
    assert stored.media_fingerprint == selection.fingerprint(media_ids)
    assert contents == set(labels.values())
    assert [entry.action for entry in audit] == [
        "label_import.created",
        "label_import.validated",
        "label_import.accepted",
    ]
    serialized = json.dumps([entry.after for entry in audit])
    assert "coordinates" not in serialized
    assert "0.5 0.5" not in serialized


async def test_invalid_labels_reject_the_import_until_discarded(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _prepared_project(client, token)
        rejected = await _import(
            client,
            token,
            project["id"],
            {
                f"{_path(0)}.txt": b"7 0.5 0.5 0.1 0.1\n",
                "camera-b/unknown.txt": b"0 0.5 0.5 0.1 0.1\n",
                f"{_path(1)}.txt": b"0 0.9 0.5 0.4 0.1\n",
            },
        )
        accept = await client.post(
            f"/api/v1/annotation-imports/{rejected['id']}/accept",
            headers=_auth(token),
        )
        activation = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        discarded = await client.delete(
            f"/api/v1/annotation-imports/{rejected['id']}", headers=_auth(token)
        )
        replaced = await _import(client, token, project["id"], _yolo_labels())

    assert rejected["status"] == "rejected"
    assert {error["code"] for error in rejected["report"]["errors"]} == {
        "unknown_class_index",
        "unmatched_path",
        "invalid_geometry",
    }
    assert accept.status_code == 409
    assert accept.json()["error"]["code"] == "import_not_valid"
    assert activation.json()["error"]["details"]["missing"] == ["label_import"]
    assert discarded.status_code == 204
    assert replaced["status"] == "validated"

    async with async_session_factory() as session:
        seeds = await session.scalar(
            select(func.count()).select_from(ImportedSeedDocument)
        )

    assert seeds == 0


async def test_import_preconditions_and_file_checks(database: None) -> None:
    await _create_user("owner")
    await _create_user("anna")
    token = await _token("owner")
    labels = {f"{_path(0)}.txt": b"0 0.5 0.5 0.1 0.1\n"}

    async with _client() as client:
        unprepared = await _prepared_project(client, token, prepare=False)
        before_prepare = await client.post(
            f"/api/v1/projects/{unprepared['id']}/annotation-imports",
            headers=_auth(token),
            json={"format": "yolo_detection", "files": _manifest(labels)},
        )
        await client.post(
            f"/api/v1/projects/{unprepared['id']}/dataset-layout/prepare",
            headers=_auth(token),
        )
        wrong_format = await client.post(
            f"/api/v1/projects/{unprepared['id']}/annotation-imports",
            headers=_auth(token),
            json={"format": "coco_segmentation", "files": _manifest(labels)},
        )
        created = await client.post(
            f"/api/v1/projects/{unprepared['id']}/annotation-imports",
            headers=_auth(token),
            json={"format": "yolo_detection", "files": _manifest(labels)},
        )
        second = await client.post(
            f"/api/v1/projects/{unprepared['id']}/annotation-imports",
            headers=_auth(token),
            json={"format": "yolo_detection", "files": _manifest(labels)},
        )
        import_id = created.json()["id"]
        incomplete = await client.post(
            f"/api/v1/annotation-imports/{import_id}/validate", headers=_auth(token)
        )
        corrupt = await client.post(
            f"/api/v1/annotation-imports/{import_id}/files/file-0",
            headers=_auth(token),
            content=b"1 0.5 0.5 0.1 0.1\n",
        )

        await client.post(
            f"/api/v1/projects/{unprepared['id']}/members",
            headers=_auth(token),
            json={"username": "anna", "role": "annotator"},
        )
        annotator_token = await _token("anna")
        annotator_read = await client.get(
            f"/api/v1/annotation-imports/{import_id}",
            headers=_auth(annotator_token),
        )
        annotator_create = await client.post(
            f"/api/v1/projects/{unprepared['id']}/annotation-imports",
            headers=_auth(annotator_token),
            json={"format": "yolo_detection", "files": _manifest(labels)},
        )

    assert before_prepare.json()["error"]["code"] == "dataset_not_prepared"
    assert wrong_format.status_code == 422
    assert wrong_format.json()["error"]["code"] == "import_not_supported"
    assert created.status_code == 201, created.text
    assert second.json()["error"]["code"] == "import_already_exists"
    assert incomplete.json()["error"]["code"] == "import_files_incomplete"
    assert incomplete.json()["error"]["details"]["pending"] == ["file-0"]
    assert corrupt.status_code == 422
    assert corrupt.json()["error"]["code"] == "checksum_mismatch"
    assert annotator_read.status_code == 403
    assert annotator_create.status_code == 403


async def test_a_coco_import_seeds_segmentation_polygons(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")
    document = json.dumps(
        {
            "images": [
                {"id": 10, "file_name": f"{_path(0)}.jpg"},
                {"id": 11, "file_name": f"{_path(1)}.jpg"},
            ],
            "annotations": [
                {
                    "image_id": 10,
                    "category_id": 1,
                    "segmentation": [[10, 10, 100, 10, 100, 80, 10, 80]],
                }
            ],
            "categories": [{"id": 0, "name": "pothole"}, {"id": 1, "name": "crack"}],
        }
    ).encode()

    async with _client() as client:
        project = await _prepared_project(client, token, task_type="segmentation")
        validated = await _import(
            client,
            token,
            project["id"],
            {"labels/instances.json": document},
            label_format="coco_segmentation",
        )
        accepted = await client.post(
            f"/api/v1/annotation-imports/{validated['id']}/accept",
            headers=_auth(token),
        )

    assert validated["report"] == {
        "labelled_images": 2,
        "objects": 1,
        "unlabelled_images": MEDIA_COUNT - 2,
        "errors": [],
    }
    assert accepted.json()["status"] == "accepted"

    async with async_session_factory() as session:
        documents = [
            seed.document
            for seed in await session.scalars(select(ImportedSeedDocument))
        ]

    polygons = [item for document in documents for item in document["objects"]]
    assert len(documents) == 2
    assert polygons[0]["class_id"] == project["class_ids"][1]
    assert polygons[0]["geometry"] == {
        "type": "polygon",
        "coordinates": [[10.0, 10.0, 100.0, 10.0, 100.0, 80.0, 10.0, 80.0]],
    }


async def test_an_accepted_import_is_final_until_the_dataset_is_reset(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _prepared_project(client, token)
        validated = await _import(client, token, project["id"], _yolo_labels())
        await client.post(
            f"/api/v1/annotation-imports/{validated['id']}/accept",
            headers=_auth(token),
        )
        discard = await client.delete(
            f"/api/v1/annotation-imports/{validated['id']}", headers=_auth(token)
        )
        reset = await client.delete(
            f"/api/v1/projects/{project['id']}/dataset-layout", headers=_auth(token)
        )
        gone = await client.get(
            f"/api/v1/annotation-imports/{validated['id']}", headers=_auth(token)
        )

    assert discard.status_code == 409
    assert discard.json()["error"]["code"] == "import_accepted"
    assert reset.status_code == 204
    assert gone.status_code == 404

    async with async_session_factory() as session:
        for model in (AnnotationImport, AnnotationImportFile, ImportedSeedDocument):
            assert await session.scalar(select(func.count()).select_from(model)) == 0


async def test_a_seeded_submission_is_the_annotators_and_deletion_removes_it(
    database: None,
) -> None:
    owner_id = (await _create_user("owner")).id
    token = await _token("owner")

    async with _client() as client:
        project = await _prepared_project(client, token)
        validated = await _import(client, token, project["id"], _yolo_labels())
        await client.post(
            f"/api/v1/annotation-imports/{validated['id']}/accept",
            headers=_auth(token),
        )
        await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        batches = await client.get(
            f"/api/v1/projects/{project['id']}/batches", headers=_auth(token)
        )
        for batch in batches.json()["items"]:
            await client.post(
                f"/api/v1/projects/{project['id']}/batches/{batch['id']}/start",
                headers=_auth(token),
            )
        queue = await client.get(
            f"/api/v1/projects/{project['id']}/assignments", headers=_auth(token)
        )
        first = queue.json()["items"][0]
        opened = await client.get(
            f"/api/v1/projects/{project['id']}/assignments/{first['id']}",
            headers=_auth(token),
        )
        submitted = await client.post(
            f"/api/v1/projects/{project['id']}/assignments/{first['id']}/submit",
            headers=_auth(token),
            json={"version": 1, "objects": opened.json()["objects"]},
        )

        async with async_session_factory() as session:
            seed = await session.scalar(
                select(ImportedSeedDocument).where(
                    ImportedSeedDocument.media_id == first["media_id"]
                )
            )
            submission = await session.get(
                AnnotationSubmission, submitted.json()["submission_id"]
            )

        deleted = await client.delete(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )

    assert first["seeded_from_import"] is True
    assert opened.json()["objects"] == seed.document["objects"]
    assert submitted.status_code == 200, submitted.text
    assert submission.seed_document_id == seed.id
    assert submission.submitted_by == owner_id
    assert submission.objects == seed.document["objects"]
    assert deleted.status_code == 204, deleted.text

    async with async_session_factory() as session:
        for model in (
            AnnotationImport,
            AnnotationImportFile,
            ImportedSeedDocument,
            AnnotationAssignment,
            AnnotationSubmission,
            ResolvedAnnotation,
            BatchItem,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
