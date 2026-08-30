"""Phase 2 project setup, membership, and policy behaviour over real HTTP."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, select

from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation_policy import (
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.bootstrap import BootstrapRecord
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.project import Project, ProjectClass, ProjectMember, ProjectRole
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User
from dada_api.services import projects as project_service

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase2-test-password"


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def _reset_database() -> None:
    """Remove every record the Phase 2 tests create."""
    async with async_session_factory() as session:
        await session.execute(delete(IdempotencyRecord))
        await session.execute(delete(AuditEntry))
        await session.execute(delete(AnnotationPolicyAnnotator))
        await session.execute(delete(AnnotationPolicyDefault))
        await session.execute(delete(ProjectClass))
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


DRAFT = {
    "name": "Road defects",
    "description": None,
    "task_type": "detection",
    "initial_training_size": 10,
    "test_set_size": 5,
    "iteration_batch_size": 5,
}


async def _create_project(
    client: httpx.AsyncClient, token: str, **overrides: object
) -> dict:
    """Create a project through the API and return its representation."""
    response = await client.post(
        "/api/v1/projects",
        headers={**_auth(token), "Idempotency-Key": "create-project-key"},
        json={**DRAFT, **overrides},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_creation_makes_the_creator_owner_and_readable(
    database: None,
) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        read = await client.get(
            f"/api/v1/projects/{project['id']}", headers=_auth(token)
        )
        listed = await client.get("/api/v1/projects", headers=_auth(token))

    assert read.status_code == 200
    assert listed.json()["items"][0]["id"] == project["id"]
    assert listed.json()["next_cursor"] is None

    async with async_session_factory() as session:
        role = await session.scalar(
            select(ProjectMember.role).where(ProjectMember.project_id == project["id"])
        )
    assert role is ProjectRole.owner


async def test_creation_is_idempotent_for_a_repeated_key(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        first = await _create_project(client, token)
        replay = await client.post(
            "/api/v1/projects",
            headers={**_auth(token), "Idempotency-Key": "create-project-key"},
            json=DRAFT,
        )

    assert replay.status_code == 201
    assert replay.json()["id"] == first["id"]
    assert replay.headers["idempotency-replayed"] == "true"


async def test_versioned_update_rejects_a_stale_version(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        updated = await client.patch(
            f"/api/v1/projects/{project['id']}",
            headers=_auth(token),
            json={"name": "Renamed", "version": project["version"]},
        )
        stale = await client.patch(
            f"/api/v1/projects/{project['id']}",
            headers=_auth(token),
            json={"name": "Again", "version": project["version"]},
        )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["version"] == project["version"] + 1
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


async def test_list_pages_through_an_opaque_cursor(
    database: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _create_user("owner")
    token = await _token("owner")
    monkeypatch.setattr(project_service, "PAGE_SIZE", 2)

    async with _client() as client:
        for index in range(3):
            response = await client.post(
                "/api/v1/projects",
                headers={**_auth(token), "Idempotency-Key": f"page-key-{index}"},
                json={**DRAFT, "name": f"Project {index}"},
            )
            assert response.status_code == 201

        first = await client.get("/api/v1/projects", headers=_auth(token))
        cursor = first.json()["next_cursor"]
        second = await client.get(
            "/api/v1/projects", headers=_auth(token), params={"cursor": cursor}
        )
        tampered = await client.get(
            "/api/v1/projects", headers=_auth(token), params={"cursor": "not-a-cursor"}
        )

    assert len(first.json()["items"]) == 2
    assert cursor is not None
    assert len(second.json()["items"]) == 1
    assert second.json()["next_cursor"] is None
    first_ids = {item["id"] for item in first.json()["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert not first_ids & second_ids
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "invalid_cursor"


async def test_classes_enforce_uniqueness_colour_and_version(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        base = f"/api/v1/projects/{project['id']}/classes"
        created = await client.post(
            base,
            headers=_auth(token),
            json={"name": "pothole", "color": "#FF8800", "display_order": 0},
        )
        duplicate_name = await client.post(
            base,
            headers=_auth(token),
            json={"name": "pothole", "color": "#00FF00", "display_order": 1},
        )
        duplicate_order = await client.post(
            base,
            headers=_auth(token),
            json={"name": "crack", "color": "#00FF00", "display_order": 0},
        )
        bad_colour = await client.post(
            base,
            headers=_auth(token),
            json={"name": "crack", "color": "orange", "display_order": 1},
        )
        item = created.json()
        renamed = await client.patch(
            f"{base}/{item['id']}",
            headers=_auth(token),
            json={"name": "deep pothole", "version": item["version"]},
        )
        stale = await client.patch(
            f"{base}/{item['id']}",
            headers=_auth(token),
            json={"name": "other", "version": item["version"]},
        )
        listed = await client.get(base, headers=_auth(token))
        removed = await client.delete(f"{base}/{item['id']}", headers=_auth(token))

    assert created.status_code == 201
    assert duplicate_name.status_code == 409
    assert duplicate_name.json()["error"]["code"] == "duplicate_class_name"
    assert duplicate_order.status_code == 409
    assert duplicate_order.json()["error"]["code"] == "duplicate_display_order"
    assert bad_colour.status_code == 422
    assert renamed.status_code == 200
    assert renamed.json()["version"] == item["version"] + 1
    assert stale.status_code == 409
    assert listed.json()["items"][0]["name"] == "deep pothole"
    assert removed.status_code == 204


async def test_members_are_added_by_username_and_audited(database: None) -> None:
    await _create_user("owner")
    await _create_user("ana")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        base = f"/api/v1/projects/{project['id']}/members"
        added = await client.post(
            base, headers=_auth(token), json={"username": "ana", "role": "annotator"}
        )
        duplicate = await client.post(
            base, headers=_auth(token), json={"username": "ana", "role": "viewer"}
        )
        unknown = await client.post(
            base, headers=_auth(token), json={"username": "ghost", "role": "viewer"}
        )
        listed = await client.get(base, headers=_auth(token))

    assert added.status_code == 201
    assert added.json()["username"] == "ana"
    assert added.json()["role"] == "annotator"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "duplicate_member"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "user_not_found"
    assert {item["username"] for item in listed.json()["items"]} == {"owner", "ana"}

    async with async_session_factory() as session:
        entry = await session.scalar(
            select(AuditEntry).where(AuditEntry.action == "member.added")
        )
    assert entry is not None
    assert entry.after == {"user_id": added.json()["user_id"], "role": "annotator"}
    assert entry.trace_id is not None


async def test_the_sole_owner_cannot_be_removed_or_demoted(database: None) -> None:
    owner = await _create_user("owner")
    await _create_user("ana")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        base = f"/api/v1/projects/{project['id']}/members"
        await client.post(
            base, headers=_auth(token), json={"username": "ana", "role": "annotator"}
        )
        demote = await client.patch(
            f"{base}/{owner.id}", headers=_auth(token), json={"role": "viewer"}
        )
        remove = await client.delete(f"{base}/{owner.id}", headers=_auth(token))
        promote = await client.post(
            base, headers=_auth(token), json={"username": "ana", "role": "owner"}
        )

    assert demote.status_code == 409
    assert demote.json()["error"]["code"] == "sole_owner_protected"
    assert remove.status_code == 409
    assert promote.status_code == 409


async def test_consensus_policy_requires_a_valid_group(database: None) -> None:
    owner = await _create_user("owner")
    ana = await _create_user("ana")
    bruno = await _create_user("bruno")
    outsider = await _create_user("outsider")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        members = f"/api/v1/projects/{project['id']}/members"
        policy_url = f"/api/v1/projects/{project['id']}/annotation-policy"
        await client.post(
            members, headers=_auth(token), json={"username": "ana", "role": "annotator"}
        )
        await client.post(
            members, headers=_auth(token), json={"username": "bruno", "role": "viewer"}
        )

        current = await client.get(policy_url, headers=_auth(token))
        version = current.json()["version"]

        too_small = await client.put(
            policy_url,
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": [ana.id],
                "resolver": "two_stage_box_fusion",
                "version": version,
            },
        )
        non_member = await client.put(
            policy_url,
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": [ana.id, outsider.id],
                "resolver": "two_stage_box_fusion",
                "version": version,
            },
        )
        viewer_member = await client.put(
            policy_url,
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": [ana.id, bruno.id],
                "resolver": "two_stage_box_fusion",
                "version": version,
            },
        )
        wrong_resolver = await client.put(
            policy_url,
            headers=_auth(token),
            json={
                "mode": "consensus",
                "annotator_ids": [owner.id, ana.id],
                "resolver": "majority_vote",
                "version": version,
            },
        )

    assert current.status_code == 200
    assert current.json()["mode"] == "single"
    assert too_small.status_code == 422
    assert too_small.json()["error"]["code"] == "invalid_consensus_group"
    assert non_member.status_code == 422
    assert non_member.json()["error"]["details"]["not_members"] == [outsider.id]
    assert viewer_member.status_code == 422
    assert viewer_member.json()["error"]["details"]["not_allowed"] == [bruno.id]
    assert wrong_resolver.status_code == 422
    assert wrong_resolver.json()["error"]["code"] == "unsupported_resolver"


async def test_consensus_policy_saves_and_rejects_a_stale_version(
    database: None,
) -> None:
    owner = await _create_user("owner")
    ana = await _create_user("ana")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        members = f"/api/v1/projects/{project['id']}/members"
        policy_url = f"/api/v1/projects/{project['id']}/annotation-policy"
        await client.post(
            members, headers=_auth(token), json={"username": "ana", "role": "annotator"}
        )
        body = {
            "mode": "consensus",
            "annotator_ids": [owner.id, ana.id],
            "resolver": "two_stage_box_fusion",
            "review_thresholds": {"agreement": 0.75},
            "version": 1,
        }
        saved = await client.put(policy_url, headers=_auth(token), json=body)
        stale = await client.put(policy_url, headers=_auth(token), json=body)
        read_back = await client.get(policy_url, headers=_auth(token))

    assert saved.status_code == 200
    assert saved.json()["mode"] == "consensus"
    assert saved.json()["annotator_ids"] == [owner.id, ana.id]
    assert saved.json()["version"] == 2
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert read_back.json()["review_thresholds"] == {"agreement": 0.75}

    async with async_session_factory() as session:
        entry = await session.scalar(
            select(AuditEntry).where(AuditEntry.action == "annotation_policy.updated")
        )
    assert entry is not None
    assert entry.before["mode"] == "single"
    assert entry.after["annotator_ids"] == [owner.id, ana.id]


async def test_single_mode_refuses_a_resolver(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        response = await client.put(
            f"/api/v1/projects/{project['id']}/annotation-policy",
            headers=_auth(token),
            json={"mode": "single", "resolver": "majority_vote", "version": 1},
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_resolver"


async def test_activation_reports_missing_prerequisites(database: None) -> None:
    await _create_user("owner")
    token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, token)
        empty = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )
        await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(token),
            json={"name": "pothole", "color": "#FF8800", "display_order": 0},
        )
        with_classes = await client.post(
            f"/api/v1/projects/{project['id']}/activate", headers=_auth(token)
        )

    assert empty.status_code == 409
    assert empty.json()["error"]["code"] == "activation_incomplete"
    assert "classes" in empty.json()["error"]["details"]["missing"]
    assert "media" in empty.json()["error"]["details"]["missing"]
    assert with_classes.status_code == 409
    assert with_classes.json()["error"]["details"]["missing"] == ["media"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (ProjectRole.manager, 200),
        (ProjectRole.annotator, 403),
        (ProjectRole.viewer, 403),
    ],
)
async def test_policy_management_follows_the_role_matrix(
    database: None, role: ProjectRole, expected: int
) -> None:
    await _create_user("owner")
    await _create_user("ana")
    owner_token = await _token("owner")

    async with _client() as client:
        project = await _create_project(client, owner_token)
        await client.post(
            f"/api/v1/projects/{project['id']}/members",
            headers=_auth(owner_token),
            json={"username": "ana", "role": role.value},
        )
        ana_token = await _token("ana")
        response = await client.put(
            f"/api/v1/projects/{project['id']}/annotation-policy",
            headers=_auth(ana_token),
            json={"mode": "single", "version": 1},
        )

    assert response.status_code == expected


async def test_administrator_manages_a_project_without_membership(
    database: None,
) -> None:
    await _create_user("owner")
    await _create_user("root", administrator=True)
    owner_token = await _token("owner")
    admin_token = await _token("root")

    async with _client() as client:
        project = await _create_project(client, owner_token)
        response = await client.post(
            f"/api/v1/projects/{project['id']}/classes",
            headers=_auth(admin_token),
            json={"name": "pothole", "color": "#FF8800", "display_order": 0},
        )
        listed = await client.get("/api/v1/projects", headers=_auth(admin_token))

    assert response.status_code == 201
    assert listed.json()["items"][0]["owner_id"] == project["owner_id"]
