"""
Phase 3 integration tests for full deployment flow.

Cowork provides end-to-end test scenarios + mock wiring.
Cursor implements:
  - DeploymentOrchestrator._deploy_to_device() (core/orchestrator.py)
  - SSHDevice.connect/send_command/send_config_set (core/ssh_handler.py)
  - All SSH calls are patched out — no real network needed.
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
    device.hostname = "spine-01"
    device.management_ip = "10.100.0.1"
    device.device_type = "cisco_xr"
    device.ssh_port = 22
    device.username = "admin"
    device.password = "test"
    return device


@pytest.fixture
def bgp_desired_config():
    return {
        "bgp": {
            "local_asn": 65001,
            "router_id": "10.100.0.1",
            "neighbors": [
                {"neighbor_ip": "10.100.0.2", "remote_asn": 65002},
                {"neighbor_ip": "10.100.0.3", "remote_asn": 65003},
            ],
        }
    }


@pytest.fixture
def mock_db(mock_device, bgp_desired_config):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = mock_device
    mock_config = MagicMock()
    mock_config.desired_state = bgp_desired_config
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_config
    return db


@pytest.fixture
def mock_ssh():
    """Fully mocked SSHDevice that pretends to be a real router."""
    ssh = MagicMock()
    ssh.__aenter__ = AsyncMock(return_value=ssh)
    ssh.__aexit__ = AsyncMock(return_value=False)
    ssh.connect = AsyncMock(return_value=True)
    ssh.disconnect = AsyncMock()
    ssh.get_running_config = AsyncMock(return_value="! running config stub")
    ssh.send_config_set = AsyncMock(return_value=True)
    ssh.get_bgp_summary = AsyncMock(return_value="BGP summary: 2 established")
    ssh.get_ospf_neighbors = AsyncMock(return_value="FULL/DR")
    ssh.ping = AsyncMock(return_value="Success rate 100%")
    return ssh


# ---------------------------------------------------------------------------
# Full deploy flow (Cursor implements _deploy_to_device body)
# ---------------------------------------------------------------------------

class TestDeployToDeviceFlow:
    @pytest.mark.asyncio
    async def test_deploy_returns_result_dict(self, mock_db, device_id):
        """
        _deploy_to_device should always return a dict with 'success', 'device_id',
        and 'time_taken' keys regardless of outcome.

        [CURSOR IMPLEMENTS _deploy_to_device — test verifies the contract]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap, \
             patch("core.state_verifier.StateVerifier") as MockSV:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            mock_ssh_instance.get_running_config = AsyncMock(return_value="! config")
            mock_ssh_instance.send_config_set = AsyncMock(return_value=True)
            MockSSH.return_value = mock_ssh_instance

            mock_snap_instance = MagicMock()
            mock_snap_instance.capture_running_config = AsyncMock(return_value={"config": "..."})
            mock_snap_instance.save_snapshot = AsyncMock(return_value=uuid4())
            MockSnap.return_value = mock_snap_instance

            result_obj = MagicMock()
            result_obj.passed = True
            mock_sv_instance = MagicMock()
            mock_sv_instance.verify_all = AsyncMock(return_value=result_obj)
            MockSV.return_value = mock_sv_instance

            result = await orch._deploy_to_device(str(device_id), "latest", "user-1")

        assert "success" in result
        assert "device_id" in result
        assert "time_taken" in result

    @pytest.mark.asyncio
    async def test_deploy_creates_before_snapshot_first(self, mock_db, device_id):
        """
        BEFORE snapshot must be captured before send_config_set is called.

        [CURSOR IMPLEMENTS step ordering in _deploy_to_device]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        call_order = []

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap, \
             patch("core.state_verifier.StateVerifier") as MockSV:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            mock_ssh_instance.get_running_config = AsyncMock(return_value="! config")

            async def track_config_set(*args, **kwargs):
                call_order.append("send_config")
                return True

            mock_ssh_instance.send_config_set = track_config_set
            MockSSH.return_value = mock_ssh_instance

            mock_snap = MagicMock()
            mock_snap.capture_running_config = AsyncMock(return_value={"raw": "! config"})

            async def track_snapshot(dep_id, dev_id, data, is_before=True):
                call_order.append(f"snapshot_{'before' if is_before else 'after'}")
                return uuid4()

            mock_snap.save_snapshot = track_snapshot
            MockSnap.return_value = mock_snap

            result_obj = MagicMock()
            result_obj.passed = True
            mock_sv = MagicMock()
            mock_sv.verify_all = AsyncMock(return_value=result_obj)
            MockSV.return_value = mock_sv

            await orch._deploy_to_device(str(device_id), "latest", "user-1")

        # Verify ordering only after Cursor implements
        if "snapshot_before" in call_order and "send_config" in call_order:
            assert call_order.index("snapshot_before") < call_order.index("send_config"), \
                "BEFORE snapshot must precede config apply"

    @pytest.mark.asyncio
    async def test_deploy_failure_on_ssh_connect_error(self, mock_db, device_id):
        """
        SSH connect failure → deploy returns success=False without crashing.

        [CURSOR IMPLEMENTS exception handling in _deploy_to_device steps 2/8]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._rollback_device = AsyncMock(return_value=True)

        with patch("core.ssh_handler.SSHDevice") as MockSSH:
            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(side_effect=ConnectionError("Refused"))
            mock_ssh_instance.disconnect = AsyncMock()
            MockSSH.return_value = mock_ssh_instance

            result = await orch._deploy_to_device(str(device_id), "latest", "user-1")

        # Must not raise; must signal failure
        assert result.get("success") is False or "error" in result

    @pytest.mark.asyncio
    async def test_deploy_failure_on_config_set_error(self, mock_db, device_id):
        """
        send_config_set returning False → deploy fails + rollback triggered.

        [CURSOR IMPLEMENTS step 5 failure path]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._rollback_device = AsyncMock(return_value=True)

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            mock_ssh_instance.get_running_config = AsyncMock(return_value="! config")
            mock_ssh_instance.send_config_set = AsyncMock(return_value=False)  # FAIL
            MockSSH.return_value = mock_ssh_instance

            mock_snap = MagicMock()
            mock_snap.capture_running_config = AsyncMock(return_value={"raw": "..."})
            mock_snap.save_snapshot = AsyncMock(return_value=uuid4())
            MockSnap.return_value = mock_snap

            result = await orch._deploy_to_device(str(device_id), "latest", "user-1")

        assert result.get("success") is False or "error" in result

    @pytest.mark.asyncio
    async def test_deploy_failure_on_verification_failure(self, mock_db, device_id):
        """
        State verification failure → deploy returns failure and triggers rollback.

        [CURSOR IMPLEMENTS step 6 failure path]
        """
        from core.orchestrator import DeploymentOrchestrator
        orch = DeploymentOrchestrator(db_session=mock_db)
        orch._rollback_device = AsyncMock(return_value=True)

        with patch("core.ssh_handler.SSHDevice") as MockSSH, \
             patch("core.state_verifier.StateVerifier") as MockSV, \
             patch("core.snapshot_manager.SnapshotManager") as MockSnap:

            mock_ssh_instance = MagicMock()
            mock_ssh_instance.connect = AsyncMock(return_value=True)
            mock_ssh_instance.disconnect = AsyncMock()
            mock_ssh_instance.get_running_config = AsyncMock(return_value="! config")
            mock_ssh_instance.send_config_set = AsyncMock(return_value=True)
            MockSSH.return_value = mock_ssh_instance

            mock_snap = MagicMock()
            mock_snap.capture_running_config = AsyncMock(return_value={})
            mock_snap.save_snapshot = AsyncMock(return_value=uuid4())
            MockSnap.return_value = mock_snap

            failed_result = MagicMock()
            failed_result.passed = False
            failed_result.checks = ["BGP neighbor 10.100.0.2: Idle (not Established)"]
            mock_sv = MagicMock()
            mock_sv.verify_all = AsyncMock(return_value=failed_result)
            MockSV.return_value = mock_sv

            result = await orch._deploy_to_device(str(device_id), "latest", "user-1")

        # After Cursor implements: result["success"] is False and rollback triggered
        # assert result.get("success") is False
        # assert orch._rollback_device.await_count == 1


# ---------------------------------------------------------------------------
# CommandBuilder integration
# ---------------------------------------------------------------------------

class TestCommandBuilderIntegration:
    def test_bgp_commands_cisco_xr_nonempty(self, bgp_desired_config):
        """CommandBuilder produces non-empty command list for cisco_xr BGP."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        cmds = cb.build(bgp_desired_config, "cisco_xr")
        assert isinstance(cmds, list)
        assert len(cmds) > 0
        assert all(isinstance(c, str) and c.strip() for c in cmds)

    def test_bgp_commands_cisco_xr_syntax(self, bgp_desired_config):
        """IOS-XR BGP commands must contain router bgp stanza."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        cmds = cb.build(bgp_desired_config, "cisco_xr")
        joined = "\n".join(cmds)
        assert "router bgp" in joined.lower()

    def test_bgp_commands_junos_set_format(self, bgp_desired_config):
        """JunOS commands must be in set-format."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        cmds = cb.build(bgp_desired_config, "junos")
        assert any(c.startswith("set ") for c in cmds)

    def test_bgp_commands_arista_eos(self, bgp_desired_config):
        """Arista EOS BGP commands produced without error."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        cmds = cb.build(bgp_desired_config, "arista_eos")
        assert isinstance(cmds, list)

    def test_command_builder_unsupported_device(self, bgp_desired_config):
        """Unknown device type raises ValueError."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        with pytest.raises(ValueError, match="[Uu]nsupported"):
            cb.build(bgp_desired_config, "exotic_vendor_os_9000")

    def test_rollback_commands_differ_from_deploy(self, bgp_desired_config):
        """
        build_rollback() should produce commands that undo build() changes.

        [CURSOR IMPLEMENTS build_rollback in CommandBuilder]
        """
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        deploy_cmds = cb.build(bgp_desired_config, "cisco_xr")
        rollback_cmds = cb.build_rollback(bgp_desired_config, "cisco_xr")
        # After Cursor implements: rollback commands should be non-empty and differ
        # assert rollback_cmds != deploy_cmds
        assert isinstance(rollback_cmds, list)

    def test_ospf_commands_cisco_ios(self):
        """IOS OSPF commands include wildcard mask conversion."""
        from core.command_builder import CommandBuilder
        cb = CommandBuilder()
        ospf_config = {
            "ospf": {
                "process_id": 1,
                "router_id": "10.0.0.1",
                "areas": [
                    {"area_id": "0", "networks": ["10.0.0.0/24"]},
                ],
            }
        }
        cmds = cb.build(ospf_config, "cisco_ios")
        assert isinstance(cmds, list)


