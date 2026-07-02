"""
Phase 3 unit tests for DeploymentOrchestrator.

Cowork provides test cases + MockRouter wiring.
Cursor implements:
  - Any remaining [CURSOR IMPLEMENTS] methods in orchestrator.py that are
    called by the tests below.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_device():
    device = MagicMock()
    device.id = uuid4()
    device.hostname = "router-1"
    device.management_ip = "10.0.0.1"
    device.device_type = "cisco_xr"
    device.ssh_port = 22
    return device


@pytest.fixture
def mock_db(mock_device):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = mock_device
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = MagicMock(
        desired_state={"bgp": {"local_asn": 65001, "neighbors": []}}
    )
    return db


@pytest.fixture
def orchestrator(mock_db):
    from core.orchestrator import DeploymentOrchestrator
    return DeploymentOrchestrator(db_session=mock_db)


@pytest.fixture
def valid_desired_config():
    return {
        "bgp": {
            "local_asn": 65001,
            "router_id": "10.0.0.1",
            "neighbors": [
                {"neighbor_ip": "192.168.1.1", "remote_asn": 65002},
            ],
        }
    }


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------

class TestOrchestratorProperties:
    def test_command_builder_lazy_init(self, orchestrator):
        """CommandBuilder is not imported until first access."""
        assert orchestrator._command_builder is None
        _ = orchestrator.command_builder
        assert orchestrator._command_builder is not None

    def test_state_verifier_lazy_init(self, orchestrator):
        """StateVerifier is not imported until first access."""
        assert orchestrator._state_verifier is None
        _ = orchestrator.state_verifier
        assert orchestrator._state_verifier is not None

    def test_command_builder_cached(self, orchestrator):
        """Repeated access returns same instance."""
        cb1 = orchestrator.command_builder
        cb2 = orchestrator.command_builder
        assert cb1 is cb2

    def test_state_verifier_cached(self, orchestrator):
        sv1 = orchestrator.state_verifier
        sv2 = orchestrator.state_verifier
        assert sv1 is sv2


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------

class TestOrchestratorHelpers:
    def test_get_device_found(self, orchestrator, mock_db, mock_device):
        result = orchestrator._get_device(str(mock_device.id))
        assert result is mock_device

    def test_get_device_not_found(self, orchestrator, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = orchestrator._get_device(str(uuid4()))
        assert result is None

    def test_get_device_no_db(self):
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=None)
        assert orch._get_device(str(uuid4())) is None

    def test_get_desired_config_latest(self, orchestrator, mock_db):
        """Returns desired_state from most recent Configuration row."""
        config = MagicMock()
        config.desired_state = {"bgp": {"local_asn": 65001}}
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = config

        result = orchestrator._get_desired_config(str(uuid4()), "latest")
        assert result == {"bgp": {"local_asn": 65001}}

    def test_get_desired_config_no_config(self, orchestrator, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = orchestrator._get_desired_config(str(uuid4()), "latest")
        assert result is None

    def test_update_deployment_status_to_in_progress(self, orchestrator, mock_db):
        """Status update sets start_time when transitioning to IN_PROGRESS."""
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        mock_db.query.return_value.filter.return_value.first.return_value = deployment

        orchestrator._update_deployment_status(uuid4(), "IN_PROGRESS")
        assert deployment.status == "IN_PROGRESS"
        assert deployment.start_time is not None
        mock_db.commit.assert_called()

    def test_update_deployment_status_to_success(self, orchestrator, mock_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        mock_db.query.return_value.filter.return_value.first.return_value = deployment

        orchestrator._update_deployment_status(uuid4(), "SUCCESS")
        assert deployment.status == "SUCCESS"
        assert deployment.end_time is not None

    def test_update_deployment_status_with_error(self, orchestrator, mock_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        mock_db.query.return_value.filter.return_value.first.return_value = deployment

        orchestrator._update_deployment_status(uuid4(), "FAILED", error_message="SSH timeout")
        assert deployment.error_message == "SSH timeout"

    def test_update_deployment_status_missing_deployment(self, orchestrator, mock_db):
        """Missing deployment: log warning, do not crash."""
        mock_db.query.return_value.filter.return_value.first.return_value = None
        # Should not raise
        orchestrator._update_deployment_status(uuid4(), "SUCCESS")

    def test_write_audit(self, orchestrator, mock_db):
        orchestrator._write_audit("user-1", "DEPLOY", str(uuid4()), {"version": "abc"})
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called()

    def test_write_audit_no_db(self):
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=None)
        # Should not raise
        orch._write_audit("user-1", "DEPLOY", str(uuid4()), {})


# ---------------------------------------------------------------------------
# Strategy routing tests
# ---------------------------------------------------------------------------

class TestDeployStrategyRouting:
    @pytest.mark.asyncio
    async def test_deploy_routes_canary(self, orchestrator):
        orchestrator._deploy_canary = AsyncMock(return_value={"status": "SUCCESS"})
        result = await orchestrator.deploy(["d1"], "latest", strategy="canary")
        orchestrator._deploy_canary.assert_awaited_once()
        assert result["status"] == "SUCCESS"

    @pytest.mark.asyncio
    async def test_deploy_routes_rolling(self, orchestrator):
        orchestrator._deploy_rolling = AsyncMock(return_value={"status": "SUCCESS"})
        result = await orchestrator.deploy(["d1", "d2"], "latest", strategy="rolling")
        orchestrator._deploy_rolling.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deploy_routes_atomic(self, orchestrator):
        orchestrator._deploy_atomic = AsyncMock(return_value={"status": "SUCCESS"})
        result = await orchestrator.deploy(["d1", "d2"], "latest", strategy="atomic")
        orchestrator._deploy_atomic.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deploy_unknown_strategy(self, orchestrator):
        result = await orchestrator.deploy(["d1"], "latest", strategy="wizard")
        assert result["status"] == "FAILED"
        assert "Unknown strategy" in result["error"]


# ---------------------------------------------------------------------------
# Canary strategy tests
# ---------------------------------------------------------------------------

class TestCanaryStrategy:
    @pytest.mark.asyncio
    async def test_canary_happy_path(self, orchestrator):
        """Canary succeeds → rest deployed in parallel."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_canary(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "SUCCESS"
        # d1 is canary, d2+d3 are rest
        assert orchestrator._deploy_to_device.await_count == 3

    @pytest.mark.asyncio
    async def test_canary_fails_deployment(self, orchestrator):
        """Canary device deploy fails → abort immediately."""
        orchestrator._deploy_to_device = AsyncMock(
            return_value={"success": False, "error": "SSH timeout"}
        )
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_canary(["d1", "d2"], "latest", "batch-1", "user-1")
        assert result["status"] == "FAILED"
        # Only canary was tried
        orchestrator._deploy_to_device.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_canary_health_check_fails(self, orchestrator):
        """Canary deployed OK but health check fails → rollback + abort."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})
        orchestrator._health_check = AsyncMock(return_value=False)
        orchestrator._rollback_device = AsyncMock(return_value=True)

        result = await orchestrator._deploy_canary(["d1", "d2"], "latest", "batch-1", "user-1")
        assert result["status"] == "ROLLBACK"
        orchestrator._rollback_device.assert_awaited_once_with("d1", "user-1")

    @pytest.mark.asyncio
    async def test_canary_empty_device_list(self, orchestrator):
        result = await orchestrator._deploy_canary([], "latest", "batch-1", "user-1")
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_canary_single_device(self, orchestrator):
        """Single device: just the canary, no rest."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_canary(["d1"], "latest", "batch-1", "user-1")
        assert result["status"] == "SUCCESS"
        orchestrator._deploy_to_device.assert_awaited_once_with("d1", "latest", "user-1")


