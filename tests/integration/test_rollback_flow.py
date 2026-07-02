"""
Phase 3 integration tests for rollback flow.

Cowork provides rollback scenarios with mocked SSH + DB.
Cursor implements:
  - DeploymentOrchestrator._rollback_device() (core/orchestrator.py)
  - SnapshotManager.restore_snapshot() (core/snapshot_manager.py)
  - All SSH calls are patched — no real network needed.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def device_id():
    return uuid4()


@pytest.fixture
def deployment_id():
    return uuid4()


@pytest.fixture
def mock_device(device_id):
    device = MagicMock()
    device.id = device_id
    device.hostname = "leaf-01"
    device.management_ip = "10.200.0.1"
    device.device_type = "cisco_xr"
    device.ssh_port = 22
    device.username = "admin"
    device.password = "test"
    return device


@pytest.fixture
def before_snapshot(deployment_id, device_id):
    snap = MagicMock()
    snap.id = uuid4()
    snap.deployment_id = deployment_id
    snap.device_id = device_id
    snap.is_before = True
    snap.config_data = {
        "config": "router bgp 65000\n neighbor 10.0.0.1 remote-as 65001\n"
    }
    snap.config_hash = "sha256:abc123"
    return snap


@pytest.fixture
def mock_db(mock_device, before_snapshot, deployment_id):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = mock_device

    # For snapshot lookup
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = before_snapshot
    db.query.return_value.filter.return_value.all.return_value = [before_snapshot]
    return db


@pytest.fixture
def mock_ssh():
    ssh = MagicMock()
    ssh.connect = AsyncMock(return_value=True)
    ssh.disconnect = AsyncMock()
    ssh.get_running_config = AsyncMock(return_value="! running config")
    ssh.send_config_set = AsyncMock(return_value=True)
    ssh.get_bgp_summary = AsyncMock(return_value="BGP summary")
    ssh.get_ospf_neighbors = AsyncMock(return_value="")
    ssh.ping = AsyncMock(return_value="Success rate 100%")
    return ssh


# ---------------------------------------------------------------------------
# _rollback_device tests
# ---------------------------------------------------------------------------

class TestRollbackDevice:
    @pytest.mark.asyncio
    async def test_rollback_returns_bool(self, mock_db, device_id):
        """_rollback_device returns True/False regardless of outcome."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        result = await orch._rollback_device(str(device_id), "user-1")
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_rollback_device_not_found(self, mock_db):
        """Returns False when device doesn't exist in DB."""
        from core.orchestrator import DeploymentOrchestrator
        mock_db.query.return_value.filter.return_value.first.return_value = None
        orch = DeploymentOrchestrator(db_session=mock_db)

        result = await orch._rollback_device(str(uuid4()), "user-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback_writes_audit_entry(self, mock_db, device_id):
        """Rollback writes AuditLog with action=ROLLBACK."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._write_audit = MagicMock()

        await orch._rollback_device(str(device_id), "user-1")

        orch._write_audit.assert_called_once()
        _, action, _, _ = orch._write_audit.call_args[0]
        assert action == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_rollback_ssh_restore(self, mock_db, device_id):
        """
        _rollback_device should SSH connect, call SnapshotManager.restore_snapshot(),
        and return True on success.

        [CURSOR IMPLEMENTS full _rollback_device body]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            MockSSH.return_value = mock_ssh_instance

            mock_snap = MagicMock()
            mock_snap.restore_snapshot = AsyncMock(return_value=True)
            MockSnap.return_value = mock_snap

            result = await orch._rollback_device(str(device_id), "user-1")

        # After Cursor implements:
        # assert result is True
        # mock_snap.restore_snapshot.assert_awaited_once()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_rollback_ssh_failure_returns_false(self, mock_db, device_id):
        """SSH failure during rollback: log error, return False."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        with patch("core.ssh_handler.SSHDevice") as MockSSH:
            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(side_effect=ConnectionError("Refused"))
            mock_ssh_instance.disconnect = AsyncMock()
            MockSSH.return_value = mock_ssh_instance

            result = await orch._rollback_device(str(device_id), "user-1")

        # After Cursor implements, SSH failure → False
        # assert result is False
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_rollback_updates_deployment_status(self, mock_db, device_id):
        """
        _rollback_device should update Deployment.status to ROLLBACK.

        [CURSOR IMPLEMENTS — calls _update_deployment_status("ROLLBACK")]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._update_deployment_status = MagicMock()

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            MockSSH.return_value = mock_ssh_instance

            mock_snap = MagicMock()
            mock_snap.restore_snapshot = AsyncMock(return_value=True)
            MockSnap.return_value = mock_snap

            await orch._rollback_device(str(device_id), "user-1")

        # After Cursor implements:
        # orch._update_deployment_status.assert_called_with(any, "ROLLBACK")


# ---------------------------------------------------------------------------
# SnapshotManager.restore_snapshot tests
# ---------------------------------------------------------------------------

class TestRestoreSnapshot:
    @pytest.mark.asyncio
    async def test_restore_applies_before_config(self, before_snapshot):
        """
        restore_snapshot fetches BEFORE snapshot, applies it via SSH.

        [CURSOR IMPLEMENTS restore_snapshot in SnapshotManager]
        """
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = before_snapshot

        mock_ssh = MagicMock()
        mock_ssh.send_config_set = AsyncMock(return_value=True)

        sm = SnapshotManager(mock_db, mock_ssh)

        dep_id = before_snapshot.deployment_id
        dev_id = before_snapshot.device_id

        result = await sm.restore_snapshot(dep_id, dev_id)
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_restore_no_before_snapshot_returns_false(self):
        """restore_snapshot returns False when no BEFORE snapshot found."""
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        mock_ssh = MagicMock()
        sm = SnapshotManager(mock_db, mock_ssh)

        result = await sm.restore_snapshot(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_calls_send_config_set(self, before_snapshot):
        """
        After finding BEFORE snapshot, restore_snapshot calls ssh.send_config_set.

        [CURSOR IMPLEMENTS]
        """
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = before_snapshot

        mock_ssh = MagicMock()
        mock_ssh.send_config_set = AsyncMock(return_value=True)
        sm = SnapshotManager(mock_db, mock_ssh)

        await sm.restore_snapshot(before_snapshot.deployment_id, before_snapshot.device_id)

        # After Cursor implements:
        # mock_ssh.send_config_set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_restore_ssh_failure_returns_false(self, before_snapshot):
        """SSH send_config_set failure during restore → returns False."""
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = before_snapshot

        mock_ssh = MagicMock()
        mock_ssh.send_config_set = AsyncMock(return_value=False)
        sm = SnapshotManager(mock_db, mock_ssh)

        result = await sm.restore_snapshot(before_snapshot.deployment_id, before_snapshot.device_id)
        # After Cursor implements:
        # assert result is False
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Rollback via API endpoint
# ---------------------------------------------------------------------------

class TestRollbackAPIEndpoint:
    def test_rollback_queued_for_success_deployment(self, client, db_session):
        """
        POST /api/deployments/{id}/rollback enqueues rollback Celery task
        when Deployment.status == SUCCESS.

        [CURSOR IMPLEMENTS via conftest fixtures + db_session]
        """
        # Placeholder — Cursor wires real DB fixture:
        # from api.models import Deployment
        # dep = Deployment(device_id=..., status="SUCCESS", ...)
        # db_session.add(dep); db_session.commit()
        # with patch("tasks.deployment.rollback_device.delay") as mock_task:
        #     mock_task.return_value = MagicMock(id="task-abc")
        #     resp = client.post(f"/api/deployments/{dep.id}/rollback", json={"reason": "test"})
        # assert resp.status_code == 200
        # data = resp.json()
        # assert data["status"] == "ROLLBACK_QUEUED"
        # assert "task_id" in data
        pass

    def test_rollback_rejected_for_in_progress(self, client, db_session):
        """
        POST rollback returns 400 when Deployment.status == IN_PROGRESS.

        [CURSOR IMPLEMENTS]
        """
        # dep = Deployment(status="IN_PROGRESS", ...)
        # resp = client.post(f"/api/deployments/{dep.id}/rollback", json={})
        # assert resp.status_code == 400
        pass

    def test_rollback_404_unknown_deployment(self, client):
        """POST rollback returns 404 for unknown deployment_id."""
        # resp = client.post(f"/api/deployments/{uuid4()}/rollback", json={})
        # assert resp.status_code == 404
        pass


# ---------------------------------------------------------------------------
# _rollback_all end-to-end
# ---------------------------------------------------------------------------

class TestRollbackAllStrategy:
    @pytest.mark.asyncio
    async def test_rollback_all_calls_per_device(self, mock_db):
        """_rollback_all calls _rollback_device for every device ID."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._rollback_device = AsyncMock(return_value=True)

        device_ids = [str(uuid4()) for _ in range(4)]
        result = await orch._rollback_all(device_ids, "user-1")

        assert orch._rollback_device.await_count == 4

    @pytest.mark.asyncio
    async def test_rollback_all_parallel(self, mock_db):
        """_rollback_all runs rollbacks concurrently (asyncio.gather)."""
        import asyncio
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        started = []

        async def slow_rollback(device_id, user_id):
            started.append(device_id)
            await asyncio.sleep(0.01)
            return True

        orch._rollback_device = slow_rollback

        device_ids = [str(uuid4()) for _ in range(3)]
        await orch._rollback_all(device_ids, "user-1")

        assert set(started) == set(device_ids)

    @pytest.mark.asyncio
    async def test_rollback_all_returns_false_if_any_fails(self, mock_db):
        """_rollback_all returns False when any individual rollback fails."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        call_count = 0

        async def partial_fail(device_id, user_id):
            nonlocal call_count
            call_count += 1
            return call_count != 2  # second call fails

        orch._rollback_device = partial_fail

        result = await orch._rollback_all(["d1", "d2", "d3"], "user-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_rollback_all_returns_true_all_succeed(self, mock_db):
        """_rollback_all returns True when all rollbacks succeed."""
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._rollback_device = AsyncMock(return_value=True)

        result = await orch._rollback_all(["d1", "d2"], "user-1")
        assert result is True


# ---------------------------------------------------------------------------
# Atomic rollback after partial failure
# ---------------------------------------------------------------------------

class TestAtomicRollbackOnFailure:
    @pytest.mark.asyncio
    async def test_atomic_deploy_one_failure_triggers_rollback_all(self, mock_db):
        """
        In atomic strategy: one device fails → all devices rolled back,
        including those that succeeded.

        [CURSOR IMPLEMENTS full _deploy_atomic + _rollback_all hand-off]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        call_count = 0

        async def one_fails(device_id, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"success": call_count != 2}  # d2 fails

        orch._deploy_to_device = one_fails
        orch._rollback_all = AsyncMock(return_value=True)

        result = await orch._deploy_atomic(["d1", "d2", "d3"], "latest", "batch-x", "user-1")

        assert result["status"] == "ROLLBACK"
        orch._rollback_all.assert_awaited_once()

        # All 3 IDs — including the 2 that succeeded — passed to rollback
        rolled_back = orch._rollback_all.call_args[0][0]
        assert len(rolled_back) == 3
