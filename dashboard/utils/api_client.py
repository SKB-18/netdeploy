"""
NetDeployClient — HTTP client wrapper for the NetDeploy API.

Phase 4 Cowork: adds Phase 3 endpoints (logs, snapshot, rollback)
                and Phase 4 convenience methods (health, sync, delete,
                config history, config diff).

Cursor implements all method bodies. Method signatures + docstrings
are complete — Cursor fills in the requests call + error handling.
"""

import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class NetDeployClient:
    """Wrapper for NetDeploy REST API calls from the dashboard."""

    def __init__(self, api_url: str, timeout: int = 10):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Returns True if the API is reachable and healthy."""
        try:
            r = self.session.get(f"{self.api_url}/health", timeout=self.timeout)
            return r.status_code == 200 and r.json().get("status") != "error"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Devices
    # ------------------------------------------------------------------

    def list_devices(self) -> List[dict]:
        """GET /api/devices/ → list of device dicts."""
        try:
            r = self.session.get(f"{self.api_url}/api/devices/", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("list_devices failed: %s", e)
            return []

    def get_device(self, device_id: str) -> Optional[dict]:
        """GET /api/devices/{device_id}"""
        try:
            r = self.session.get(f"{self.api_url}/api/devices/{device_id}", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_device %s failed: %s", device_id, e)
            return None

    def create_device(self, device_data: dict) -> Optional[dict]:
        """POST /api/devices/ → created device dict or None on error."""
        try:
            r = self.session.post(
                f"{self.api_url}/api/devices/", json=device_data, timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("create_device failed: %s", e)
            return None

    def update_device(self, device_id: str, updates: dict) -> Optional[dict]:
        """
        PUT /api/devices/{device_id} → updated device dict.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.put(
                f"{self.api_url}/api/devices/{device_id}",
                json=updates,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("update_device %s failed: %s", device_id, e)
            return None

    def delete_device(self, device_id: str) -> bool:
        """
        DELETE /api/devices/{device_id} → True on success.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.delete(
                f"{self.api_url}/api/devices/{device_id}", timeout=self.timeout
            )
            r.raise_for_status()
            return True
        except Exception as e:
            logger.error("delete_device %s failed: %s", device_id, e)
            return False

    def check_device_health(self, device_id: str) -> Optional[dict]:
        """
        GET /api/devices/{device_id}/health → {"healthy": bool, "message": str}.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.get(
                f"{self.api_url}/api/devices/{device_id}/health", timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("check_device_health %s failed: %s", device_id, e)
            return None

    def sync_device(self, device_id: str) -> Optional[dict]:
        """
        POST /api/devices/{device_id}/sync → sync result dict or None.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.post(
                f"{self.api_url}/api/devices/{device_id}/sync", timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("sync_device %s failed: %s", device_id, e)
            return None

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def list_deployments(self, limit: int = 20, status: str = None) -> List[dict]:
        """GET /api/deployments/?limit=N[&status=S]"""
        params: dict = {"limit": limit}
        if status:
            params["status"] = status
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/",
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("list_deployments failed: %s", e)
            return []

    def get_deployment(self, deployment_id: str) -> Optional[dict]:
        """GET /api/deployments/{deployment_id}"""
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/{deployment_id}", timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_deployment %s failed: %s", deployment_id, e)
            return None

    def get_deployment_logs(self, deployment_id: str) -> Optional[dict]:
        """
        GET /api/deployments/{deployment_id}/logs
        → {"logs": [...], "log_count": int, "status": str, ...}

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/{deployment_id}/logs",
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_deployment_logs %s failed: %s", deployment_id, e)
            return None

    def get_deployment_snapshot(
        self, deployment_id: str, device_id: str = None
    ) -> Optional[dict]:
        """
        GET /api/deployments/{deployment_id}/snapshot[?device_id=...]
        → {"snapshots": [...], "diff": str|None}

        [CURSOR IMPLEMENTS]
        """
        params = {}
        if device_id:
            params["device_id"] = device_id
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/{deployment_id}/snapshot",
                params=params,
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_deployment_snapshot %s failed: %s", deployment_id, e)
            return None

    def trigger_deployment(
        self,
        device_ids: List[str],
        config_version: str,
        strategy: str = "atomic",
    ) -> Optional[str]:
        """POST /api/configs/deploy → returns batch_id or None on error."""
        result = self.trigger_deployment_detailed(device_ids, config_version, strategy)
        return result.get("batch_id") if result.get("success") else None

    def trigger_deployment_detailed(
        self,
        device_ids: List[str],
        config_version: str,
        strategy: str = "atomic",
    ) -> dict:
        """POST /api/configs/deploy → {success, batch_id?, detail?}."""
        try:
            r = self.session.post(
                f"{self.api_url}/api/configs/deploy",
                json={
                    "device_ids": device_ids,
                    "config_version": config_version,
                    "strategy": strategy,
                },
                timeout=self.timeout,
            )
            if r.status_code >= 400:
                try:
                    detail = r.json().get("detail", r.text)
                except Exception:
                    detail = r.text
                logger.error("trigger_deployment failed (%s): %s", r.status_code, detail)
                return {"success": False, "status_code": r.status_code, "detail": detail}
            data = r.json()
            return {"success": True, "batch_id": data.get("batch_id"), "data": data}
        except Exception as e:
            logger.error("trigger_deployment failed: %s", e)
            return {"success": False, "detail": str(e)}

    def rollback_deployment(self, deployment_id: str, reason: str = "manual") -> Optional[str]:
        """
        POST /api/deployments/{deployment_id}/rollback
        → task_id string or None on error.
        """
        try:
            r = self.session.post(
                f"{self.api_url}/api/deployments/{deployment_id}/rollback",
                json={"deployment_id": deployment_id, "reason": reason},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json().get("task_id")
        except Exception as e:
            logger.error("rollback_deployment %s failed: %s", deployment_id, e)
            return None

    def get_batch(self, batch_id: str) -> Optional[dict]:
        """
        GET /api/deployments/batch/{batch_id}
        → {"batch_id": str, "total": int, "deployments": [...]}

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/batch/{batch_id}", timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_batch %s failed: %s", batch_id, e)
            return None

    # ------------------------------------------------------------------
    # Configurations
    # ------------------------------------------------------------------

    def create_config(
        self,
        device_id: str,
        desired_state: dict,
        description: str = "Configuration update",
    ) -> Optional[dict]:
        """POST /api/configs/ → store desired configuration for a device."""
        try:
            r = self.session.post(
                f"{self.api_url}/api/configs/",
                json={
                    "device_id": device_id,
                    "desired_state": desired_state,
                    "description": description,
                },
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("create_config failed: %s", e)
            return None

    def validate_config(self, device_id: str, desired_state: dict) -> Optional[dict]:
        """
        POST /api/configs/validate → ValidationResponse dict.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.post(
                f"{self.api_url}/api/configs/validate",
                json={"device_id": device_id, "desired_state": desired_state},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("validate_config failed: %s", e)
            return None

    def get_config_history(self, device_id: str, limit: int = 20) -> List[dict]:
        """
        GET /api/configs/history?device_id={device_id}&limit={limit}
        → list of config version dicts.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.get(
                f"{self.api_url}/api/configs/history",
                params={"device_id": device_id, "limit": limit},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_config_history %s failed: %s", device_id, e)
            return []

    def get_config_diff(self, device_id: str) -> Optional[dict]:
        """
        GET /api/configs/diff?device_id={device_id}
        → ConfigDiffResponse with desired vs running config and unified diff.

        [CURSOR IMPLEMENTS]
        """
        try:
            r = self.session.get(
                f"{self.api_url}/api/configs/diff",
                params={"device_id": device_id},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_config_diff %s failed: %s", device_id, e)
            return None

    # ------------------------------------------------------------------
    # Audit Log
    # ------------------------------------------------------------------

    def get_audit_log(
        self,
        user: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        """GET /api/audit-log with optional filters."""
        params: dict = {"limit": limit}
        if user:
            params["user_id"] = user
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        try:
            r = self.session.get(
                f"{self.api_url}/api/audit-log/", params=params, timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_audit_log failed: %s", e)
            return []