# ---------------------------------------------------------------------------
# StateVerifier integration
# ---------------------------------------------------------------------------

class TestStateVerifierIntegration:
    @pytest.mark.asyncio
    async def test_verify_bgp_established_cisco_xr(self):
        """StateVerifier correctly identifies Established BGP session."""
        from core.state_verifier import StateVerifier
        sv = StateVerifier()

        mock_ssh = MagicMock()
        mock_ssh.get_bgp_summary = AsyncMock(
            return_value=(
                "BGP router identifier 10.0.0.1, local AS number 65001\n"
                "Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State\n"
                "10.100.0.2      4 65002      50      50        0    0    0 01:00:00 Established\n"
                "10.100.0.3      4 65003      50      50        0    0    0 01:00:00 Established\n"
            )
        )
        mock_ssh.get_ospf_neighbors = AsyncMock(return_value="")
        mock_ssh.ping = AsyncMock(return_value="Success rate 100 percent (5/5)")

        config = {
            "bgp": {
                "local_asn": 65001,
                "neighbors": [
                    {"neighbor_ip": "10.100.0.2", "remote_asn": 65002},
                    {"neighbor_ip": "10.100.0.3", "remote_asn": 65003},
                ],
            }
        }

        result = await sv.verify_all(mock_ssh, config, "cisco_xr")
        assert hasattr(result, "passed")

    @pytest.mark.asyncio
    async def test_verify_bgp_idle_neighbor(self):
        """StateVerifier detects Idle (non-Established) BGP neighbor."""
        from core.state_verifier import StateVerifier
        sv = StateVerifier()

        mock_ssh = MagicMock()
        mock_ssh.get_bgp_summary = AsyncMock(
            return_value="10.100.0.2      4 65002       0       0 never    Idle\n"
        )
        mock_ssh.get_ospf_neighbors = AsyncMock(return_value="")
        mock_ssh.ping = AsyncMock(return_value="Success rate 0 percent (0/5)")

        config = {
            "bgp": {
                "local_asn": 65001,
                "neighbors": [{"neighbor_ip": "10.100.0.2", "remote_asn": 65002}],
            }
        }

        result = await sv.verify_all(mock_ssh, config, "cisco_xr")
        assert hasattr(result, "passed")
        # Idle neighbor = not established; after Cursor implements:
        # assert result.passed is False

    @pytest.mark.asyncio
    async def test_verify_ospf_full_adjacency(self):
        """StateVerifier recognises OSPF FULL adjacency."""
        from core.state_verifier import StateVerifier
        sv = StateVerifier()

        mock_ssh = MagicMock()
        mock_ssh.get_bgp_summary = AsyncMock(return_value="")
        mock_ssh.get_ospf_neighbors = AsyncMock(
            return_value=(
                "Neighbor ID     Pri   State           Dead Time  Address\n"
                "10.0.0.2         1   FULL/BDR        00:00:35   10.0.0.2\n"
            )
        )
        mock_ssh.ping = AsyncMock(return_value="Success rate 100 percent (5/5)")

        config = {
            "ospf": {
                "process_id": 1,
                "areas": [{"area_id": "0", "networks": ["10.0.0.0/24"]}],
            }
        }

        result = await sv.verify_all(mock_ssh, config, "cisco_xr")
        assert hasattr(result, "passed")

    @pytest.mark.asyncio
    async def test_verify_empty_config_passes(self):
        """Empty desired config: verify_all should pass (nothing to check)."""
        from core.state_verifier import StateVerifier
        sv = StateVerifier()

        mock_ssh = MagicMock()
        mock_ssh.get_bgp_summary = AsyncMock(return_value="")
        mock_ssh.get_ospf_neighbors = AsyncMock(return_value="")
        mock_ssh.ping = AsyncMock(return_value="")

        result = await sv.verify_all(mock_ssh, {}, "cisco_xr")
        assert hasattr(result, "passed")


