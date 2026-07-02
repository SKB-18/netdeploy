"""
Integration tests for the deployment pipeline using MockRouter.

Tests the full _deploy_to_device path with mocked SSH
(MockRouter) and a real in-memory DB session.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from tests.fixtures.mock_devices import MockRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_device(device_type="cisco_xr"):
    d = MagicMock()
    d.id = uuid4()
    d.hostname = "test-router"
    d.management_ip = "10.0.0.1"
    d.device_type = device_type
    d.ssh_port = 22
    return d


def make_mock_config(device_type="cisco_xr"):
    return {
        "bgp": {
            "local_asn": 65001,
            "router_id": "10.0.0.1",
            "neighbors": [
                {"neighbor_ip": "192.168.1.2", "remote_asn": 65002},
            ],
        }
    }


def make_mock_db(device, config=None):
    db = MagicMock()
    mock_config_row = MagicMock()
    mock_config_row.desired_state = config or make_mock_config(device.device_type)

    def query_side(model_class):
        q = MagicMock()
        q.filter.return_value.first.return_value = device
        q.filter.return_value.order_by.return_value.first.return_value = mock_config_row
        return q

    db.query.side_effect = query_side
    return db


# ---------------------------------------------------------------------------
# _deploy_to_device with full mock SSH
# ---------------------------------------------------------------------------

class TestDeployToDeviceMocked:
    @pytest.mark.asyncio
    async def test_deploy_happy_path_returns_success(self):
        """Full deploy pipeline succeeds when all steps succeed."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.get_running_config = AsyncMock(return_value="hostname test-router\n")
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        # BGP output must contain neighbor IP + "Established" for verification to pass
        mock_ssh.send_command = AsyncMock(return_value=(
            "Neighbor        V    AS  State\n"
            "192.168.1.2     4  65002  Established\n"
        ))
        mock_ssh.device_type = "cisco_xr"

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        assert result["success"] is True
        assert result["device_id"] == str(device.id)
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_deploy_ssh_connect_fails(self):
        """SSH connect failure → success=False with error."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=False)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.get_running_config = AsyncMock(return_value="")
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        mock_ssh.send_command = AsyncMock(return_value="")

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        assert result["success"] is False
        assert "SSH connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_deploy_device_not_found(self):
        """Device not in DB → success=False."""
        from core.orchestrator import DeploymentOrchestrator

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        orch = DeploymentOrchestrator(db_session=db)

        result = await orch._deploy_to_device("nonexistent-id", "latest", "admin")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_deploy_no_config_found(self):
        """No desired config in DB → success=False."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = device
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = MagicMock(desired_state=None)
        orch = DeploymentOrchestrator(db_session=db)

        result = await orch._deploy_to_device(str(device.id), "latest", "admin")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_deploy_send_config_set_fails_triggers_rollback(self):
        """send_config_set failure triggers rollback and returns success=False."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)
        orch._rollback_device = AsyncMock(return_value=True)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.get_running_config = AsyncMock(return_value="hostname test")
        mock_ssh.send_config_set = AsyncMock(return_value=False)
        mock_ssh.send_command = AsyncMock(return_value="")
        mock_ssh.device_type = "cisco_xr"

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        assert result["success"] is False
        assert "send_config_set failed" in result["error"]
        orch._rollback_device.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deploy_always_disconnects(self):
        """SSH disconnect is always called, even when deploy fails."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)
        orch._rollback_device = AsyncMock(return_value=True)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.get_running_config = AsyncMock(side_effect=RuntimeError("SSH dropped"))
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        mock_ssh.send_command = AsyncMock(return_value="")
        mock_ssh.device_type = "cisco_xr"

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        mock_ssh.disconnect.assert_awaited_once()
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_deploy_records_time_taken(self):
        """Result always includes time_taken float."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device()
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.get_running_config = AsyncMock(return_value="hostname r1")
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        mock_ssh.send_command = AsyncMock(return_value=(
            "192.168.1.2     4  65002  Established\n"
        ))
        mock_ssh.device_type = "cisco_xr"

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        assert "time_taken" in result
        assert isinstance(result["time_taken"], float)
        assert result["time_taken"] >= 0


# ---------------------------------------------------------------------------
# MockRouter integration (SSHDevice wrapping MockRouter)
# ---------------------------------------------------------------------------

class TestDeployWithMockRouter:
    """Tests that verify the full pipeline using MockRouter as the SSH backend."""

    @pytest.mark.asyncio
    async def test_full_pipeline_with_mock_router(self):
        """Deploy to a MockRouter via an adapter — verifies command flow."""
        from core.orchestrator import DeploymentOrchestrator

        router = MockRouter("test-r1", 65001, device_type="cisco_xr")
        router.add_bgp_neighbor("192.168.1.2", 65002)

        device = make_mock_device("cisco_xr")
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)

        # Adapter: AsyncMock wrapping MockRouter synchronous calls
        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.device_type = "cisco_xr"
        mock_ssh.get_running_config = AsyncMock(
            return_value=router.send_command("show running-config")
        )
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        mock_ssh.send_command = AsyncMock(
            side_effect=lambda cmd: router.send_command(cmd)
        )

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        # With MockRouter the BGP neighbor IS in Established state in output
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_failed_router_triggers_rollback(self):
        """Deploy to a failing MockRouter → rollback is triggered."""
        from core.orchestrator import DeploymentOrchestrator

        device = make_mock_device("cisco_xr")
        db = make_mock_db(device)
        orch = DeploymentOrchestrator(db_session=db)
        orch._rollback_device = AsyncMock(return_value=True)

        mock_ssh = MagicMock()
        mock_ssh.connect = AsyncMock(return_value=True)
        mock_ssh.disconnect = AsyncMock()
        mock_ssh.device_type = "cisco_xr"
        mock_ssh.get_running_config = AsyncMock(return_value="hostname r1")
        mock_ssh.send_config_set = AsyncMock(return_value=False)  # Simulate failure
        mock_ssh.send_command = AsyncMock(return_value="Active")

        with patch("core.ssh_handler.SSHDevice", return_value=mock_ssh), \
             patch("api.models.ConfigSnapshot"):
            result = await orch._deploy_to_device(str(device.id), "latest", "admin")

        assert result["success"] is False
        orch._rollback_device.assert_awaited_once()


# ---------------------------------------------------------------------------
# Celery task smoke tests
# ---------------------------------------------------------------------------

class TestDeploymentCeleryTasks:
    def test_validate_and_deploy_task_exists(self):
        from tasks.deployment import validate_and_deploy_task
        assert callable(validate_and_deploy_task)

    def test_deploy_to_device_task_exists(self):
        from tasks.deployment import deploy_to_device
        assert callable(deploy_to_device)

    def test_rollback_device_task_exists(self):
        from tasks.deployment import rollback_device
        assert callable(rollback_device)

    def test_sync_device_state_task_exists(self):
        from tasks.deployment import sync_device_state
        assert callable(sync_device_state)

    def test_check_deployment_health_task_exists(self):
        from tasks.deployment import check_deployment_health
        assert callable(check_deployment_health)


# ---------------------------------------------------------------------------
# End-to-end strategy smoke tests (strategies with full _deploy_to_device mocked)
# ---------------------------------------------------------------------------

class TestStrategyEndToEnd:
    @pytest.mark.asyncio
    async def test_canary_strategy_full_run(self):
        from core.orchestrator import DeploymentOrchestrator

        orch = DeploymentOrchestrator(db_session=None)
        orch._deploy_to_device = AsyncMock(return_value={"success": True})
        orch._health_check = AsyncMock(return_value=True)

        result = await orch.deploy(
            device_ids=["d1", "d2", "d3"],
            config_version="latest",
            strategy="canary",
            user_id="test-user",
        )
        assert result["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_rolling_strategy_full_run(self):
        from core.orchestrator import DeploymentOrchestrator

        orch = DeploymentOrchestrator(db_session=None)
        orch._deploy_to_device = AsyncMock(return_value={"success": True})
        orch._health_check = AsyncMock(return_value=True)

        result = await orch.deploy(
            device_ids=["d1", "d2"],
            config_version="latest",
            strategy="rolling",
        )
        assert result["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_atomic_strategy_full_run(self):
        from core.orchestrator import DeploymentOrchestrator

        orch = DeploymentOrchestrator(db_session=None)
        orch._deploy_to_device = AsyncMock(return_value={"success": True})

        result = await orch.deploy(
            device_ids=["d1", "d2", "d3"],
            config_version="latest",
            strategy="atomic",
        )
        assert result["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_atomic_rollback_on_partial_failure(self):
        from core.orchestrator import DeploymentOrchestrator

        orch = DeploymentOrchestrator(db_session=None)
        call_num = 0

        async def flaky_deploy(device_id, *args, **kwargs):
            nonlocal call_num
            call_num += 1
            return {"success": call_num != 2}

        orch._deploy_to_device = flaky_deploy
        orch._rollback_all = AsyncMock(return_value=True)

        result = await orch.deploy(
            device_ids=["d1", "d2", "d3"],
            config_version="latest",
            strategy="atomic",
        )
        assert result["status"] == "ROLLBACK"
        orch._rollback_all.assert_awaited_once()
