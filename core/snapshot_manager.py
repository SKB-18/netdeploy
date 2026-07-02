"""
SnapshotManager — saves and restores device config snapshots around deployments.

Phase 3 Cowork: class structure, save/restore stubs with DB interaction outline.

Cursor implements:
  - save_snapshot (SSH → get_running_config → write ConfigSnapshot row)
  - restore_snapshot (fetch ConfigSnapshot → SSH → apply config_before)
  - diff_snapshots (unified diff between before and after)
"""

import hashlib
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Creates and restores ConfigSnapshot records for deployment safety.

    Used by DeploymentOrchestrator._deploy_to_device():
    1. save_snapshot(before=True)   ← backup before applying changes
    2. [apply config]
    3. save_snapshot(before=False)  ← capture final state
    4. On failure: restore_snapshot()  ← roll back to backup
    """

    def __init__(self, db_session=None, ssh_device=None, db=None):
        self.db = db_session if db_session is not None else db
        self.ssh = ssh_device

    def _compute_hash(self, content: str) -> str:
        """Return SHA-256 hex digest of the given config string."""
        return hashlib.sha256(content.encode()).hexdigest()

    async def save_snapshot(
        self,
        deployment_id: UUID,
        device_id: UUID,
        config_data: dict,
        is_before: bool = True,
    ) -> Optional[UUID]:
        """
        Persist a ConfigSnapshot row for a deployment.

        Steps (Cursor implements):
        1. Compute SHA-256 hash of config_data JSON for integrity
        2. Create ConfigSnapshot(
               deployment_id=deployment_id,
               device_id=device_id,
               config_before=config_data if is_before else None,
               config_after=None if is_before else config_data,
               snapshot_hash=sha256_hash,
           )
        3. db.add() + db.commit()
        4. Return snapshot.id

        Args:
            deployment_id: Parent Deployment UUID
            device_id:     Device UUID
            config_data:   Config dict to snapshot (desired_state or running)
            is_before:     True = save as config_before, False = config_after

        Returns: ConfigSnapshot UUID, or None on error.

        [CURSOR IMPLEMENTS]
        """
        import json
        snapshot_hash = hashlib.sha256(
            json.dumps(config_data, sort_keys=True).encode()
        ).hexdigest()

        logger.info(
            "Saving %s snapshot for deployment=%s device=%s hash=%s",
            "BEFORE" if is_before else "AFTER",
            deployment_id, device_id, snapshot_hash[:8],
        )

        try:
            from api.models import ConfigSnapshot
            snapshot = ConfigSnapshot(
                deployment_id=deployment_id,
                device_id=device_id,
                config_before=config_data if is_before else None,
                config_after=None if is_before else config_data,
                applied_at=datetime.utcnow(),
                snapshot_hash=snapshot_hash,
            )
            self.db.add(snapshot)
            self.db.commit()
            self.db.refresh(snapshot)
            logger.info("Snapshot saved: id=%s", snapshot.id)
            return snapshot.id
        except Exception as e:
            logger.exception("Failed to save snapshot: %s", e)
            return None

    async def restore_snapshot(
        self,
        deployment_id: UUID,
        device_id: UUID,
    ) -> bool:
        """
        Restore a device to its pre-deployment config.

        Steps (Cursor implements):
        1. Fetch ConfigSnapshot WHERE deployment_id=deployment_id
           AND device_id=device_id ORDER BY applied_at ASC LIMIT 1
           (the BEFORE snapshot)
        2. Extract config_before
        3. If config_before is None: log error, return False
        4. Use SSHDevice.send_config_set() to apply config_before
        5. Verify state with StateVerifier
        6. Update ConfigSnapshot.config_after with final state
        7. Return True if successful

        [CURSOR IMPLEMENTS]
        """
        logger.info(
            "Restoring snapshot for deployment=%s device=%s", deployment_id, device_id
        )

        try:
            from api.models import ConfigSnapshot
            snapshot = (
                self.db.query(ConfigSnapshot)
                .filter(
                    ConfigSnapshot.deployment_id == deployment_id,
                    ConfigSnapshot.device_id == device_id,
                )
                .order_by(ConfigSnapshot.applied_at.asc())
                .first()
            )

            if not snapshot or not snapshot.config_before:
                logger.error(
                    "No BEFORE snapshot found for deployment=%s device=%s",
                    deployment_id, device_id,
                )
                return False

            if self.ssh is None:
                logger.warning("No SSH device — cannot apply rollback config")
                return False

            config_before = snapshot.config_before
            if isinstance(config_before, dict) and "raw" in config_before:
                # Stored as raw text — send line by line as config set
                raw_lines = [
                    line for line in config_before["raw"].splitlines()
                    if line.strip() and not line.strip().startswith("!")
                ]
                ok = await self.ssh.send_config_set(raw_lines)
            else:
                from core.command_builder import CommandBuilder
                builder = CommandBuilder()
                # Determine device_type from SSH device attribute
                device_type = getattr(self.ssh, "device_type", "cisco_xr")
                try:
                    cmds = builder.build(config_before, device_type)
                    ok = await self.ssh.send_config_set(cmds)
                except Exception as build_err:
                    logger.error("CommandBuilder failed during restore: %s", build_err)
                    ok = False

            if ok:
                logger.info("Restore snapshot succeeded for deployment=%s device=%s", deployment_id, device_id)
            else:
                logger.error("Restore snapshot failed for deployment=%s device=%s", deployment_id, device_id)
            return ok

        except Exception as e:
            logger.exception("restore_snapshot failed: %s", e)
            return False

    def diff_snapshots(self, deployment_id: UUID, device_id: UUID) -> Optional[str]:
        """
        Generate a unified diff between config_before and config_after.

        Returns diff string, or None if snapshots not found.

        [CURSOR IMPLEMENTS using difflib.unified_diff]
        """
        import json
        import difflib

        try:
            from api.models import ConfigSnapshot
            snapshot = (
                self.db.query(ConfigSnapshot)
                .filter(
                    ConfigSnapshot.deployment_id == deployment_id,
                    ConfigSnapshot.device_id == device_id,
                )
                .order_by(ConfigSnapshot.applied_at.asc())
                .first()
            )

            if not snapshot:
                return None

            before_lines = json.dumps(
                snapshot.config_before or {}, indent=2
            ).splitlines(keepends=True)
            after_lines = json.dumps(
                snapshot.config_after or {}, indent=2
            ).splitlines(keepends=True)

            diff = list(difflib.unified_diff(
                before_lines, after_lines,
                fromfile="config_before",
                tofile="config_after",
            ))

            return "".join(diff) if diff else "(no changes)"

        except Exception as e:
            logger.exception("diff_snapshots failed: %s", e)
            return None

    async def capture_running_config(self, device_id: UUID) -> Optional[dict]:
        """
        SSH to device, get running config, return as dict.

        Used to save the BEFORE snapshot from live device state.

        [CURSOR IMPLEMENTS parsing running config text → dict]
        """
        if self.ssh is None:
            return None
        try:
            raw = await self.ssh.get_running_config()
            # Cursor: parse raw text → structured dict
            # For now return as raw string in a wrapper
            return {"raw": raw, "format": "text"}
        except Exception as e:
            logger.exception("capture_running_config failed: %s", e)
            return None
