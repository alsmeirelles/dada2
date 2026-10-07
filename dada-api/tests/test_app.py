"""Phase 0 HTTP application contract tests."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import ValidationError

from dada_api.core.errors import redact_validation_errors
from dada_api.main import app
from dada_api.schemas.project import ProjectCreate


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Use the same non-blocking ASGI transport as the other HTTP tests."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as test_client:
        yield test_client


async def test_health_is_dependency_free_and_traced(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health", headers={"X-Trace-ID": "test-trace-1234"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "DADA API"}
    assert response.headers["x-trace-id"] == "test-trace-1234"


async def test_capabilities_match_frontend_contract(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/capabilities")
    assert response.status_code == 200
    assert response.json() == {
        "supported_image_media_types": ["image/jpeg", "image/png", "image/webp"],
        "max_file_bytes": 104857600,
        "max_project_files": 100000,
        "upload_chunk_bytes": 8388608,
        "upload_session_ttl_hours": 24,
        "max_import_file_bytes": 52428800,
        "supported_task_types": ["classification", "detection", "segmentation"],
        "supported_annotation_modes": ["single", "consensus"],
        "consensus_resolvers": {
            "classification": ["majority_vote"],
            "detection": ["two_stage_box_fusion"],
            "segmentation": ["two_stage_mask_fusion"],
        },
        "realtime_transport": "websocket",
    }


async def test_framework_errors_use_common_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/missing")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "not_found"
    assert body["message"] == "Not Found"
    assert body["details"] == {}
    assert body["trace_id"] == response.headers["x-trace-id"]


async def test_invalid_idempotency_key_uses_common_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/projects",
        headers={"Idempotency-Key": "short"},
        json={},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"


async def test_idempotency_short_circuit_still_carries_cors_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post(
        "/api/v1/projects",
        headers={
            "Origin": "http://localhost:5173",
            "Idempotency-Key": "short",
        },
        json={},
    )
    assert response.status_code == 400
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_validation_errors_never_echo_the_submitted_value(
    client: httpx.AsyncClient,
) -> None:
    secret = "Pa55wd!"
    response = await client.post(
        "/api/v1/auth/token",
        json={"username": "alice", "password": secret},
    )
    assert response.status_code == 422
    errors = response.json()["error"]["details"]["errors"]
    assert errors
    assert all("input" not in error for error in errors)
    assert secret not in response.text


def test_model_validator_errors_are_reported_by_message() -> None:
    with pytest.raises(ValidationError) as raised:
        ProjectCreate.model_validate(
            {
                "name": "Static",
                "task_type": "detection",
                "dataset_layout": "single_batch",
                "iteration_batch_size": 3,
            }
        )

    errors = redact_validation_errors(raised.value.errors())

    assert "single_batch accepts no split or iteration sizes" in json.dumps(errors)


async def test_cors_allows_configured_app_origin_and_upload_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.options(
        "/api/v1/capabilities",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Upload-Offset",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "Upload-Offset" in response.headers["access-control-allow-headers"]


async def test_openapi_contains_capabilities_and_project_schemas(
    client: httpx.AsyncClient,
) -> None:
    document = (await client.get("/openapi.json")).json()
    assert "/api/v1/capabilities" in document["paths"]
    assert "/api/v1/projects/{project_id}/annotation-policy" in document["paths"]
    schemas = document["components"]["schemas"]
    assert "CapabilitiesResponse" in schemas
    assert "ErrorEnvelope" in schemas
    assert "ProjectCreate" in schemas
    assert "ProjectResponse" in schemas
    assert "ProjectClassResponse" in schemas
    assert "ProjectMemberResponse" in schemas
    assert "AnnotationPolicyResponse" in schemas


async def test_project_routes_require_authentication(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
