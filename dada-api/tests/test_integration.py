"""Phase 0 PostgreSQL, Redis, migration, and readiness integration test."""

import os

import httpx
import pytest
from sqlalchemy import delete, text

from dada_api.core.security import create_access_token
from dada_api.db.migrations import current_revision, migration_head
from dada_api.db.session import async_session_factory, engine
from dada_api.main import app
from dada_api.models.idempotency import IdempotencyRecord
from dada_api.models.user import User

pytestmark = pytest.mark.skipif(
    os.getenv("DADA_RUN_INTEGRATION") != "1",
    reason="set DADA_RUN_INTEGRATION=1 with PostgreSQL and Redis running",
)


async def test_migrations_and_readiness() -> None:
    async with engine.connect() as connection:
        assert await current_revision(connection) == migration_head()
        assert await connection.scalar(text("SELECT 1")) == 1

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert set(response.json()["dependencies"]) == {
        "postgresql",
        "migrations",
        "redis",
    }

    async with async_session_factory() as session:
        user = User(
            username="phase0-integration",
            display_name="Phase 0 Integration",
            password_hash="not-used-by-this-test",
            is_administrator=False,
            is_active=True,
        )
        session.add(user)
        await session.commit()

    token = create_access_token("phase0-integration", [])
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "phase0-idempotency-test",
    }
    payload = {"image_id": "image-1", "annotations": []}
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        first = await client.post(
            "/api/v1/queue/annotations", headers=headers, json=payload
        )
        replay = await client.post(
            "/api/v1/queue/annotations", headers=headers, json=payload
        )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["idempotency-replayed"] == "true"

    async with async_session_factory() as session:
        await session.execute(delete(IdempotencyRecord))
        await session.execute(delete(User).where(User.username == "phase0-integration"))
        await session.commit()
