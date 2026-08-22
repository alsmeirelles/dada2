"""Phase 1 identity, session, and authorization behaviour over real HTTP requests."""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from jose import jwt
from sqlalchemy import delete

from dada_api.api.v1.endpoints.auth import REFRESH_COOKIE_NAME
from dada_api.core.config import get_settings
from dada_api.core.errors import ApiError
from dada_api.core.security import create_refresh_token, hash_password
from dada_api.db.session import async_session_factory
from dada_api.main import app
from dada_api.models.bootstrap import BootstrapRecord
from dada_api.models.project import Project, ProjectMember, ProjectRole
from dada_api.models.refresh_session import RefreshSession
from dada_api.models.user import User
from dada_api.services.authorization import (
    ProjectAction,
    authorize_project_action,
    role_allows,
)
from dada_api.services.bootstrap import (
    BootstrapError,
    bootstrap_administrator,
    replace_bootstrap_administrator,
)

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)

PASSWORD = "phase1-test-password"


def _client() -> httpx.AsyncClient:
    """Return an HTTP client bound to the ASGI application."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


async def _reset_database() -> None:
    """Remove every record the Phase 1 tests create."""
    async with async_session_factory() as session:
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


async def _create_project(owner: User) -> Project:
    """Persist a draft project owned by a user."""
    async with async_session_factory() as session:
        project = Project(
            name="Road defects",
            description=None,
            task_type="detection",
            status="draft",
            owner_id=owner.id,
            initial_training_size=10,
            test_set_size=5,
            iteration_batch_size=5,
            version=1,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project


async def _add_member(project: Project, user: User, role: ProjectRole) -> None:
    """Grant a user a role in a project."""
    async with async_session_factory() as session:
        session.add(ProjectMember(project_id=project.id, user_id=user.id, role=role))
        await session.commit()


async def _login(username: str) -> tuple[str, str]:
    """Log in and return the access token with the issued refresh token."""
    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token",
            json={"username": username, "password": PASSWORD},
        )
    assert response.status_code == 200
    return response.json()["access_token"], response.cookies[REFRESH_COOKIE_NAME]


async def _refresh(refresh_token: str) -> httpx.Response:
    """Call the refresh route with an explicit credential and no jar state."""
    async with _client() as client:
        return await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"{REFRESH_COOKIE_NAME}={refresh_token}"},
        )


async def test_login_issues_access_token_and_first_party_refresh_cookie(
    database: None,
) -> None:
    await _create_user("annie")

    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token",
            json={"username": "annie", "password": PASSWORD},
        )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1/auth" in set_cookie


async def test_login_rejects_invalid_credentials(database: None) -> None:
    await _create_user("annie")

    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/token",
            json={"username": "annie", "password": "wrong-password-value"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_current_user_reports_administrator_flag(database: None) -> None:
    await _create_user("root", administrator=True)
    access_token, _ = await _login("root")

    async with _client() as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.json()["username"] == "root"
    assert response.json()["is_administrator"] is True


async def test_refresh_rotates_and_rejects_replay(database: None) -> None:
    await _create_user("annie")
    _, first_token = await _login("annie")

    rotated = await _refresh(first_token)
    assert rotated.status_code == 200
    second_token = rotated.cookies[REFRESH_COOKIE_NAME]
    assert second_token != first_token
    assert rotated.json()["access_token"]

    replay = await _refresh(first_token)
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "refresh_token_replayed"

    revoked_successor = await _refresh(second_token)
    assert revoked_successor.status_code == 401


async def test_refresh_without_credential_is_rejected(database: None) -> None:
    async with _client() as client:
        response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_refresh_token"


async def test_expired_refresh_token_is_rejected(database: None) -> None:
    user = await _create_user("annie")
    token, token_hash = create_refresh_token()
    async with async_session_factory() as session:
        session.add(
            RefreshSession(
                family_id=str(uuid4()),
                user_id=user.id,
                token_hash=token_hash,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        await session.commit()

    response = await _refresh(token)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "refresh_token_expired"


async def test_logout_revokes_the_refresh_session(database: None) -> None:
    await _create_user("annie")
    _, refresh_token = await _login("annie")

    async with _client() as client:
        response = await client.post(
            "/api/v1/auth/logout",
            headers={"Cookie": f"{REFRESH_COOKIE_NAME}={refresh_token}"},
        )

    assert response.status_code == 204
    assert (await _refresh(refresh_token)).status_code == 401


async def test_expired_access_token_is_rejected(database: None) -> None:
    await _create_user("annie")
    settings = get_settings()
    expired = jwt.encode(
        {
            "sub": "annie",
            "roles": [],
            "type": "access",
            "iat": datetime.now(UTC) - timedelta(minutes=10),
            "exp": datetime.now(UTC) - timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    async with _client() as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {expired}"},
        )

    assert response.status_code == 401


async def test_administrator_route_denies_regular_users(database: None) -> None:
    await _create_user("root", administrator=True)
    await _create_user("annie")
    admin_token, _ = await _login("root")
    user_token, _ = await _login("annie")

    async with _client() as client:
        allowed = await client.get(
            "/api/v1/admin/status",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        denied = await client.get(
            "/api/v1/admin/status",
            headers={"Authorization": f"Bearer {user_token}"},
        )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


async def test_project_read_requires_membership(database: None) -> None:
    owner = await _create_user("owner")
    await _create_user("outsider")
    project = await _create_project(owner)
    await _add_member(project, owner, ProjectRole.owner)

    owner_token, _ = await _login("owner")
    outsider_token, _ = await _login("outsider")

    async with _client() as client:
        permitted = await client.get(
            f"/api/v1/projects/{project.id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        denied = await client.get(
            f"/api/v1/projects/{project.id}",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        missing = await client.get(
            f"/api/v1/projects/{uuid4()}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

    assert permitted.status_code == 200
    assert permitted.json()["name"] == "Road defects"
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert missing.status_code == 404


async def test_administrator_reads_a_project_without_membership(
    database: None,
) -> None:
    owner = await _create_user("owner")
    await _create_user("root", administrator=True)
    project = await _create_project(owner)
    await _add_member(project, owner, ProjectRole.owner)
    admin_token, _ = await _login("root")

    async with _client() as client:
        response = await client.get(
            f"/api/v1/projects/{project.id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    assert response.json()["owner_id"] == owner.id


@pytest.mark.parametrize("role", sorted(ProjectRole))
@pytest.mark.parametrize("action", sorted(ProjectAction))
async def test_database_backed_authorization_matches_the_matrix(
    database: None,
    role: ProjectRole,
    action: ProjectAction,
) -> None:
    owner = await _create_user("owner")
    member = await _create_user("member")
    project = await _create_project(owner)
    await _add_member(project, member, role)

    async with async_session_factory() as session:
        try:
            await authorize_project_action(session, member, project.id, action)
            granted = True
        except ApiError as error:
            assert error.status_code == 403
            granted = False

    assert granted is role_allows(role, action)


async def test_bootstrap_creates_once_and_reruns_safely(database: None) -> None:
    async with async_session_factory() as session:
        created_user, created = await bootstrap_administrator(
            session, "root", "Root Administrator", PASSWORD
        )
        assert created is True
        assert created_user.is_administrator is True
        original_hash = created_user.password_hash

        same_user, created_again = await bootstrap_administrator(
            session, "root", "Root Administrator", "a-completely-different-password"
        )

    assert created_again is False
    assert same_user.id == created_user.id
    assert same_user.password_hash == original_hash


async def test_bootstrap_refuses_a_different_identity(database: None) -> None:
    async with async_session_factory() as session:
        await bootstrap_administrator(session, "root", "Root", PASSWORD)

        with pytest.raises(BootstrapError, match="replace-bootstrap-admin"):
            await bootstrap_administrator(session, "someone-else", "Other", PASSWORD)


async def test_bootstrap_refuses_an_existing_non_bootstrap_username(
    database: None,
) -> None:
    await _create_user("root")

    async with async_session_factory() as session:
        with pytest.raises(BootstrapError, match="already exists"):
            await bootstrap_administrator(session, "root", "Root", PASSWORD)


async def test_replace_bootstrap_administrator_repoints_the_record(
    database: None,
) -> None:
    async with async_session_factory() as session:
        first, _ = await bootstrap_administrator(session, "root", "Root", PASSWORD)
        replacement = await replace_bootstrap_administrator(
            session, "root2", "Root Two", PASSWORD
        )
        record = await session.get(BootstrapRecord, 1)

        assert replacement.id != first.id
        assert replacement.is_administrator is True
        assert record is not None
        assert record.user_id == replacement.id


async def test_replace_requires_an_existing_bootstrap(database: None) -> None:
    async with async_session_factory() as session:
        with pytest.raises(BootstrapError, match="Run bootstrap-admin first"):
            await replace_bootstrap_administrator(session, "root", "Root", PASSWORD)
