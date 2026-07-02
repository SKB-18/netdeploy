"""
DeploymentOrchestrator — safe multi-device deployment with rollback.

Phase 1 Cowork: class structure, strategy skeletons, state machine.
Phase 3 Cowork: wires in CommandBuilder, StateVerifier, SnapshotManager;
                adds DeploymentRecord DB update helpers; fleshes out
                _deploy_to_device step sequence for Cursor.

Cursor implements:
  - Full body of _deploy_to_device (SSH connect → backup → apply → verify → audit)
  - Full body of _rollback_device (fetch snapshot → SSH → apply → verify)
  - Full body of _health_check (BGP/OSPF state verification)
  - Vendor command generation (delegates to CommandBuilder)
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4, UUID

logger = logging.getLogger(__name__)


class DeploymentOrchestrator:
    """Orchestrate safe deployment of network configurations."""

    def __init__(self, db_session=None):
        self.db = db_session
        # Phase 3: lazy-import to avoid circular deps at module load
        self._command_builder = None
        self._state_verifier = None

    @property
    def command_builder(self):
        if self._command_builder is None:
            from core.command_builder import CommandBuilder
            self._command_builder = CommandBuilder()
        return self._command_builder

    @property
    def state_verifier(self):
        if self._state_verifier is None:
            from core.state_verifier import StateVerifier
            self._state_verifier = StateVerifier()
        return self._state_verifier

    def _get_device(self, device_id: str):
        """Fetch Device ORM object from DB. Returns None if not found."""
        if self.db is None:
            return None
        from api.models import Device
        return self.db.query(Device).filter(Device.id == device_id).first()

    def _get_desired_config(self, device_id: str, config_version: str) -> Optional[dict]:
        """
        Fetch desired_state for a device at a specific version.

        If config_version == "latest": return most recent Configuration row.
        Otherwise: fetch from GitConfigRepository at that commit hash.

        [CURSOR IMPLEMENTS Git lookup branch]
        """
        if self.db is None:
            return None
        from api.models import Configuration
        if config_version == "latest":
            config = (
                self.db.query(Configuration)
                .filter(Configuration.device_id == device_id)
                .order_by(Configuration.created_at.desc())
                .first()
            )
            return config.desired_state if config else None
        # Cursor: from core.git_handler import GitConfigRepository
        # repo = GitConfigRepository(settings.GIT_REPO_PATH)
        # return repo.get_version(device_id, config_version)
        return None

    def _update_deployment_status(
        self,
        deployment_id: UUID,
        status: str,
        error_message: str = None,
        logs: str = None,
    ):
        """
        Update Deployment.status + timestamps in DB.

        Called at each state transition:
          QUEUED → IN_PROGRESS → SUCCESS | ROLLBACK | FAILED

        [CURSOR IMPLEMENTS]
        """
        if self.db is None:
            return
        from api.models import Deployment
        deployment = self.db.query(Deployment).filter(Deployment.id == deployment_id).first()
        if not deployment:
            logger.warning("_update_deployment_status: deployment %s not found", deployment_id)
            return

        deployment.status = status
        if status == "IN_PROGRESS" and not deployment.start_time:
            deployment.start_time = datetime.utcnow()
        if status in ("SUCCESS", "ROLLBACK", "FAILED"):
            deployment.end_time = datetime.utcnow()
        if error_message:
            deployment.error_message = error_message
        if logs:
            deployment.logs = (deployment.logs or "") + logs + "\n"

        self.db.commit()

    def _write_audit(
        self,
        user_id: str,
        action: str,
        device_id: str,
        details: dict,
    ):
        """
        Append an AuditLog entry for a deployment action.

        [CURSOR IMPLEMENTS]
        """
        if self.db is None:
            return
        from api.models import AuditLog
        entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type="Deployment",
            resource_id=device_id,
            details=details,
        )
        self.db.add(entry)
        self.db.commit()

    async def deploy(
        self,
        device_ids: List[str],
        config_version: str,
        strategy: str = "atomic",
        batch_id: Optional[str] = None,
        user_id: str = "system",
    ) -> dict:
        """
        Main deployment entry point.

        Strategies:
        - canary:  Deploy to first device → wait 5 min health check → rest
        - rolling: Sequential device-by-device with health checks between
        - atomic:  All in parallel; rollback all if any fail

        Returns dict with status, batch_id, affected_devices, errors.
        """
        batch_id = batch_id or str(uuid4())
        logger.info(
            "Starting %s deployment batch=%s devices=%s", strategy, batch_id, device_ids
        )

        if strategy == "canary":
            return await self._deploy_canary(device_ids, config_version, batch_id, user_id)
        elif strategy == "rolling":
            return await self._deploy_rolling(device_ids, config_version, batch_id, user_id)
        elif strategy == "atomic":
            return await self._deploy_atomic(device_ids, config_version, batch_id, user_id)
        else:
            return {"status": "FAILED", "error": f"Unknown strategy: {strategy}"}

    # ------------------------------------------------------------------
    # Strategy implementations (Cursor fills in the logic)
    # ------------------------------------------------------------------

    async def _deploy_canary(
        self, device_ids: List[str], config_version: str, batch_id: str, user_id: str
    ) -> dict:
        """
        Canary strategy:
        1. Deploy to device_ids[0] (canary device)
        2. Wait CANARY_HEALTH_WAIT_SECONDS
        3. Health check canary
        4. If healthy: deploy rest in parallel
        5. If unhealthy: rollback canary, abort

        [CURSOR IMPLEMENTS]
        """
        if not device_ids:
            return {"status": "FAILED", "error": "No devices provided"}

        canary_id = device_ids[0]
        rest_ids = device_ids[1:]

        canary_result = await self._deploy_to_device(canary_id, config_version, user_id)
        if not canary_result.get("success"):
            return {
                "status": "FAILED",
                "batch_id": batch_id,
                "error": f"Canary device {canary_id} failed: {canary_result.get('error')}",
            }

        # [CURSOR]: wait + health check before proceeding to rest
        healthy = await self._health_check(canary_id)
        if not healthy:
            await self._rollback_device(canary_id, user_id)
            return {
                "status": "ROLLBACK",
                "batch_id": batch_id,
                "error": f"Canary health check failed for {canary_id}",
            }

        # Deploy rest in parallel
        tasks = [self._deploy_to_device(d, config_version, user_id) for d in rest_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        failed = [r for r in results if isinstance(r, Exception) or not r.get("success")]

        return {
            "status": "SUCCESS" if not failed else "PARTIAL",
            "batch_id": batch_id,
            "affected_devices": device_ids,
            "failed_count": len(failed),
        }

    async def _deploy_rolling(
        self, device_ids: List[str], config_version: str, batch_id: str, user_id: str
    ) -> dict:
        """
        Rolling strategy:
        Deploy to each device sequentially; health-check before next.
        Abort (no rollback of completed) if any device fails.

        [CURSOR IMPLEMENTS]
        """
        completed = []
        for device_id in device_ids:
            result = await self._deploy_to_device(device_id, config_version, user_id)
            if not result.get("success"):
                return {
                    "status": "FAILED",
                    "batch_id": batch_id,
                    "completed": completed,
                    "failed_at": device_id,
                    "error": result.get("error"),
                }
            completed.append(device_id)

            healthy = await self._health_check(device_id)
            if not healthy:
                logger.warning("Health check failed for %s, aborting rolling deploy", device_id)
                return {
                    "status": "FAILED",
                    "batch_id": batch_id,
                    "completed": completed,
                    "error": f"Health check failed at device {device_id}",
                }

        return {"status": "SUCCESS", "batch_id": batch_id, "affected_devices": device_ids}

    async def _deploy_atomic(
        self, device_ids: List[str], config_version: str, batch_id: str, user_id: str
    ) -> dict:
        """
        Atomic strategy:
        Deploy to all devices in parallel.
        If any fail → rollback ALL (including successful ones).

        [CURSOR IMPLEMENTS]
        """
        tasks = [self._deploy_to_device(d, config_version, user_id) for d in device_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        failed = []
        for device_id, result in zip(device_ids, results):
            if isinstance(result, Exception) or not result.get("success"):
                failed.append(device_id)

        if failed:
            logger.warning("Atomic deploy failed on %s — rolling back all", failed)
            await self._rollback_all(device_ids, user_id)
            return {
                "status": "ROLLBACK",
                "batch_id": batch_id,
                "failed_devices": failed,
                "error": "Atomic deployment failed; all devices rolled back",
            }

        return {"status": "SUCCESS", "batch_id": batch_id, "affected_devices": device_ids}

    # ------------------------------------------------------------------
    # Per-device operations (Cursor implements SSH + DB updates)
    # ------------------------------------------------------------------

    async def _deploy_to_device(
        self, device_id: str, config_version: str, user_id: str = "system"
    ) -> dict:
        """
        Deploy config to a single device.

        Full step sequence — Cursor implements each step body:

        Step 1 — Fetch device + desired config from DB
            device = self._get_device(device_id)
            desired_config = self._get_desired_config(device_id, config_version)

        Step 2 — SSH connect
            from core.ssh_handler import SSHDevice
            ssh = SSHDevice(hostname, ip, device_type, ...)
            await ssh.connect()

        Step 3 — Backup running config (BEFORE snapshot)
            from core.snapshot_manager import SnapshotManager
            snap = SnapshotManager(self.db, ssh)
            running = await snap.capture_running_config(device_id)
            await snap.save_snapshot(deployment_id, device_id, running, is_before=True)

        Step 4 — Generate vendor commands
            cmds = self.command_builder.build(desired_config, device.device_type)

        Step 5 — Apply commands
            ok = await ssh.send_config_set(cmds)
            if not ok: raise RuntimeError("send_config_set failed")

        Step 6 — Verify state
            vr = await self.state_verifier.verify_all(ssh, desired_config, device.device_type)
            if not vr.passed: raise RuntimeError(f"State verification failed: {vr.checks}")

        Step 7 — Save AFTER snapshot + update DB
            after = await snap.capture_running_config(device_id)
            await snap.save_snapshot(deployment_id, device_id, after, is_before=False)
            self._update_deployment_status(deployment_id, "SUCCESS")
            self._write_audit(user_id, "DEPLOY", device_id, {"version": config_version})

        Step 8 — Disconnect
            await ssh.disconnect()

        On exception in steps 2–7:
            await self._rollback_device(device_id, user_id)
            self._update_deployment_status(deployment_id, "ROLLBACK", error_message=str(e))
            return {"success": False, "error": str(e), ...}

        Returns: {"success": bool, "device_id": str, "error": str|None, "time_taken": float}

        [CURSOR IMPLEMENTS the above — steps are pseudocode scaffolding]
        """
        start = datetime.utcnow()
        logger.info("Deploying config to device %s (version=%s)", device_id, config_version)

        # Step 1 — Fetch device + desired config
        device = self._get_device(device_id)
        if not device:
            return {
                "success": False,
                "device_id": device_id,
                "error": f"Device {device_id} not found",
                "time_taken": (datetime.utcnow() - start).total_seconds(),
            }

        desired_config = self._get_desired_config(device_id, config_version)
        if not desired_config:
            return {
                "success": False,
                "device_id": device_id,
                "error": f"No config found for device {device_id} at version {config_version}",
                "time_taken": (datetime.utcnow() - start).total_seconds(),
            }

        # Create a deployment record and get its ID
        deployment_id = uuid4()
        self._update_deployment_status(deployment_id, "IN_PROGRESS")

        from core.ssh_handler import SSHDevice
        from core.snapshot_manager import SnapshotManager

        ssh = SSHDevice(
            hostname=device.hostname,
            ip=getattr(device, "management_ip", device.hostname),
            device_type=device.device_type,
            port=getattr(device, "ssh_port", 22),
        )

        try:
            # Step 2 — SSH connect
            connected = await ssh.connect()
            if not connected:
                raise RuntimeError(f"SSH connection failed for {device.hostname}")

            snap = SnapshotManager(self.db, ssh)

            # Step 3 — Backup running config
            running = await snap.capture_running_config(device_id)
            await snap.save_snapshot(deployment_id, device_id, running or {}, is_before=True)

            # Step 4 — Generate vendor commands
            cmds = self.command_builder.build(desired_config, device.device_type)

            # Step 5 — Apply commands
            ok = await ssh.send_config_set(cmds)
            if not ok:
                raise RuntimeError("send_config_set failed — check device logs")

            # Step 6 — Verify state
            vr = await self.state_verifier.verify_all(ssh, desired_config, device.device_type)
            if not vr.passed:
                failed_checks = [c for c in vr.checks if not c["passed"]]
                raise RuntimeError(f"State verification failed: {failed_checks}")

            # Step 7 — Save AFTER snapshot + update DB
            after = await snap.capture_running_config(device_id)
            await snap.save_snapshot(deployment_id, device_id, after or {}, is_before=False)
            self._update_deployment_status(deployment_id, "SUCCESS")
            self._write_audit(user_id, "DEPLOY", device_id, {"version": config_version})

            return {
                "success": True,
                "device_id": device_id,
                "deployment_id": str(deployment_id),
                "error": None,
                "time_taken": (datetime.utcnow() - start).total_seconds(),
            }

        except Exception as e:
            logger.exception("Deploy failed for device %s: %s", device_id, e)
            await self._rollback_device(device_id, user_id)
            self._update_deployment_status(deployment_id, "ROLLBACK", error_message=str(e))
            return {
                "success": False,
                "device_id": device_id,
                "deployment_id": str(deployment_id),
                "error": str(e),
                "time_taken": (datetime.utcnow() - start).total_seconds(),
            }
        finally:
            # Step 8 — Disconnect
            await ssh.disconnect()

    async def _health_check(self, device_id: str) -> bool:
        """
        Check device health post-deployment using StateVerifier.

        Steps (Cursor implements):
        1. Fetch device + latest desired_config from DB
        2. SSH connect
        3. Call state_verifier.verify_all(ssh, desired_config, device_type)
        4. Disconnect
        5. Return verify_result.passed

        Returns True if all checks pass.

        [CURSOR IMPLEMENTS]
        """
        logger.info("Health check for device %s", device_id)

        device = self._get_device(device_id)
        if not device:
            logger.error("Health check: device %s not found", device_id)
            return False

        desired_config = self._get_desired_config(device_id, "latest")
        if not desired_config:
            logger.warning("Health check: no desired config for device %s", device_id)
            return True  # Nothing to verify

        # Cursor: SSH connect, call state_verifier.verify_all(), return result.passed
        logger.warning("_health_check: SSH verify not yet implemented — CURSOR IMPLEMENTS")
        return True  # Placeholder

    async def _rollback_device(self, device_id: str, user_id: str = "system") -> bool:
        """
        Rollback device to previous config snapshot.

        Steps (Cursor implements):
        1. Fetch most recent Deployment for device_id with status IN_PROGRESS or ROLLBACK
        2. Instantiate SnapshotManager(self.db, ssh)
        3. Call snapshot_manager.restore_snapshot(deployment_id, device_id)
        4. Call state_verifier.verify_all() to confirm rollback succeeded
        5. Update Deployment.status = "ROLLBACK"
        6. Write AuditLog(action="ROLLBACK")

        Returns True if rollback succeeded.

        [CURSOR IMPLEMENTS]
        """
        logger.info("Rolling back device %s", device_id)

        device = self._get_device(device_id)
        if not device:
            logger.error("Rollback: device %s not found", device_id)
            return False

        # Cursor: SSH + SnapshotManager.restore_snapshot()
        logger.warning("_rollback_device: SSH restore not yet implemented — CURSOR IMPLEMENTS")
        self._write_audit(user_id, "ROLLBACK", device_id, {"reason": "auto-rollback on deploy failure"})
        return True  # Placeholder

    async def _rollback_all(self, device_ids: List[str], user_id: str = "system") -> bool:
        """Parallel rollback of all devices."""
        tasks = [self._rollback_device(d, user_id) for d in device_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(r is True for r in results)

    def _config_to_commands(self, config: dict, device_type: str) -> List[str]:
        """
        Convert desired config dict to vendor-specific CLI commands.

        Supported device types (Cursor implements each vendor):
        - cisco_xr: IOS-XR syntax
        - junos:    Juniper JunOS set-format
        - arista_eos: Arista EOS syntax
        - cisco_ios: classic IOS

        Returns list of CLI commands.
        
        [CURSOR IMPLEMENTS]
        """
        commands = []

        if device_type == "cisco_xr":
            commands = self._cisco_xr_commands(config)
        elif device_type == "cisco_ios":
            commands = self._cisco_ios_commands(config)
        elif device_type == "junos":
            commands = self._junos_commands(config)
        elif device_type == "arista_eos":
            commands = self._arista_eos_commands(config)
        else:
            raise ValueError(f"Unsupported device type: {device_type}")

        return commands

    def _cisco_xr_commands(self, config: dict) -> List[str]:
        """[CURSOR IMPLEMENTS] IOS-XR config commands."""
        return ["! Cursor implements Cisco XR commands"]

    def _cisco_ios_commands(self, config: dict) -> List[str]:
        """[CURSOR IMPLEMENTS] Classic IOS config commands."""
        return ["! Cursor implements Cisco IOS commands"]

    def _junos_commands(self, config: dict) -> List[str]:
        """[CURSOR IMPLEMENTS] JunOS set-format commands."""
        return ["# Cursor implements JunOS commands"]

    def _arista_eos_commands(self, config: dict) -> List[str]:
        """[CURSOR IMPLEMENTS] Arista EOS config commands."""
        return ["! Cursor implements Arista EOS commands"]
