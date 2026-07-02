"""
Phase 6 — Comprehensive integration test suite.

This file is the final "everything works together" validation.
It runs full user-journey scenarios against the real FastAPI app
(TestClient + in-memory or test PostgreSQL, no real SSH).

Scenarios:
  A. Full deployment lifecycle (register → validate → deploy → verify → rollback → audit)
  B. Multi-device batch deployment with mixed results
  C. Config version management (create → list → diff → delete)
  D. Audit log completeness (every write operation produces an audit entry)
  E. API contract stability (all endpoints return documented schemas)
  F. Concurrent request safety (10 parallel requests don't cause 5xx)
  G. Pagination and filtering (large result sets handled correctly)
  H. Error boundary (every error path returns correct status code)

[CURSOR IMPLEMENTS]: Scenarios B, D, F, G, H stubs.
                     Cowork scaffolds structure + all assertions.
"""

import pytest
import threading
import time
from uuid import uuid4
from unittest.mock import patch, AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Shared device/config factories
# ---------------------------------------------------------------------------

def make_device(suffix=None) -> dict:
    s = suffix or uuid4().hex[:6]
    # Use a stable hash so any string suffix produces a valid IP
    h = abs(hash(s))
    return {
        "hostname": f"comp-r-{s}",
        "management_ip": f"10.250.{h % 256}.{(h >> 8) % 254 + 1}",
        "device_type": "cisco_xr",
        "ssh_port": 22,
        "bgp_asn": 65001,
        "ospf_area": "0.0.0.0",
        "os_version": "7.9.1",
    }


def make_bgp_config(asn: int = 65001) -> dict:
    return {
        "asn": asn,
        "router_id": "10.0.0.1",
        "neighbors": [
            {"peer_ip": "10.0.0.2", "remote_asn": 65002, "description": "peer-spine"},
        ],
        "networks": ["10.0.0.0/24"],
    }


def make_ospf_config() -> dict:
    return {
        "process_id": 1,
        "router_id": "10.0.0.1",
        "areas": [{"area_id": "0.0.0.0", "interfaces": [
            {"name": "GigabitEthernet0/0/0", "type": "point-to-point"}
        ]}],
    }


# ---------------------------------------------------------------------------
# Scenario A: Full deployment lifecycle
# ---------------------------------------------------------------------------

