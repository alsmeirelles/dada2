"""Phase 4 global user administration and self-service password over real HTTP."""

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, select

from dada_api.api.v1.endpoints.auth import REFRESH_COOKIE_NAME
from dada_api.core.security import hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.annotation_policy import (
    AnnotationPolicyAnnotator,
    AnnotationPolicyDefault,
)
from dada_api.models.audit import AuditEntry
from dada_api.models.bootstrap import SINGLETON_ID, BootstrapRecord
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.project import Project, ProjectClass, ProjectMember
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase4-test-password"
REPLACEMENT = "phase4-replacement-password"
TOO_SHORT = "leaky7"


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
            version=1,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _token(username: str, password: str = PASSWORD) -> str:
    """Log in and return the access token."""
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token",
            json={"username": username, "password": password},
        )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


async def _login(username: str, password: str = PASSWORD) -> httpx.Response:
    """Attempt a login and return the raw response."""
    async with _client() as client:
        return await client.post(
            "/api/v1/auth/token",
            json={"username": username, "password": password},
        )


def _auth(token: str) -> dict[str, str]:
    """Return the bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


NEW_USER = {
    "username": "annie",
    "display_name": "Annie",
    "password": PASSWORD,
}


async def test_administrator_creates_reads_and_lists_users(database: None) -> None:
    await _create_user("root", administrator=True)
    token = await _token("root")

    async with _client() as client:
        created = await client.post(
            "/api/v1/users", headers=_auth(token), json=NEW_USER
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["username"] == "annie"
        assert body["version"] == 1
        assert body["is_active"] is True
        assert body["is_administrator"] is False
        assert "password" not in created.text

        read = await client.get(f"/api/v1/users/{body['id']}", headers=_auth(token))
        assert read.status_code == 200
        assert read.json()["username"] == "annie"

        listed = await client.get("/api/v1/users", headers=_auth(token))
        assert listed.status_code == 200
        page = listed.json()
        assert [item["username"] for item in page["items"]] == ["annie", "root"]
        assert page["next_cursor"] is None


async def test_duplicate_username_is_refused(database: None) -> None:
    await _create_user("root", administrator=True)
    await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        response = await client.post(
            "/api/v1/users", headers=_auth(token), json=NEW_USER
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "username_taken"


async def test_list_filters_by_active_state(database: None) -> None:
    root = await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        disabled = await client.patch(
            f"/api/v1/users/{annie.id}",
            headers=_auth(token),
            json={"version": 1, "is_active": False},
        )
        assert disabled.status_code == 200

        active = await client.get(
            "/api/v1/users", headers=_auth(token), params={"active": "true"}
        )
        inactive = await client.get(
            "/api/v1/users", headers=_auth(token), params={"active": "false"}
        )

    assert [item["id"] for item in active.json()["items"]] == [root.id]
    assert [item["id"] for item in inactive.json()["items"]] == [annie.id]


async def test_update_is_versioned_and_username_is_immutable(database: None) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        updated = await client.patch(
            f"/api/v1/users/{annie.id}",
            headers=_auth(token),
            json={"version": 1, "display_name": "Annie B", "username": "renamed"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["display_name"] == "Annie B"
        assert updated.json()["username"] == "annie"
        assert updated.json()["version"] == 2

        stale = await client.patch(
            f"/api/v1/users/{annie.id}",
            headers=_auth(token),
            json={"version": 1, "display_name": "Annie C"},
        )

    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


async def test_password_reset_replaces_credentials_and_revokes_sessions(
    database: None,
) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        login = await client.post(
            "/api/v1/auth/token",
            json={"username": "annie", "password": PASSWORD},
        )
        refresh_token = login.cookies[REFRESH_COOKIE_NAME]

        reset = await client.post(
            f"/api/v1/users/{annie.id}/reset-password",
            headers=_auth(token),
            json={"new_password": REPLACEMENT},
        )
        assert reset.status_code == 204

        rotated = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"{REFRESH_COOKIE_NAME}={refresh_token}"},
        )

    assert rotated.status_code == 401
    assert (await _login("annie", PASSWORD)).status_code == 401
    assert (await _login("annie", REPLACEMENT)).status_code == 200


async def test_deactivation_blocks_login_and_existing_bearer_tokens(
    database: None,
) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    admin_token = await _token("root")
    annie_token = await _token("annie")

    async with _client() as client:
        before = await client.get("/api/v1/auth/me", headers=_auth(annie_token))
        assert before.status_code == 200

        disabled = await client.patch(
            f"/api/v1/users/{annie.id}",
            headers=_auth(admin_token),
            json={"version": 1, "is_active": False},
        )
        assert disabled.status_code == 200
        assert disabled.json()["is_active"] is False

        after = await client.get("/api/v1/auth/me", headers=_auth(annie_token))

    assert after.status_code == 401
    assert (await _login("annie")).status_code == 401


async def test_unreferenced_user_is_deleted_with_a_matching_if_match(
    database: None,
) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        response = await client.delete(
            f"/api/v1/users/{annie.id}",
            headers={**_auth(token), "If-Match": '"1"'},
        )
        assert response.status_code == 204

        missing = await client.get(f"/api/v1/users/{annie.id}", headers=_auth(token))

    assert missing.status_code == 404


async def test_if_match_is_required_and_must_be_current(database: None) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        missing = await client.delete(f"/api/v1/users/{annie.id}", headers=_auth(token))
        unparseable = await client.delete(
            f"/api/v1/users/{annie.id}",
            headers={**_auth(token), "If-Match": "not-a-version"},
        )
        stale = await client.delete(
            f"/api/v1/users/{annie.id}",
            headers={**_auth(token), "If-Match": "7"},
        )

    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "invalid_if_match"
    assert unparseable.status_code == 400
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"


async def test_project_owner_cannot_be_deleted(database: None) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    owner_token = await _token("annie")
    admin_token = await _token("root")

    async with _client() as client:
        created = await client.post(
            "/api/v1/projects",
            headers=_auth(owner_token),
            json={
                "name": "Road defects",
                "description": None,
                "task_type": "detection",
                "initial_training_size": 10,
                "test_set_size": 5,
                "iteration_batch_size": 5,
            },
        )
        assert created.status_code == 201, created.text

        response = await client.delete(
            f"/api/v1/users/{annie.id}",
            headers={**_auth(admin_token), "If-Match": "1"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_in_use"


async def test_audit_author_cannot_be_deleted(database: None) -> None:
    await _create_user("root", administrator=True)
    manager = await _create_user("mary", administrator=True)
    admin_token = await _token("root")
    manager_token = await _token("mary")

    async with _client() as client:
        created = await client.post(
            "/api/v1/users",
            headers=_auth(manager_token),
            json={**NEW_USER, "username": "created-by-mary"},
        )
        assert created.status_code == 201, created.text

        demote = await client.patch(
            f"/api/v1/users/{manager.id}",
            headers=_auth(admin_token),
            json={"version": 1, "is_administrator": False},
        )
        assert demote.status_code == 200

        response = await client.delete(
            f"/api/v1/users/{manager.id}",
            headers={**_auth(admin_token), "If-Match": "2"},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_in_use"


async def test_bootstrap_administrator_cannot_be_deleted(database: None) -> None:
    root = await _create_user("root", administrator=True)
    other = await _create_user("second", administrator=True)
    async with async_session_factory() as session:
        session.add(BootstrapRecord(id=SINGLETON_ID, user_id=root.id))
        await session.commit()

    token = await _token("second")
    async with _client() as client:
        response = await client.delete(
            f"/api/v1/users/{root.id}",
            headers={**_auth(token), "If-Match": "1"},
        )

    assert other.id != root.id
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_in_use"


async def test_last_active_administrator_is_protected(database: None) -> None:
    root = await _create_user("root", administrator=True)
    await _create_user("annie")
    token = await _token("root")

    async with _client() as client:
        demote_last = await client.patch(
            f"/api/v1/users/{root.id}",
            headers=_auth(token),
            json={"version": 1, "is_administrator": False},
        )
        deactivate_last = await client.patch(
            f"/api/v1/users/{root.id}",
            headers=_auth(token),
            json={"version": 1, "is_active": False},
        )
        delete_last = await client.delete(
            f"/api/v1/users/{root.id}",
            headers={**_auth(token), "If-Match": "1"},
        )

    for response in (demote_last, deactivate_last, delete_last):
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "last_active_administrator"


async def test_administrator_cannot_withdraw_their_own_access(database: None) -> None:
    root = await _create_user("root", administrator=True)
    await _create_user("second", administrator=True)
    token = await _token("root")

    async with _client() as client:
        demote = await client.patch(
            f"/api/v1/users/{root.id}",
            headers=_auth(token),
            json={"version": 1, "is_administrator": False},
        )
        deactivate = await client.patch(
            f"/api/v1/users/{root.id}",
            headers=_auth(token),
            json={"version": 1, "is_active": False},
        )
        remove = await client.delete(
            f"/api/v1/users/{root.id}",
            headers={**_auth(token), "If-Match": "1"},
        )

    for response in (demote, deactivate, remove):
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "self_administration_change"


async def test_an_administrator_may_still_demote_a_peer(database: None) -> None:
    await _create_user("root", administrator=True)
    second = await _create_user("second", administrator=True)
    token = await _token("root")

    async with _client() as client:
        response = await client.patch(
            f"/api/v1/users/{second.id}",
            headers=_auth(token),
            json={"version": 1, "is_administrator": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["is_administrator"] is False


async def test_global_user_routes_refuse_every_non_administrator(
    database: None,
) -> None:
    await _create_user("root", administrator=True)
    annie = await _create_user("annie")
    owner_token = await _token("annie")

    async with _client() as client:
        created = await client.post(
            "/api/v1/projects",
            headers=_auth(owner_token),
            json={
                "name": "Road defects",
                "description": None,
                "task_type": "detection",
                "initial_training_size": 10,
                "test_set_size": 5,
                "iteration_batch_size": 5,
            },
        )
        assert created.status_code == 201

        responses = [
            await client.get("/api/v1/users", headers=_auth(owner_token)),
            await client.post(
                "/api/v1/users", headers=_auth(owner_token), json=NEW_USER
            ),
            await client.get(f"/api/v1/users/{annie.id}", headers=_auth(owner_token)),
            await client.patch(
                f"/api/v1/users/{annie.id}",
                headers=_auth(owner_token),
                json={"version": 1, "display_name": "Nope"},
            ),
            await client.post(
                f"/api/v1/users/{annie.id}/reset-password",
                headers=_auth(owner_token),
                json={"new_password": REPLACEMENT},
            ),
            await client.delete(
                f"/api/v1/users/{annie.id}",
                headers={**_auth(owner_token), "If-Match": "1"},
            ),
        ]

    assert [response.status_code for response in responses] == [403] * 6


async def test_any_user_changes_their_own_password(database: None) -> None:
    await _create_user("annie")

    async with _client() as client:
        login = await client.post(
            "/api/v1/auth/token",
            json={"username": "annie", "password": PASSWORD},
        )
        token = login.json()["access_token"]
        refresh_token = login.cookies[REFRESH_COOKIE_NAME]

        wrong = await client.post(
            "/api/v1/auth/me/password",
            headers=_auth(token),
            json={"current_password": "not-the-password", "new_password": REPLACEMENT},
        )
        assert wrong.status_code == 400
        assert wrong.json()["error"]["code"] == "current_password_incorrect"

        changed = await client.post(
            "/api/v1/auth/me/password",
            headers=_auth(token),
            json={"current_password": PASSWORD, "new_password": REPLACEMENT},
        )
        assert changed.status_code == 204

        rotated = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"{REFRESH_COOKIE_NAME}={refresh_token}"},
        )

    assert rotated.status_code == 401
    assert (await _login("annie", PASSWORD)).status_code == 401
    assert (await _login("annie", REPLACEMENT)).status_code == 200


async def test_passwords_never_reach_responses_or_audit_entries(
    database: None,
) -> None:
    await _create_user("root", administrator=True)
    token = await _token("root")

    async with _client() as client:
        rejected = await client.post(
            "/api/v1/users",
            headers=_auth(token),
            json={**NEW_USER, "password": TOO_SHORT},
        )
        assert rejected.status_code == 422
        assert TOO_SHORT not in rejected.text

        created = await client.post(
            "/api/v1/users", headers=_auth(token), json=NEW_USER
        )
        assert created.status_code == 201

        reset = await client.post(
            f"/api/v1/users/{created.json()['id']}/reset-password",
            headers=_auth(token),
            json={"new_password": REPLACEMENT},
        )
        assert reset.status_code == 204

    async with async_session_factory() as session:
        entries = list(await session.scalars(select(AuditEntry)))

    assert {entry.action for entry in entries} == {
        "user.created",
        "user.password_reset",
    }
    for entry in entries:
        assert entry.project_id is None
        serialized = f"{entry.before} {entry.after}"
        assert PASSWORD not in serialized
        assert REPLACEMENT not in serialized
