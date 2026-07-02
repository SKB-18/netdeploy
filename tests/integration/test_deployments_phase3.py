"""
Integration tests for Phase 3 deployment endpoints:
- GET /api/deployments/{id}/logs
- GET /api/deployments/{id}/snapshot
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch
from datetime import datetime
from fastapi.testclient import TestClient


@pytest.fixture
def device(db_session):
    from api.models import Device
    d = Device(
        hostname=f"log-test-r-{uuid4().hex[:6]}",
        management_ip="10.99.0.1",
        device_type="cisco_xr",
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    return d


@pytest.fixture
def deployment(db_session, device):
    from api.models import Deployment
    dep = Deployment(
        device_id=device.id,
        status="SUCCESS",
        config_version="latest",
        strategy="atomic",
        logs="Step 1: connected\nStep 2: applied\nStep 3: verified\n",
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        end_time=datetime(2024, 1, 1, 12, 5, 0),
    )
    db_session.add(dep)
    db_session.commit()
    db_session.refresh(dep)
    return dep


# ---------------------------------------------------------------------------
# GET /api/deployments/{id}/logs
# ---------------------------------------------------------------------------

class TestDeploymentLogsEndpoint:
    def test_logs_returns_log_lines(self, client, deployment):
        r = client.get(f"/api/deployments/{deployment.id}/logs")
        assert r.status_code == 200
        data = r.json()
        assert data["deployment_id"] == str(deployment.id)
        assert data["status"] == "SUCCESS"
        assert isinstance(data["logs"], list)
        assert len(data["logs"]) == 3  # 3 non-empty log lines
        assert "Step 1: connected" in data["logs"]

    def test_logs_count_matches(self, client, deployment):
        r = client.get(f"/api/deployments/{deployment.id}/logs")
        data = r.json()
        assert data["log_count"] == len(data["logs"])

    def test_logs_includes_timestamps(self, client, deployment):
        r = client.get(f"/api/deployments/{deployment.id}/logs")
        data = r.json()
        assert data["start_time"] is not None
        assert data["end_time"] is not None

    def test_logs_empty_deployment(self, client, db_session, device):
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="IN_PROGRESS",
            config_version="latest",
            strategy="rolling",
            logs=None,  # No logs yet
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        r = client.get(f"/api/deployments/{dep.id}/logs")
        assert r.status_code == 200
        data = r.json()
        assert data["logs"] == []
        assert data["log_count"] == 0
        assert data["start_time"] is None
        assert data["end_time"] is None

    def test_logs_deployment_not_found(self, client):
        r = client.get(f"/api/deployments/{uuid4()}/logs")
        assert r.status_code == 404

    def test_logs_whitespace_lines_excluded(self, client, db_session, device):
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="SUCCESS",
            config_version="latest",
            strategy="atomic",
            logs="line 1\n   \nline 2\n\nline 3\n",
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        r = client.get(f"/api/deployments/{dep.id}/logs")
        data = r.json()
        # Empty/whitespace lines are excluded
        assert len(data["logs"]) == 3


# ---------------------------------------------------------------------------
# GET /api/deployments/{id}/snapshot
# ---------------------------------------------------------------------------

class TestDeploymentSnapshotEndpoint:
    def test_snapshot_deployment_not_found(self, client):
        r = client.get(f"/api/deployments/{uuid4()}/snapshot")
        assert r.status_code == 404

    def test_snapshot_no_snapshots_returns_empty_list(self, client, deployment):
        r = client.get(f"/api/deployments/{deployment.id}/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert data["deployment_id"] == str(deployment.id)
        assert data["snapshots"] == []
        assert data["diff"] is None

    def test_snapshot_with_snapshots(self, client, db_session, deployment, device):
        from api.models import ConfigSnapshot
        snap = ConfigSnapshot(
            deployment_id=deployment.id,
            device_id=device.id,
            config_before={"bgp": {"local_asn": 65001}},
            config_after=None,
            snapshot_hash="abc123",
        )
        db_session.add(snap)
        db_session.commit()

        r = client.get(f"/api/deployments/{deployment.id}/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert len(data["snapshots"]) == 1

    def test_snapshot_filtered_by_device_id(self, client, db_session, deployment, device):
        from api.models import ConfigSnapshot, Device

        other_device = Device(
            hostname=f"filter-r-{uuid4().hex[:6]}",
            management_ip="10.99.1.2",
            device_type="cisco_ios",
        )
        db_session.add(other_device)
        db_session.commit()
        db_session.refresh(other_device)

        snap1 = ConfigSnapshot(
            deployment_id=deployment.id,
            device_id=device.id,
            config_before={"bgp": {"local_asn": 65001}},
            config_after=None,
            snapshot_hash="abc111",
        )
        snap2 = ConfigSnapshot(
            deployment_id=deployment.id,
            device_id=other_device.id,
            config_before={"bgp": {"local_asn": 65002}},
            config_after=None,
            snapshot_hash="abc222",
        )
        db_session.add_all([snap1, snap2])
        db_session.commit()

        r = client.get(
            f"/api/deployments/{deployment.id}/snapshot?device_id={device.id}"
        )
        assert r.status_code == 200
        data = r.json()
        # Only snap1 should be returned
        assert len(data["snapshots"]) == 1
        assert data["snapshots"][0]["device_id"] == str(device.id)

    def test_snapshot_result_has_required_keys(self, client, deployment):
        r = client.get(f"/api/deployments/{deployment.id}/snapshot")
        data = r.json()
        assert "deployment_id" in data
        assert "snapshots" in data
        assert "diff" in data


# ---------------------------------------------------------------------------
# Rollback endpoint (existing but extended coverage)
# ---------------------------------------------------------------------------

@pytest.fixture
def authed_client(db_session):
    """FastAPI test client with get_current_user overridden."""
    from api.main import app
    from api.dependencies import get_db, get_current_user

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return {"user_id": "test-user", "username": "admin", "role": "admin"}

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestRollbackEndpointExtended:
    def test_rollback_in_progress_deployment(self, authed_client, db_session, device):
        """Can't rollback an IN_PROGRESS deployment — should return 400."""
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="IN_PROGRESS",
            config_version="latest",
            strategy="atomic",
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        r = authed_client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id)},
        )
        assert r.status_code == 400

    def test_rollback_queued_deployment(self, authed_client, db_session, device):
        """Can't rollback a QUEUED deployment → 400."""
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="QUEUED",
            config_version="latest",
            strategy="rolling",
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        r = authed_client.post(
            f"/api/deployments/{dep.id}/rollback",
            json={"deployment_id": str(dep.id)},
        )
        assert r.status_code == 400

    def test_rollback_failed_deployment_enqueues(self, authed_client, db_session, device):
        """FAILED deployment can be rolled back → returns 200 with task_id."""
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="FAILED",
            config_version="latest",
            strategy="atomic",
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        mock_task = MagicMock()
        mock_task.id = "rollback-task-1"

        with patch("tasks.deployment.rollback_device") as mock_rollback:
            mock_rollback.delay.return_value = mock_task
            r = authed_client.post(
                f"/api/deployments/{dep.id}/rollback",
                json={"deployment_id": str(dep.id)},
            )

        assert r.status_code == 200
        data = r.json()
        assert "task_id" in data

    def test_rollback_success_deployment_enqueues(self, authed_client, db_session, device):
        """SUCCESS deployment can also be rolled back → 200."""
        from api.models import Deployment
        dep = Deployment(
            device_id=device.id,
            status="SUCCESS",
            config_version="latest",
            strategy="atomic",
        )
        db_session.add(dep)
        db_session.commit()
        db_session.refresh(dep)

        mock_task = MagicMock()
        mock_task.id = "rollback-task-2"

        with patch("tasks.deployment.rollback_device") as mock_rollback:
            mock_rollback.delay.return_value = mock_task
            r = authed_client.post(
                f"/api/deployments/{dep.id}/rollback",
                json={"deployment_id": str(dep.id)},
            )

        assert r.status_code == 200