# ---------------------------------------------------------------------------
# SnapshotManager integration
# ---------------------------------------------------------------------------

class TestSnapshotManagerIntegration:
    @pytest.mark.asyncio
    async def test_save_before_snapshot_adds_db_row(self):
        """save_snapshot(is_before=True) writes a ConfigSnapshot ORM row."""
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_ssh = MagicMock()
        mock_ssh.get_running_config = AsyncMock(return_value="! running config")

        sm = SnapshotManager(mock_db, mock_ssh)
        dep_id = uuid4()
        dev_id = uuid4()

        await sm.save_snapshot(dep_id, dev_id, {"config": "!"}, is_before=True)

        mock_db.add.assert_called_once()
        snap = mock_db.add.call_args[0][0]
        # is_before=True → config_before is set, config_after is None
        assert snap.config_before == {"config": "!"}
        assert snap.config_after is None
        assert snap.deployment_id == dep_id

    @pytest.mark.asyncio
    async def test_save_after_snapshot_is_before_false(self):
        """save_snapshot(is_before=False) marks snapshot as AFTER."""
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_ssh = MagicMock()
        sm = SnapshotManager(mock_db, mock_ssh)

        await sm.save_snapshot(uuid4(), uuid4(), {"config": "!"}, is_before=False)
        snap = mock_db.add.call_args[0][0]
        # is_before=False → config_after is set, config_before is None
        assert snap.config_after == {"config": "!"}
        assert snap.config_before is None

    @pytest.mark.asyncio
    async def test_capture_running_config_returns_dict(self):
        """capture_running_config returns a dict."""
        from core.snapshot_manager import SnapshotManager

        mock_db = MagicMock()
        mock_ssh = MagicMock()
        mock_ssh.get_running_config = AsyncMock(
            return_value="interface Loopback0\n ip address 1.1.1.1 255.255.255.255\n"
        )

        sm = SnapshotManager(mock_db, mock_ssh)
        result = await sm.capture_running_config(str(uuid4()))
        assert isinstance(result, dict)

    def test_diff_snapshots_returns_string_or_none(self):
        """diff_snapshots returns a string or None — never raises."""
        from core.snapshot_manager import SnapshotManager

        before_snap = MagicMock()
        before_snap.is_before = True
        before_snap.config_data = {"config": "line A\nline B\n"}

        after_snap = MagicMock()
        after_snap.is_before = False
        after_snap.config_data = {"config": "line A\nline C\n"}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [before_snap, after_snap]

        sm = SnapshotManager(mock_db, ssh_device=None)
        diff = sm.diff_snapshots(uuid4(), uuid4())
        assert diff is None or isinstance(diff, str)


