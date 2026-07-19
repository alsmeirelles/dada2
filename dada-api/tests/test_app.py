"""Phase 0 HTTP application contract tests."""

from fastapi.testclient import TestClient

from dada_api.main import app

client = TestClient(app)


def test_health_is_dependency_free_and_traced() -> None:
    response = client.get("/health", headers={"X-Trace-ID": "test-trace-1234"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "DADA API"}
    assert response.headers["x-trace-id"] == "test-trace-1234"


def test_capabilities_match_frontend_contract() -> None:
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    assert response.json() == {
        "supported_image_media_types": ["image/jpeg", "image/png", "image/webp"],
        "max_file_bytes": 104857600,
        "max_project_files": 100000,
        "upload_chunk_bytes": 8388608,
        "supported_task_types": ["classification", "detection", "segmentation"],
        "realtime_transport": "websocket",
    }


def test_framework_errors_use_common_envelope() -> None:
    response = client.get("/missing")
    assert response.status_code == 404
    body = response.json()["error"]
    assert body["code"] == "not_found"
    assert body["message"] == "Not Found"
    assert body["details"] == {}
    assert body["trace_id"] == response.headers["x-trace-id"]


def test_invalid_idempotency_key_uses_common_envelope() -> None:
    response = client.post(
        "/api/v1/projects",
        headers={"Idempotency-Key": "short"},
        json={},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_idempotency_key"


def test_cors_allows_configured_app_origin_and_upload_headers() -> None:
    response = client.options(
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


def test_openapi_contains_capabilities_and_project_schemas() -> None:
    document = client.get("/openapi.json").json()
    assert "/api/v1/capabilities" in document["paths"]
    schemas = document["components"]["schemas"]
    assert "CapabilitiesResponse" in schemas
    assert "ErrorEnvelope" in schemas
    assert "ProjectCreate" in schemas
    assert "ProjectResponse" in schemas


def test_phase_two_project_placeholder_uses_error_envelope() -> None:
    response = client.get("/api/v1/projects")
    assert response.status_code == 501
    assert (
        response.json()["error"]["message"]
        == "Project persistence is scheduled for Phase 2."
    )