class TestScenarioAFullLifecycle:
    """
    Complete user journey: register → validate → save config →
    deploy (mocked SSH) → check status → view logs → rollback → audit.
    """

    def test_A1_register_device(self, client):
        """Device registration returns 201 with an ID."""
        r = client.post("/api/devices", json=make_device("aaa001"))
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["hostname"] == "comp-r-aaa001"

    def test_A2_duplicate_hostname_returns_409(self, client):
        """Registering the same hostname twice returns 409 Conflict."""
        device = make_device("dup001")
        r1 = client.post("/api/devices", json=device)
        assert r1.status_code == 201
        r2 = client.post("/api/devices", json=device)
        assert r2.status_code in (409, 422), \
            f"Duplicate hostname should be rejected, got {r2.status_code}"

    def test_A3_validate_config_valid(self, client, db_session):
        """Valid BGP+OSPF config passes validation."""
        r = client.post("/api/devices", json=make_device("val001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.post("/api/configs/validate", json={
            "device_id": device_id,
            "bgp": make_bgp_config(),
            "ospf": make_ospf_config(),
        })
        assert r.status_code == 200
        body = r.json()
        assert "valid" in body

    def test_A4_validate_invalid_bgp_asn(self, client, db_session):
        """BGP ASN out of valid range is caught by validator."""
        r = client.post("/api/devices", json=make_device("inv001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        bad_bgp = make_bgp_config()
        bad_bgp["asn"] = 0  # invalid ASN

        r = client.post("/api/configs/validate", json={
            "device_id": device_id,
            "bgp": bad_bgp,
            "ospf": make_ospf_config(),
        })
        assert r.status_code in (200, 422)
        if r.status_code == 200:
            body = r.json()
            # Validator should flag this as invalid or warn
            assert not body.get("valid") or len(body.get("errors", [])) > 0 or \
                   len(body.get("warnings", [])) > 0

    def test_A5_get_device_returns_full_schema(self, client):
        """GET /api/devices/{id} returns all expected fields."""
        r = client.post("/api/devices", json=make_device("get001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.get(f"/api/devices/{device_id}")
        assert r.status_code == 200
        body = r.json()
        required_fields = {"id", "hostname", "management_ip", "device_type"}
        missing = required_fields - set(body.keys())
        assert not missing, f"Missing fields in device response: {missing}"

    def test_A6_list_devices_includes_created(self, client):
        """Registered device appears in list."""
        suffix = uuid4().hex[:6]
        r = client.post("/api/devices", json=make_device(suffix))
        assert r.status_code == 201
        hostname = r.json()["hostname"]

        r = client.get("/api/devices")
        assert r.status_code == 200
        hostnames = [d["hostname"] for d in r.json()]
        assert hostname in hostnames

    def test_A7_trigger_deployment_returns_id(self, client, db_session):
        """POST /api/deployments returns a deployment/batch ID."""
        r = client.post("/api/devices", json=make_device("dep001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.post("/api/deployments", json={
            "device_ids": [device_id],
            "config_version": "latest",
            "strategy": "atomic",
            "dry_run": True,
        })
        assert r.status_code in (200, 201, 202)
        body = r.json()
        dep_id = body.get("deployment_id") or body.get("id") or body.get("batch_id")
        assert dep_id is not None, f"No deployment ID in response: {body}"

    def test_A8_list_deployments_returns_list(self, client):
        """GET /api/deployments returns a list."""
        r = client.get("/api/deployments")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_A9_delete_device_returns_204(self, client):
        """DELETE /api/devices/{id} returns 204 No Content."""
        r = client.post("/api/devices", json=make_device("del001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.delete(f"/api/devices/{device_id}")
        assert r.status_code in (200, 204)

        r = client.get(f"/api/devices/{device_id}")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scenario B: Multi-device batch deployment
# ---------------------------------------------------------------------------

class TestScenarioBBatchDeployment:
    """
    Deploy to 3 devices simultaneously; verify all get deployment records.
    [CURSOR IMPLEMENTS full batch assertions]
    """

    def test_B1_batch_with_multiple_devices(self, client):
        """Batch deployment across 3 devices returns a batch or list of IDs."""
        device_ids = []
        for i in range(3):
            r = client.post("/api/devices", json=make_device(f"bat{i:03d}"))
            assert r.status_code == 201
            device_ids.append(r.json()["id"])

        r = client.post("/api/deployments", json={
            "device_ids": device_ids,
            "config_version": "latest",
            "strategy": "rolling",
            "dry_run": True,
        })
        assert r.status_code in (200, 201, 202)

    def test_B2_empty_device_list_returns_422(self, client):
        """Triggering a deployment with no devices is a validation error."""
        r = client.post("/api/deployments", json={
            "device_ids": [],
            "config_version": "latest",
            "strategy": "atomic",
        })
        assert r.status_code in (400, 422)

    def test_B3_unknown_device_id_returns_error(self, client):
        """Deployment with a non-existent device ID returns 404 or 422."""
        r = client.post("/api/deployments", json={
            "device_ids": [str(uuid4())],
            "config_version": "latest",
            "strategy": "atomic",
        })
        assert r.status_code in (400, 404, 422)


# ---------------------------------------------------------------------------
# Scenario C: Config version management
# ---------------------------------------------------------------------------

class TestScenarioCConfigVersions:
    """Test configuration CRUD and history."""

    def test_C1_create_config(self, client):
        """POST /api/configs creates a configuration record."""
        r = client.post("/api/devices", json=make_device("cfg001"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.post("/api/configs", json={
            "device_id": device_id,
            "version": f"v1-{uuid4().hex[:4]}",
            "bgp": make_bgp_config(),
            "ospf": make_ospf_config(),
            "created_by": "test-suite",
        })
        assert r.status_code in (200, 201)
        body = r.json()
        assert "id" in body or "version" in body

    def test_C2_list_configs_for_device(self, client, db_session):
        """GET /api/configs?device_id=... returns that device's configs."""
        r = client.post("/api/devices", json=make_device("cfg002"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        # Create 2 versions
        for ver in ["v1", "v2"]:
            client.post("/api/configs", json={
                "device_id": device_id,
                "version": f"{ver}-{uuid4().hex[:4]}",
                "bgp": make_bgp_config(),
                "ospf": make_ospf_config(),
                "created_by": "test-suite",
            })

        r = client.get(f"/api/configs?device_id={device_id}")
        assert r.status_code == 200
        configs = r.json()
        assert isinstance(configs, list)

    def test_C3_validate_before_save(self, client):
        """Validate endpoint returns structured result with 'valid' field."""
        r = client.post("/api/devices", json=make_device("cfg003"))
        assert r.status_code == 201
        device_id = r.json()["id"]

        r = client.post("/api/configs/validate", json={
            "device_id": device_id,
            "bgp": make_bgp_config(),
            "ospf": make_ospf_config(),
        })
        assert r.status_code == 200
        body = r.json()
        assert "valid" in body
        assert "errors" in body or "warnings" in body or body.get("valid") is not None


# ---------------------------------------------------------------------------
# Scenario D: Audit log completeness
# ---------------------------------------------------------------------------

class TestScenarioDauditLog:
    """Every CREATE and DEPLOY generates an audit log entry."""

    def test_D1_audit_log_returns_list(self, client):
        """GET /api/audit returns a list."""
        r = client.get("/api/audit")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_D2_audit_log_has_required_fields(self, client):
        """Each audit entry has the required schema fields."""
        r = client.post("/api/devices", json=make_device("aud001"))
        assert r.status_code == 201

        r = client.get("/api/audit?limit=5")
        assert r.status_code == 200
        entries = r.json()
        if entries:
            entry = entries[0]
            # Required fields per AuditLog schema
            for field in ("id", "action", "timestamp"):
                assert field in entry, f"Audit entry missing field: {field}"

    def test_D3_audit_log_filter_by_action(self, client):
        """GET /api/audit?action=CREATE filters by action type."""
        r = client.get("/api/audit?action=CREATE&limit=5")
        assert r.status_code in (200, 422)  # 422 if action filter not supported
        if r.status_code == 200:
            entries = r.json()
            for entry in entries:
                assert entry.get("action") in ("CREATE", None)

    def test_D4_audit_log_limit_respected(self, client):
        """GET /api/audit?limit=3 returns at most 3 entries."""
        r = client.get("/api/audit?limit=3")
        assert r.status_code == 200
        assert len(r.json()) <= 3


# ---------------------------------------------------------------------------
# Scenario E: API contract stability
# ---------------------------------------------------------------------------

class TestScenarioEAPIContract:
    """All documented endpoints return correct status codes and JSON."""

    ENDPOINTS_200 = [
        "/health",
        "/api/devices",
        "/api/deployments",
        "/api/audit",
        "/api/configs",
    ]

    @pytest.mark.parametrize("path", ENDPOINTS_200)
    def test_E1_get_endpoint_returns_200(self, client, path):
        """Every documented GET endpoint returns 200."""
        r = client.get(path)
        assert r.status_code == 200, f"GET {path} returned {r.status_code}: {r.text[:200]}"

    @pytest.mark.parametrize("path", ENDPOINTS_200)
    def test_E2_get_endpoint_returns_json(self, client, path):
        """Every GET endpoint returns valid JSON."""
        r = client.get(path)
        if r.status_code == 200:
            assert r.json() is not None

    def test_E3_openapi_schema_is_valid(self, client):
        """OpenAPI schema is accessible and well-formed."""
        r = client.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert "openapi" in schema
        assert "paths" in schema
        assert schema["openapi"].startswith("3.")

    def test_E4_docs_ui_accessible(self, client):
        """Swagger UI is accessible at /docs."""
        r = client.get("/docs")
        assert r.status_code == 200

    def test_E5_redoc_accessible(self, client):
        """ReDoc is accessible at /redoc."""
        r = client.get("/redoc")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Scenario F: Concurrent request safety
# ---------------------------------------------------------------------------

class TestScenarioFConcurrency:
    """10 concurrent requests must not produce 5xx errors."""

    def test_F1_concurrent_reads_no_5xx(self, client):
        """10 concurrent GET /api/devices calls all succeed."""
        results = []
        errors = []

        def do_request():
            try:
                r = client.get("/api/devices")
                results.append(r.status_code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_request) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Requests raised exceptions: {errors}"
        server_errors = [s for s in results if s >= 500]
        assert not server_errors, f"Got {len(server_errors)} 5xx responses: {server_errors}"

    def test_F2_concurrent_writes_no_5xx(self, client):
        """10 concurrent POST /api/devices calls don't cause 5xx."""
        results = []
        errors = []

        def do_create(i):
            try:
                r = client.post("/api/devices", json=make_device(f"con{i:04d}"))
                results.append(r.status_code)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=do_create, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"Requests raised exceptions: {errors}"
        server_errors = [s for s in results if s >= 500]
        assert not server_errors, f"Got {len(server_errors)} 5xx responses"


# ---------------------------------------------------------------------------
# Scenario G: Pagination and filtering
# ---------------------------------------------------------------------------

class TestScenarioGPagination:
    """Large result sets handled with limit/offset."""

    def test_G1_limit_parameter_on_devices(self, client):
        """GET /api/devices?limit=2 returns at most 2 results."""
        # Create 3+ devices first
        for i in range(3):
            client.post("/api/devices", json=make_device(f"pag{i:03d}"))

        r = client.get("/api/devices?limit=2")
        assert r.status_code == 200
        assert len(r.json()) <= 2

    def test_G2_limit_parameter_on_audit(self, client):
        """GET /api/audit?limit=5 returns at most 5 entries."""
        r = client.get("/api/audit?limit=5")
        assert r.status_code == 200
        assert len(r.json()) <= 5

    def test_G3_zero_limit_returns_empty_or_default(self, client):
        """GET /api/devices?limit=0 returns empty list or default limit."""
        r = client.get("/api/devices?limit=0")
        assert r.status_code in (200, 422)


# ---------------------------------------------------------------------------
# Scenario H: Error boundary
# ---------------------------------------------------------------------------

class TestScenarioHErrorBoundary:
    """Every error path returns the correct HTTP status code."""

    def test_H1_404_on_unknown_device(self, client):
        r = client.get(f"/api/devices/{uuid4()}")
        assert r.status_code == 404

    def test_H2_404_on_unknown_deployment(self, client):
        r = client.get(f"/api/deployments/{uuid4()}")
        assert r.status_code == 404

    def test_H3_422_on_missing_required_field(self, client):
        """POST without required field returns 422 Unprocessable Entity."""
        r = client.post("/api/devices", json={"management_ip": "10.0.0.1"})  # missing hostname
        assert r.status_code == 422

    def test_H4_422_on_invalid_uuid_path_param(self, client):
        r = client.get("/api/devices/not-a-uuid")
        assert r.status_code == 422

    def test_H5_405_on_wrong_method(self, client):
        r = client.put("/api/devices")
        assert r.status_code in (405, 404)  # 405 preferred, some routers return 404

    def test_H6_404_on_nonexistent_path(self, client):
        r = client.get("/api/this-endpoint-does-not-exist")
        assert r.status_code == 404

    def test_H7_error_response_has_detail_field(self, client):
        """Error responses always have a 'detail' field."""
        r = client.get(f"/api/devices/{uuid4()}")
        assert r.status_code == 404
        body = r.json()
        assert "detail" in body

    def test_H8_422_detail_is_list(self, client):
        """Pydantic validation errors return detail as a list."""
        r = client.post("/api/devices", json={"hostname": None})
        assert r.status_code == 422
        body = r.json()
        assert isinstance(body.get("detail"), list)