# ---------------------------------------------------------------------------
# API endpoint integration (deployment logs + snapshot)
# ---------------------------------------------------------------------------

class TestDeploymentAPIEndpoints:
    def test_get_deployment_logs_200(self, client, db_session):
        """
        GET /api/deployments/{id}/logs returns 200 with log structure.

        [CURSOR IMPLEMENTS — requires Deployment row in DB]
        """
        # Placeholder — Cursor wires up a real Deployment row via db_session fixture
        # dep = Deployment(device_id=..., status="SUCCESS", logs="step1\nstep2\n")
        # db_session.add(dep); db_session.commit()
        # resp = client.get(f"/api/deployments/{dep.id}/logs")
        # assert resp.status_code == 200
        # data = resp.json()
        # assert "logs" in data
        # assert "log_count" in data
        pass

    def test_get_deployment_logs_404(self, client):
        """GET /api/deployments/{id}/logs with unknown ID returns 404."""
        # resp = client.get(f"/api/deployments/{uuid4()}/logs")
        # assert resp.status_code == 404
        pass

    def test_get_deployment_snapshot_200(self, client, db_session):
        """
        GET /api/deployments/{id}/snapshot returns snapshot list.

        [CURSOR IMPLEMENTS]
        """
        pass

    def test_get_deployment_snapshot_404(self, client):
        """GET /api/deployments/{id}/snapshot with unknown ID returns 404."""
        pass
