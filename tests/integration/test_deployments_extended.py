"""
Extended integration tests for /api/deployments endpoints.

Covers: get by ID, get by ID 404, list with status filter,
        batch endpoint 404, rollback 404, rollback bad status,
        deployment record creation.
"""

import uuid
import pytest

from api.models import Deployment


def _create_deployment(db_session, device_id, status="SUCCESS", batch_id=None):
    """Helper: insert a Deployment row directly."""
    from datetime import datetime
    d = Deployment(
        batch_id=batch_id or uuid.uuid4(),
        device_id=device_id,
        config_version="abc123",
        status=status,
        strategy="atomic",
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    return d


# ---------------------------------------------------------------------------
# GET /api/deployments/
# ---------------------------------------------------------------------------

class TestListDeployments:
    def test_list_empty(self, client):
        r = client.get("/api/deployments/")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_returns_deployments(self, client, mock_device, db_session):
        _create_deployment(db_session, mock_device.id)
        r = client.get("/api/deployments/")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_list_filter_by_status(self, client, mock_device, db_session):
        _create_deployment(db_session, mock_device.id, status="SUCCESS")
        _create_deployment(db_session, mock_device.id, status="FAILED")
        r = client.get("/api/deployments/?status=SUCCESS")
        assert r.status_code == 200
        entries = r.json()
        assert all(e["status"] == "SUCCESS" for e in entries)

    def test_list_filter_status_case_insensitive(self, client, mock_device, db_session):
        _create_deployment(db_session, mock_device.id, status="FAILED")
        r = client.get("/api/deployments/?status=failed")
        # Server uppercases the filter
        assert r.status_code == 200
        entries = r.json()
        assert all(e["status"] == "FAILED" for e in entries)

    def test_list_pagination(self, client, mock_device, db_session):
        for _ in range(5):
            _create_deployment(db_session, mock_device.id)
        r = client.get("/api/deployments/?limit=2")
        assert r.status_code == 200
        assert len(r.json()) <= 2


# ---------------------------------------------------------------------------
# GET /api/deployments/{deployment_id}
# ---------------------------------------------------------------------------

class TestGetDeployment:
    def test_get_existing_deployment(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id)
        r = client.get(f"/api/deployments/{dep.id}")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(dep.id)
        assert body["status"] == "SUCCESS"

    def test_get_nonexistent_deployment_returns_404(self, client):
        r = client.get(f"/api/deployments/{uuid.uuid4()}")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_get_deployment_has_required_fields(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id)
        r = client.get(f"/api/deployments/{dep.id}")
        body = r.json()
        for field in ("id", "batch_id", "device_id", "config_version", "status", "strategy"):
            assert field in body


# ---------------------------------------------------------------------------
# GET /api/deployments/batch/{batch_id}
# ---------------------------------------------------------------------------

class TestGetBatch:
    def test_get_batch_with_deployments(self, client, mock_device, db_session):
        batch_id = uuid.uuid4()
        _create_deployment(db_session, mock_device.id, batch_id=batch_id)
        _create_deployment(db_session, mock_device.id, batch_id=batch_id)
        r = client.get(f"/api/deployments/batch/{batch_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["batch_id"] == str(batch_id)
        assert body["total"] == 2
        assert len(body["deployments"]) == 2

    def test_get_batch_nonexistent_returns_404(self, client):
        r = client.get(f"/api/deployments/batch/{uuid.uuid4()}")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"].lower()

    def test_batch_deployment_fields(self, client, mock_device, db_session):
        batch_id = uuid.uuid4()
        _create_deployment(db_session, mock_device.id, batch_id=batch_id)
        r = client.get(f"/api/deployments/batch/{batch_id}")
        dep = r.json()["deployments"][0]
        for field in ("id", "device_id", "status"):
            assert field in dep


# ---------------------------------------------------------------------------
# POST /api/deployments/{id}/rollback
# ---------------------------------------------------------------------------

class TestRollbackDeployment:
    def test_rollback_nonexistent_deployment_returns_404(self, client):
        r = client.post(
            f"/api/deployments/{uuid.uuid4()}/rollback",
            json={"deployment_id": str(uuid.uuid4()), "reason": "test"},
        )
        assert r.status_code == 404

    def test_rollback_queued_status_returns_400(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id, status="QUEUED")
        r = client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id)},
        )
        assert r.status_code == 400
        assert "cannot rollback" in r.json()["detail"].lower()

    def test_rollback_in_progress_returns_400(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id, status="IN_PROGRESS")
        r = client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id)},
        )
        assert r.status_code == 400

    def test_rollback_success_deployment_enqueues(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id, status="SUCCESS")
        r = client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id), "reason": "regression"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ROLLBACK_QUEUED"
        assert body["deployment_id"] == str(dep.id)
        assert "task_id" in body

    def test_rollback_failed_deployment_enqueues(self, client, mock_device, db_session):
        dep = _create_deployment(db_session, mock_device.id, status="FAILED")
        r = client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id)},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "ROLLBACK_QUEUED"
