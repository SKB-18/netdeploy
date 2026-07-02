"""
Phase 4 unit tests for NetDeployClient.

All HTTP calls are mocked with responses.mock or unittest.mock.
Cursor implements the client method bodies; these tests verify them.
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4


@pytest.fixture
def client():
    from dashboard.utils.api_client import NetDeployClient
    return NetDeployClient(api_url="http://localhost:8000", timeout=5)


@pytest.fixture
def device_id():
    return str(uuid4())


@pytest.fixture
def deployment_id():
    return str(uuid4())


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthCheck:
    def test_healthy_api(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: {"status": "healthy"}
            )
            assert client.health_check() is True

    def test_unhealthy_api_error_status(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: {"status": "error"}
            )
            assert client.health_check() is False

    def test_unreachable_api(self, client):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            assert client.health_check() is False

    def test_500_response(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=500)
            mock_get.return_value.json.side_effect = Exception("no json")
            assert client.health_check() is False


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

class TestListDevices:
    def test_returns_list(self, client):
        devices = [{"id": str(uuid4()), "hostname": "r1", "device_type": "cisco_xr"}]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: devices
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.list_devices()
        assert result == devices

    def test_returns_empty_on_error(self, client):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.list_devices()
        assert result == []

    def test_returns_empty_on_500(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=500)
            mock_get.return_value.raise_for_status.side_effect = Exception("500")
            result = client.list_devices()
        assert result == []


class TestGetDevice:
    def test_returns_device_dict(self, client, device_id):
        device = {"id": device_id, "hostname": "r1"}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: device
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_device(device_id)
        assert result == device

    def test_returns_none_on_404(self, client, device_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            mock_get.return_value.raise_for_status.side_effect = Exception("404")
            result = client.get_device(device_id)
        assert result is None


class TestCreateDevice:
    def test_creates_device(self, client):
        created = {"id": str(uuid4()), "hostname": "new-router"}
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=201, json=lambda: created
            )
            mock_post.return_value.raise_for_status = MagicMock()
            result = client.create_device({"hostname": "new-router", "management_ip": "10.0.0.1", "device_type": "cisco_xr"})
        assert result == created

    def test_returns_none_on_conflict(self, client):
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=409)
            mock_post.return_value.raise_for_status.side_effect = Exception("409 Conflict")
            result = client.create_device({"hostname": "duplicate"})
        assert result is None


class TestCheckDeviceHealth:
    def test_healthy_device(self, client, device_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: {"healthy": True, "message": "All checks passed"}
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.check_device_health(device_id)
        assert result["healthy"] is True

    def test_unhealthy_device(self, client, device_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: {"healthy": False, "message": "BGP down"}
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.check_device_health(device_id)
        assert result["healthy"] is False

    def test_unreachable_returns_none(self, client, device_id):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.check_device_health(device_id)
        assert result is None


class TestSyncDevice:
    def test_sync_success(self, client, device_id):
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: {"status": "SYNC_QUEUED", "task_id": "t1"}
            )
            mock_post.return_value.raise_for_status = MagicMock()
            result = client.sync_device(device_id)
        assert result is not None

    def test_sync_failure_returns_none(self, client, device_id):
        with patch.object(client.session, "post", side_effect=ConnectionError()):
            result = client.sync_device(device_id)
        assert result is None


class TestDeleteDevice:
    def test_delete_success(self, client, device_id):
        with patch.object(client.session, "delete") as mock_del:
            mock_del.return_value = MagicMock(status_code=204)
            mock_del.return_value.raise_for_status = MagicMock()
            result = client.delete_device(device_id)
        assert result is True

    def test_delete_not_found_returns_false(self, client, device_id):
        with patch.object(client.session, "delete") as mock_del:
            mock_del.return_value = MagicMock(status_code=404)
            mock_del.return_value.raise_for_status.side_effect = Exception("404")
            result = client.delete_device(device_id)
        assert result is False


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------

class TestListDeployments:
    def test_returns_list(self, client):
        deps = [{"id": str(uuid4()), "status": "SUCCESS"}]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: deps
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.list_deployments()
        assert result == deps

    def test_passes_limit_param(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: []
            )
            mock_get.return_value.raise_for_status = MagicMock()
            client.list_deployments(limit=50)
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["limit"] == 50

    def test_status_filter_passed(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: []
            )
            mock_get.return_value.raise_for_status = MagicMock()
            client.list_deployments(status="SUCCESS")
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"].get("status") == "SUCCESS"


class TestGetDeploymentLogs:
    def test_returns_logs_dict(self, client, deployment_id):
        logs_data = {"logs": ["step1", "step2"], "log_count": 2, "status": "SUCCESS"}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: logs_data
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_deployment_logs(deployment_id)
        assert result["log_count"] == 2
        assert len(result["logs"]) == 2

    def test_returns_none_on_error(self, client, deployment_id):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.get_deployment_logs(deployment_id)
        assert result is None


class TestGetDeploymentSnapshot:
    def test_returns_snapshot_dict(self, client, deployment_id):
        snap_data = {"snapshots": [], "diff": None}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: snap_data
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_deployment_snapshot(deployment_id)
        assert "snapshots" in result

    def test_passes_device_id_param(self, client, deployment_id, device_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: {"snapshots": []}
            )
            mock_get.return_value.raise_for_status = MagicMock()
            client.get_deployment_snapshot(deployment_id, device_id=device_id)
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"].get("device_id") == device_id


class TestTriggerDeployment:
    def test_returns_batch_id(self, client, device_id):
        batch_id = str(uuid4())
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: {"batch_id": batch_id, "status": "QUEUED"}
            )
            mock_post.return_value.raise_for_status = MagicMock()
            result = client.trigger_deployment([device_id], "latest", "atomic")
        assert result == batch_id

    def test_returns_none_on_error(self, client, device_id):
        with patch.object(client.session, "post", side_effect=ConnectionError()):
            result = client.trigger_deployment([device_id], "latest")
        assert result is None


class TestRollbackDeployment:
    def test_returns_task_id(self, client, deployment_id):
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"status": "ROLLBACK_QUEUED", "task_id": "task-abc"}
            )
            mock_post.return_value.raise_for_status = MagicMock()
            result = client.rollback_deployment(deployment_id)
        assert result == "task-abc"

    def test_returns_none_on_failure(self, client, deployment_id):
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=400)
            mock_post.return_value.raise_for_status.side_effect = Exception("400")
            result = client.rollback_deployment(deployment_id)
        assert result is None


# ---------------------------------------------------------------------------
# Configurations
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def test_valid_config(self, client, device_id):
        resp = {"valid": True, "errors": [], "warnings": []}
        with patch.object(client.session, "post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200, json=lambda: resp
            )
            mock_post.return_value.raise_for_status = MagicMock()
            result = client.validate_config(device_id, {"bgp": {"local_asn": 65001}})
        assert result["valid"] is True

    def test_returns_none_on_error(self, client, device_id):
        with patch.object(client.session, "post", side_effect=ConnectionError()):
            result = client.validate_config(device_id, {})
        assert result is None


class TestGetConfigHistory:
    def test_returns_list(self, client, device_id):
        history = [{"version": "abc123", "status": "SYNCED"}]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: history
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_config_history(device_id)
        assert result == history

    def test_returns_empty_on_error(self, client, device_id):
        with patch.object(client.session, "get", side_effect=Exception("fail")):
            result = client.get_config_history(device_id)
        assert result == []


# ---------------------------------------------------------------------------
# Update device
# ---------------------------------------------------------------------------

class TestUpdateDevice:
    def test_updates_device(self, client, device_id):
        updated = {"id": device_id, "hostname": "updated-r1", "os_version": "8.0"}
        with patch.object(client.session, "put") as mock_put:
            mock_put.return_value = MagicMock(status_code=200, json=lambda: updated)
            mock_put.return_value.raise_for_status = MagicMock()
            result = client.update_device(device_id, {"os_version": "8.0"})
        assert result == updated

    def test_update_not_found_returns_none(self, client, device_id):
        with patch.object(client.session, "put") as mock_put:
            mock_put.return_value = MagicMock(status_code=404)
            mock_put.return_value.raise_for_status.side_effect = Exception("404")
            result = client.update_device(device_id, {})
        assert result is None

    def test_update_connection_error_returns_none(self, client, device_id):
        with patch.object(client.session, "put", side_effect=ConnectionError()):
            result = client.update_device(device_id, {"hostname": "new"})
        assert result is None


# ---------------------------------------------------------------------------
# Get deployment (single)
# ---------------------------------------------------------------------------

class TestGetDeployment:
    def test_returns_deployment_dict(self, client, deployment_id):
        dep = {"id": deployment_id, "status": "SUCCESS", "strategy": "atomic"}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: dep)
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_deployment(deployment_id)
        assert result == dep

    def test_returns_none_on_404(self, client, deployment_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            mock_get.return_value.raise_for_status.side_effect = Exception("404")
            result = client.get_deployment(deployment_id)
        assert result is None

    def test_returns_none_on_connection_error(self, client, deployment_id):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.get_deployment(deployment_id)
        assert result is None


# ---------------------------------------------------------------------------
# Get batch
# ---------------------------------------------------------------------------

class TestGetBatch:
    def test_returns_batch_dict(self, client):
        batch_id = str(uuid4())
        batch = {"batch_id": batch_id, "total": 2, "deployments": []}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: batch)
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_batch(batch_id)
        assert result["batch_id"] == batch_id
        assert result["total"] == 2

    def test_returns_none_on_404(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=404)
            mock_get.return_value.raise_for_status.side_effect = Exception("404")
            result = client.get_batch("nonexistent")
        assert result is None

    def test_returns_none_on_error(self, client):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.get_batch("any-batch")
        assert result is None


# ---------------------------------------------------------------------------
# Get config diff
# ---------------------------------------------------------------------------

class TestGetConfigDiff:
    def test_returns_diff_dict(self, client, device_id):
        diff = {"device_id": device_id, "diff": "--- before\n+++ after\n"}
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: diff)
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_config_diff(device_id)
        assert "diff" in result

    def test_device_id_in_params(self, client, device_id):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: {})
            mock_get.return_value.raise_for_status = MagicMock()
            client.get_config_diff(device_id)
        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["device_id"] == device_id

    def test_returns_none_on_error(self, client, device_id):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.get_config_diff(device_id)
        assert result is None


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class TestGetAuditLog:
    def test_returns_entries(self, client):
        entries = [{"action": "DEPLOY", "user_id": "admin"}]
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: entries
            )
            mock_get.return_value.raise_for_status = MagicMock()
            result = client.get_audit_log()
        assert result == entries

    def test_filters_passed_to_params(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: []
            )
            mock_get.return_value.raise_for_status = MagicMock()
            client.get_audit_log(user="admin", action="DEPLOY", limit=50)
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["user_id"] == "admin"
        assert params["action"] == "DEPLOY"
        assert params["limit"] == 50

    def test_resource_type_filter_passed(self, client):
        with patch.object(client.session, "get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=lambda: [])
            mock_get.return_value.raise_for_status = MagicMock()
            client.get_audit_log(resource_type="Device")
        params = mock_get.call_args[1]["params"]
        assert params["resource_type"] == "Device"

    def test_returns_empty_on_error(self, client):
        with patch.object(client.session, "get", side_effect=ConnectionError()):
            result = client.get_audit_log()
        assert result == []
