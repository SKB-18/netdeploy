"""Unit tests for Celery deployment tasks (tasks/deployment.py)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# validate_and_deploy_task
# ---------------------------------------------------------------------------

class TestValidateAndDeployTask:
    def test_task_exists(self):
        from tasks.deployment import validate_and_deploy_task
        assert callable(validate_and_deploy_task)

    def test_task_calls_orchestrator_deploy(self):
        """Task calls DeploymentOrchestrator.deploy() and returns result."""
        from tasks.deployment import validate_and_deploy_task

        mock_result = {"status": "SUCCESS", "batch_id": "batch-1", "affected_devices": ["d1"]}

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.deploy = AsyncMock(return_value=mock_result)

            result = validate_and_deploy_task(
                device_ids=["d1"],
                config_version="latest",
                strategy="atomic",
                batch_id="batch-1",
                user_id="admin",
            )

        assert result["status"] == "SUCCESS"

    def test_task_uses_provided_batch_id(self):
        """Provided batch_id is passed through to orchestrator."""
        from tasks.deployment import validate_and_deploy_task

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.deploy = AsyncMock(return_value={"status": "SUCCESS"})

            result = validate_and_deploy_task(
                device_ids=["d1"],
                config_version="latest",
                strategy="canary",
                batch_id="my-batch-123",
            )

        assert result["status"] == "SUCCESS"

    def test_task_generates_batch_id_if_none(self):
        """If batch_id is None, a UUID is generated."""
        from tasks.deployment import validate_and_deploy_task

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch.deploy = AsyncMock(return_value={"status": "SUCCESS", "batch_id": "auto"})

            result = validate_and_deploy_task(
                device_ids=["d1"],
                config_version="latest",
                strategy="rolling",
                batch_id=None,
            )

        assert result["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# deploy_to_device
# ---------------------------------------------------------------------------

class TestDeployToDeviceTask:
    def test_task_exists(self):
        from tasks.deployment import deploy_to_device
        assert callable(deploy_to_device)

    def test_task_calls_orchestrator_deploy_to_device(self):
        """Task calls _deploy_to_device and returns result."""
        from tasks.deployment import deploy_to_device

        mock_result = {"success": True, "device_id": "dev-1", "time_taken": 1.23}

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch._deploy_to_device = AsyncMock(return_value=mock_result)

            result = deploy_to_device(
                device_id="dev-1",
                config_version="latest",
                batch_id="batch-1",
                user_id="admin",
            )

        assert result["success"] is True

    def test_task_passes_config_version(self):
        from tasks.deployment import deploy_to_device

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch._deploy_to_device = AsyncMock(
                return_value={"success": True, "device_id": "d1"}
            )

            result = deploy_to_device(device_id="d1", config_version="v1.2.3")

        assert result["success"] is True


# ---------------------------------------------------------------------------
# rollback_device
# ---------------------------------------------------------------------------

class TestRollbackDeviceTask:
    def test_task_exists(self):
        from tasks.deployment import rollback_device
        assert callable(rollback_device)

    def test_rollback_calls_orchestrator(self):
        """rollback_device task calls orchestrator._rollback_device."""
        from tasks.deployment import rollback_device

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch._rollback_device = AsyncMock(return_value=True)

            result = rollback_device(
                device_id="dev-1",
                deployment_id="dep-1",
                user_id="admin",
            )

        assert result["success"] is True
        assert result["device_id"] == "dev-1"

    def test_rollback_failure_returns_false(self):
        from tasks.deployment import rollback_device

        with patch("core.orchestrator.DeploymentOrchestrator") as MockOrch:
            mock_orch = MockOrch.return_value
            mock_orch._rollback_device = AsyncMock(return_value=False)

            result = rollback_device(device_id="dev-1", user_id="admin")

        assert result["success"] is False


# ---------------------------------------------------------------------------
# sync_device_state
# ---------------------------------------------------------------------------

class TestSyncDeviceStateTask:
    def test_task_exists(self):
        from tasks.deployment import sync_device_state
        assert callable(sync_device_state)

    def test_sync_returns_status(self):
        from tasks.deployment import sync_device_state

        result = sync_device_state(device_id="dev-1")
        assert isinstance(result, dict)
        assert result["device_id"] == "dev-1"
        assert "status" in result


# ---------------------------------------------------------------------------
# check_deployment_health
# ---------------------------------------------------------------------------

class TestCheckDeploymentHealthTask:
    def test_task_exists(self):
        from tasks.deployment import check_deployment_health
        assert callable(check_deployment_health)

    def test_check_returns_status(self):
        from tasks.deployment import check_deployment_health

        result = check_deployment_health(deployment_id="dep-1")
        assert isinstance(result, dict)
        assert result["deployment_id"] == "dep-1"
        assert "status" in result