# ---------------------------------------------------------------------------
# Rolling strategy tests
# ---------------------------------------------------------------------------

class TestRollingStrategy:
    @pytest.mark.asyncio
    async def test_rolling_happy_path(self, orchestrator):
        """All devices succeed in sequence."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_rolling(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "SUCCESS"
        assert orchestrator._deploy_to_device.await_count == 3

    @pytest.mark.asyncio
    async def test_rolling_first_device_fails(self, orchestrator):
        orchestrator._deploy_to_device = AsyncMock(
            return_value={"success": False, "error": "Connection refused"}
        )
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_rolling(
            ["d1", "d2"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "FAILED"
        assert result["failed_at"] == "d1"
        assert result["completed"] == []
        # Rolling stops at first failure — d2 never tried
        orchestrator._deploy_to_device.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rolling_second_device_fails(self, orchestrator):
        call_count = 0

        async def side_effect(device_id, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"success": call_count == 1}  # d1 ok, d2 fails

        orchestrator._deploy_to_device = side_effect
        orchestrator._health_check = AsyncMock(return_value=True)

        result = await orchestrator._deploy_rolling(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "FAILED"
        assert result["failed_at"] == "d2"
        assert "d1" in result["completed"]

    @pytest.mark.asyncio
    async def test_rolling_health_check_fails(self, orchestrator):
        """Deploy succeeds but health check fails on second device."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})
        orchestrator._health_check = AsyncMock(side_effect=[True, False])

        result = await orchestrator._deploy_rolling(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_rolling_sequential_order(self, orchestrator):
        """Devices are deployed strictly in order."""
        order = []

        async def track_order(device_id, *args, **kwargs):
            order.append(device_id)
            return {"success": True}

        orchestrator._deploy_to_device = track_order
        orchestrator._health_check = AsyncMock(return_value=True)

        await orchestrator._deploy_rolling(["d1", "d2", "d3"], "latest", "batch-1", "user-1")
        assert order == ["d1", "d2", "d3"]


# ---------------------------------------------------------------------------
# Atomic strategy tests
# ---------------------------------------------------------------------------

class TestAtomicStrategy:
    @pytest.mark.asyncio
    async def test_atomic_happy_path(self, orchestrator):
        """All succeed in parallel."""
        orchestrator._deploy_to_device = AsyncMock(return_value={"success": True})

        result = await orchestrator._deploy_atomic(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "SUCCESS"
        assert orchestrator._deploy_to_device.await_count == 3

    @pytest.mark.asyncio
    async def test_atomic_one_fails_rollback_all(self, orchestrator):
        """One device fails → all devices rolled back."""
        call_count = 0

        async def side_effect(device_id, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"success": call_count != 2}  # d2 fails

        orchestrator._deploy_to_device = side_effect
        orchestrator._rollback_all = AsyncMock(return_value=True)

        result = await orchestrator._deploy_atomic(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "ROLLBACK"
        orchestrator._rollback_all.assert_awaited_once()
        # All 3 device IDs passed to rollback
        rollback_ids = orchestrator._rollback_all.call_args[0][0]
        assert set(rollback_ids) == {"d1", "d2", "d3"}

    @pytest.mark.asyncio
    async def test_atomic_exception_triggers_rollback(self, orchestrator):
        """Exception in one task also triggers rollback."""
        async def boom(device_id, *args, **kwargs):
            if device_id == "d2":
                raise RuntimeError("SSH error")
            return {"success": True}

        orchestrator._deploy_to_device = boom
        orchestrator._rollback_all = AsyncMock(return_value=True)

        result = await orchestrator._deploy_atomic(
            ["d1", "d2", "d3"], "latest", "batch-1", "user-1"
        )
        assert result["status"] == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_atomic_parallel_execution(self, orchestrator):
        """All deploys are launched concurrently (no sequential order dependency)."""
        import asyncio
        started = []

        async def slow_deploy(device_id, *args, **kwargs):
            started.append(device_id)
            await asyncio.sleep(0.01)
            return {"success": True}

        orchestrator._deploy_to_device = slow_deploy

        await orchestrator._deploy_atomic(["d1", "d2", "d3"], "latest", "batch-1", "user-1")
        assert set(started) == {"d1", "d2", "d3"}


# ---------------------------------------------------------------------------
# Health check + rollback tests
# ---------------------------------------------------------------------------

class TestHealthCheckAndRollback:
    @pytest.mark.asyncio
    async def test_health_check_no_device(self, orchestrator, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = await orchestrator._health_check("missing-device")
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_no_desired_config(self, orchestrator, mock_db, mock_device):
        # Device exists but no config
        mock_db.query.return_value.filter.return_value.first.return_value = mock_device
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        # Should return True — nothing to verify
        result = await orchestrator._health_check(str(mock_device.id))
        assert result is True

    @pytest.mark.asyncio
    async def test_rollback_no_device(self, orchestrator, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        result = await orchestrator._rollback_device("missing-device", "user-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback_writes_audit(self, orchestrator, mock_db, mock_device):
        mock_db.query.return_value.filter.return_value.first.return_value = mock_device
        orchestrator._write_audit = MagicMock()

        await orchestrator._rollback_device(str(mock_device.id), "user-1")
        orchestrator._write_audit.assert_called_once()
        call_args = orchestrator._write_audit.call_args[0]
        assert call_args[1] == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_rollback_all_parallel(self, orchestrator):
        """_rollback_all calls _rollback_device for all IDs."""
        orchestrator._rollback_device = AsyncMock(return_value=True)
        await orchestrator._rollback_all(["d1", "d2", "d3"], "user-1")
        assert orchestrator._rollback_device.await_count == 3
