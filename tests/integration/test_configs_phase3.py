"""
Integration tests for Phase 3 configs endpoints:
- POST /api/configs/validate-batch
- POST /api/configs/validate-async
- GET  /api/configs/validate-status/{task_id}
- POST /api/configs/deploy
- GET  /api/configs/diff (device not found)
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures — reuse conftest client + db session
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_bgp_state():
    return {
        "bgp": {
            "local_asn": 65001,
            "router_id": "10.0.0.1",
            "neighbors": [
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65002}
            ],
        }
    }


@pytest.fixture
def device_id(client, db_session):
    """Create a device and return its UUID string."""
    from api.models import Device
    device = Device(
        hostname=f"test-r-{uuid4().hex[:6]}",
        management_ip="10.0.0.100",
        device_type="cisco_xr",
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return str(device.id)


# ---------------------------------------------------------------------------
# validate-batch
# ---------------------------------------------------------------------------

class TestValidateBatchEndpoint:
    def test_validate_batch_all_valid(self, client, device_id, valid_bgp_state):
        payload = [
            {"device_id": device_id, "desired_state": valid_bgp_state},
        ]
        r = client.post("/api/configs/validate-batch", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["valid"] is True

    def test_validate_batch_mixed_results(self, client, device_id, valid_bgp_state):
        invalid_state = {"bgp": {"local_asn": -1, "neighbors": []}}
        payload = [
            {"device_id": device_id, "desired_state": valid_bgp_state},
            {"device_id": str(uuid4()), "desired_state": invalid_state},
        ]
        r = client.post("/api/configs/validate-batch", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2

    def test_validate_batch_empty_list(self, client):
        r = client.post("/api/configs/validate-batch", json=[])
        assert r.status_code == 200
        assert r.json() == []

    def test_validate_batch_multiple_devices(self, client, device_id):
        payload = [
            {
                "device_id": device_id,
                "desired_state": {
                    "bgp": {"local_asn": 65001 + i, "router_id": f"10.0.0.{i+1}", "neighbors": []}
                },
            }
            for i in range(3)
        ]
        r = client.post("/api/configs/validate-batch", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 3

    def test_validate_batch_result_has_device_id(self, client, device_id, valid_bgp_state):
        payload = [{"device_id": device_id, "desired_state": valid_bgp_state}]
        r = client.post("/api/configs/validate-batch", json=payload)
        data = r.json()
        assert data[0]["device_id"] == device_id


# ---------------------------------------------------------------------------
# validate-async
# ---------------------------------------------------------------------------

class TestValidateAsyncEndpoint:
    def test_validate_async_returns_task_id(self, client, device_id, valid_bgp_state):
        payload = {"device_id": device_id, "desired_state": valid_bgp_state}

        mock_task = MagicMock()
        mock_task.id = "task-abc-123"

        with patch("tasks.validation.validate_config_task") as mock_validate:
            mock_validate.delay.return_value = mock_task
            r = client.post("/api/configs/validate-async", json=payload)

        assert r.status_code == 200
        data = r.json()
        assert "task_id" in data
        assert data["status"] == "PENDING"
        assert data["device_id"] == device_id

    def test_validate_async_device_not_found(self, client, valid_bgp_state):
        payload = {"device_id": str(uuid4()), "desired_state": valid_bgp_state}

        with patch("tasks.validation.validate_config_task"):
            r = client.post("/api/configs/validate-async", json=payload)

        assert r.status_code == 404

    def test_validate_async_with_run_preflight(self, client, device_id, valid_bgp_state):
        payload = {"device_id": device_id, "desired_state": valid_bgp_state}

        mock_task = MagicMock()
        mock_task.id = "task-pf-456"

        with patch("tasks.validation.validate_config_task") as mock_validate:
            mock_validate.delay.return_value = mock_task
            r = client.post(
                "/api/configs/validate-async?run_preflight=true", json=payload
            )

        assert r.status_code == 200
        # Verify run_preflight was passed
        call_kwargs = mock_validate.delay.call_args[1]
        assert call_kwargs.get("run_preflight") is True


# ---------------------------------------------------------------------------
# validate-status
# ---------------------------------------------------------------------------

class TestValidateStatusEndpoint:
    def test_status_pending(self, client):
        mock_result = MagicMock()
        mock_result.state = "PENDING"

        with patch("celery.result.AsyncResult", return_value=mock_result):
            r = client.get("/api/configs/validate-status/task-123")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "PENDING"
        assert data["task_id"] == "task-123"

    def test_status_success_returns_result(self, client):
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.result = {"valid": True, "errors": [], "warnings": []}

        with patch("celery.result.AsyncResult", return_value=mock_result):
            r = client.get("/api/configs/validate-status/task-success")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "SUCCESS"
        assert "result" in data

    def test_status_failure_returns_error(self, client):
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.result = Exception("Validation crashed")

        with patch("celery.result.AsyncResult", return_value=mock_result):
            r = client.get("/api/configs/validate-status/task-fail")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "FAILURE"
        assert "error" in data

    def test_status_unknown_state(self, client):
        mock_result = MagicMock()
        mock_result.state = "RETRY"

        with patch("celery.result.AsyncResult", return_value=mock_result):
            r = client.get("/api/configs/validate-status/task-retry")

        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "RETRY"


# ---------------------------------------------------------------------------
# deploy endpoint
# ---------------------------------------------------------------------------

class TestDeployConfigEndpoint:
    def test_deploy_returns_batch_id(self, client, device_id, valid_bgp_state, db_session):
        from api.models import Configuration

        db_session.add(
            Configuration(
                device_id=device_id,
                version="pending",
                desired_state=valid_bgp_state,
                status="PENDING",
                created_by="test",
            )
        )
        db_session.commit()

        payload = {
            "device_ids": [device_id],
            "config_version": "latest",
            "strategy": "atomic",
        }

        mock_task = MagicMock()
        mock_task.id = "celery-task-789"

        with patch("tasks.deployment.validate_and_deploy_task") as mock_deploy:
            mock_deploy.delay.return_value = mock_task
            r = client.post("/api/configs/deploy", json=payload)

        assert r.status_code == 200
        data = r.json()
        assert "batch_id" in data
        assert data["status"] == "QUEUED"
        assert data["strategy"] == "atomic"
        assert data["device_count"] == 1

    def test_deploy_device_not_found_returns_404(self, client):
        payload = {
            "device_ids": [str(uuid4())],
            "config_version": "latest",
            "strategy": "rolling",
        }

        with patch("tasks.deployment.validate_and_deploy_task"):
            r = client.post("/api/configs/deploy", json=payload)

        assert r.status_code == 404

    def test_deploy_multiple_devices(self, client, db_session, valid_bgp_state):
        from api.models import Device, Configuration

        device_ids = []
        for i in range(3):
            d = Device(
                hostname=f"deploy-r{i}-{uuid4().hex[:4]}",
                management_ip=f"10.1.{i}.1",
                device_type="cisco_xr",
            )
            db_session.add(d)
            db_session.commit()
            db_session.refresh(d)
            device_ids.append(str(d.id))
            db_session.add(
                Configuration(
                    device_id=d.id,
                    version="pending",
                    desired_state=valid_bgp_state,
                    status="PENDING",
                    created_by="test",
                )
            )
        db_session.commit()

        payload = {
            "device_ids": device_ids,
            "config_version": "latest",
            "strategy": "canary",
        }

        mock_task = MagicMock()
        mock_task.id = "batch-task-xyz"

        with patch("tasks.deployment.validate_and_deploy_task") as mock_deploy:
            mock_deploy.delay.return_value = mock_task
            r = client.post("/api/configs/deploy", json=payload)

        assert r.status_code == 200
        data = r.json()
        assert data["device_count"] == 3
        assert data["strategy"] == "canary"

    def test_deploy_missing_config_returns_422(self, client, device_id):
        payload = {
            "device_ids": [device_id],
            "config_version": "latest",
            "strategy": "atomic",
        }

        with patch("tasks.deployment.validate_and_deploy_task"):
            r = client.post("/api/configs/deploy", json=payload)

        assert r.status_code == 422
        detail = r.json()["detail"]
        assert device_id in detail["missing_device_ids"]

    def test_deploy_task_id_in_response(self, client, device_id, valid_bgp_state, db_session):
        from api.models import Configuration

        db_session.add(
            Configuration(
                device_id=device_id,
                version="pending",
                desired_state=valid_bgp_state,
                status="PENDING",
                created_by="test",
            )
        )
        db_session.commit()

        payload = {
            "device_ids": [device_id],
            "config_version": "latest",
            "strategy": "rolling",
        }

        mock_task = MagicMock()
        mock_task.id = "specific-task-id-999"

        with patch("tasks.deployment.validate_and_deploy_task") as mock_deploy:
            mock_deploy.delay.return_value = mock_task
            r = client.post("/api/configs/deploy", json=payload)

        data = r.json()
        assert data["task_id"] == "specific-task-id-999"


# ---------------------------------------------------------------------------
# diff — device not found (404 path)
# ---------------------------------------------------------------------------

class TestConfigDiffEndpoint:
    def test_diff_device_not_found(self, client):
        r = client.get(f"/api/configs/diff?device_id={uuid4()}")
        assert r.status_code == 404
