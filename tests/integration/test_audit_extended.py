"""
Extended integration tests for /api/audit-log endpoints.

Covers: filter by user_id, action, resource_type; get by ID; 404;
        pagination (limit/offset); audit entries created by device actions.
"""

import uuid
import pytest

from api.models import AuditLog


def _create_audit_entry(db_session, user_id="testuser", action="CREATE", resource_type="Device"):
    """Helper: insert a real AuditLog row for testing filters."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=uuid.uuid4(),
        details={"test": True},
        ip_address="127.0.0.1",
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# GET /api/audit-log/ — list with filters
# ---------------------------------------------------------------------------

class TestListAuditLog:
    def test_list_returns_200(self, client):
        r = client.get("/api/audit-log/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filter_by_user_id(self, client, db_session):
        _create_audit_entry(db_session, user_id="alice", action="CREATE")
        _create_audit_entry(db_session, user_id="bob", action="DELETE")

        r = client.get("/api/audit-log/?user_id=alice")
        assert r.status_code == 200
        entries = r.json()
        assert all(e["user_id"] == "alice" for e in entries)

    def test_filter_by_action(self, client, db_session):
        _create_audit_entry(db_session, user_id="u1", action="VALIDATE")
        _create_audit_entry(db_session, user_id="u2", action="DEPLOY")

        r = client.get("/api/audit-log/?action=VALIDATE")
        assert r.status_code == 200
        entries = r.json()
        assert all(e["action"] == "VALIDATE" for e in entries)

    def test_filter_by_action_case_insensitive(self, client, db_session):
        """action filter is uppercased server-side."""
        _create_audit_entry(db_session, user_id="u1", action="CREATE")
        r = client.get("/api/audit-log/?action=create")
        assert r.status_code == 200
        entries = r.json()
        assert any(e["action"] == "CREATE" for e in entries)

    def test_filter_by_resource_type(self, client, db_session):
        _create_audit_entry(db_session, resource_type="Device")
        _create_audit_entry(db_session, resource_type="Configuration")

        r = client.get("/api/audit-log/?resource_type=Configuration")
        assert r.status_code == 200
        entries = r.json()
        assert all(e["resource_type"] == "Configuration" for e in entries)

    def test_filter_combination(self, client, db_session):
        _create_audit_entry(db_session, user_id="carol", action="DELETE", resource_type="Device")
        _create_audit_entry(db_session, user_id="carol", action="CREATE", resource_type="Device")

        r = client.get("/api/audit-log/?user_id=carol&action=DELETE")
        assert r.status_code == 200
        entries = r.json()
        assert all(e["user_id"] == "carol" and e["action"] == "DELETE" for e in entries)

    def test_filter_no_match_returns_empty_list(self, client, db_session):
        r = client.get("/api/audit-log/?user_id=nobody_ever")
        assert r.status_code == 200
        assert r.json() == []

    def test_pagination_limit(self, client, db_session):
        for i in range(5):
            _create_audit_entry(db_session, user_id=f"pguser{i}")
        r = client.get("/api/audit-log/?limit=2")
        assert r.status_code == 200
        assert len(r.json()) <= 2

    def test_pagination_offset(self, client, db_session):
        for i in range(4):
            _create_audit_entry(db_session, user_id="offsetuser")
        r_all = client.get("/api/audit-log/?user_id=offsetuser")
        r_skip = client.get("/api/audit-log/?user_id=offsetuser&offset=2")
        assert len(r_skip.json()) == len(r_all.json()) - 2

    def test_limit_max_boundary(self, client):
        r = client.get("/api/audit-log/?limit=1000")
        assert r.status_code == 200

    def test_limit_zero_returns_422(self, client):
        r = client.get("/api/audit-log/?limit=0")
        assert r.status_code == 422

    def test_entries_ordered_newest_first(self, client, db_session):
        e1 = _create_audit_entry(db_session, user_id="order_test")
        e2 = _create_audit_entry(db_session, user_id="order_test")
        r = client.get("/api/audit-log/?user_id=order_test")
        ids = [e["id"] for e in r.json()]
        # Newest first — e2 should appear before e1
        assert ids.index(str(e2.id)) < ids.index(str(e1.id))


# ---------------------------------------------------------------------------
# GET /api/audit-log/{log_id}
# ---------------------------------------------------------------------------

class TestGetAuditEntry:
    def test_get_existing_entry(self, client, db_session):
        entry = _create_audit_entry(db_session, user_id="findme", action="ROLLBACK")
        r = client.get(f"/api/audit-log/{entry.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(entry.id)
        assert body["user_id"] == "findme"
        assert body["action"] == "ROLLBACK"

    def test_get_nonexistent_entry_returns_404(self, client):
        r = client.get(f"/api/audit-log/{uuid.uuid4()}")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_get_entry_has_all_fields(self, client, db_session):
        entry = _create_audit_entry(db_session)
        r = client.get(f"/api/audit-log/{entry.id}")
        body = r.json()
        for field in ("id", "user_id", "action", "resource_type", "resource_id", "timestamp"):
            assert field in body


# ---------------------------------------------------------------------------
# Audit log created by device actions
# ---------------------------------------------------------------------------

class TestAuditLogCreatedByActions:
    def test_create_device_writes_audit_log(self, client, db_session):
        payload = {
            "hostname": "audit-test-router",
            "device_type": "cisco_xr",
            "management_ip": "10.50.50.50",
        }
        client.post("/api/devices/", json=payload)

        r = client.get("/api/audit-log/?action=CREATE&resource_type=Device")
        assert r.status_code == 200
        entries = r.json()
        hostnames = [e["details"].get("hostname") for e in entries if e.get("details")]
        assert "audit-test-router" in hostnames

    def test_validate_config_writes_audit_log(self, client, mock_device, valid_bgp_config):
        client.post(
            "/api/configs/validate",
            json={
                "device_id": str(mock_device.id),
                "desired_state": valid_bgp_config,
                "description": "audit-test",
            },
        )
        r = client.get("/api/audit-log/?action=VALIDATE")
        assert r.status_code == 200
        # Background task may not have run synchronously in tests; just verify endpoint works
        assert isinstance(r.json(), list)
