"""NetDeployClient — HTTP client wrapper for the NetDeploy API."""

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
    # Devices  [CURSOR IMPLEMENTS method bodies]
    # ------------------------------------------------------------------

    def list_devices(self) -> List[dict]:
        """GET /api/devices → list of device dicts."""
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
        """POST /api/devices/"""
        try:
            r = self.session.post(
                f"{self.api_url}/api/devices/", json=device_data, timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("create_device failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Deployments  [CURSOR IMPLEMENTS method bodies]
    # ------------------------------------------------------------------

    def list_deployments(self, limit: int = 20) -> List[dict]:
        """GET /api/deployments/?limit=N"""
        try:
            r = self.session.get(
                f"{self.api_url}/api/deployments/",
                params={"limit": limit},
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

    def trigger_deployment(
        self,
        device_ids: List[str],
        config_version: str,
        strategy: str = "atomic",
    ) -> Optional[str]:
        """POST /api/configs/deploy → returns batch_id or None on error."""
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
            r.raise_for_status()
            return r.json().get("batch_id")
        except Exception as e:
            logger.error("trigger_deployment failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Audit Log  [CURSOR IMPLEMENTS method bodies]
    # ------------------------------------------------------------------

    def get_audit_log(
        self,
        user: Optional[str] = None,
        action: Optional[str] = None,
        limit: int = 100,
    ) -> List[dict]:
        """GET /api/audit-log with optional filters."""
        params: dict = {"limit": limit}
        if user:
            params["user_id"] = user
        if action:
            params["action"] = action
        try:
            r = self.session.get(
                f"{self.api_url}/api/audit-log/", params=params, timeout=self.timeout
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error("get_audit_log failed: %s", e)
            return []
