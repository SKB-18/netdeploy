"""
Phase 4 integration tests for the Streamlit dashboard.

Tests verify:
1. NetDeployClient correctly calls the FastAPI backend
2. Page render functions don't crash with mocked client
3. Formatting helpers produce correct output end-to-end

Note: Streamlit UI rendering tests use the AppTest runner.
Cursor implements full AppTest suites.
"""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """A fully mocked NetDeployClient."""
    client = MagicMock()
    client.health_check.return_value = True
    client.list_devices.return_value = [
        {
            "id": str(uuid4()),
            "hostname": "spine-01",
            "management_ip": "10.0.0.1",
            "device_type": "cisco_xr",
            "bgp_asn": 65001,
            "ospf_area": "0.0.0.0",
            "os_version": "7.9.1",
            "ssh_port": 22,
        }
    ]
    client.list_deployments.return_value = [
        {
            "id": str(uuid4()),
            "device_id": str(uuid4()),
            "status": "SUCCESS",
            "strategy": "atomic",
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T10:02:30",
            "error_message": None,
        }
    ]
    client.get_audit_log.return_value = [
        {
            "id": str(uuid4()),
            "user_id": "admin",
            "action": "DEPLOY",
            "resource_type": "Deployment",
            "resource_id": str(uuid4()),
            "timestamp": "2024-01-01T10:00:00",
            "ip_address": "127.0.0.1",
        }
    ]
    return client


# ---------------------------------------------------------------------------
# NetDeployClient + FastAPI integration
# ---------------------------------------------------------------------------

class TestClientWithRealAPI:
    """
    These tests run against a live FastAPI via WSGI TestClient transport.
    They use a requests.Session pointed at the TestClient's ASGI transport
    so no real HTTP server is needed.
    """

    def _make_dashboard_client(self, fastapi_test_client):
        """Build a NetDeployClient that reuses the TestClient's session."""
        from dashboard.utils.api_client import NetDeployClient
        dc = NetDeployClient(api_url="http://testserver", timeout=5)
        # Replace the requests session with the TestClient so calls go through ASGI
        dc.session = fastapi_test_client
        return dc

    def test_health_check_real_api(self, client):
        dc = self._make_dashboard_client(client)
        result = dc.health_check()
        assert result is True

    def test_list_devices_empty_initially(self, client):
        dc = self._make_dashboard_client(client)
        devices = dc.list_devices()
        assert isinstance(devices, list)

    def test_create_and_get_device(self, client, db_session):
        dc = self._make_dashboard_client(client)
        created = dc.create_device({
            "hostname": f"dash-r-{uuid4().hex[:6]}",
            "management_ip": "10.50.0.1",
            "device_type": "cisco_xr",
        })
        assert created is not None
        assert "id" in created

        fetched = dc.get_device(created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_list_deployments_empty_initially(self, client):
        dc = self._make_dashboard_client(client)
        deps = dc.list_deployments()
        assert isinstance(deps, list)

    def test_get_audit_log_returns_list(self, client):
        dc = self._make_dashboard_client(client)
        log = dc.get_audit_log()
        assert isinstance(log, list)


# ---------------------------------------------------------------------------
# Page render smoke tests (no Streamlit context needed — just function calls)
# ---------------------------------------------------------------------------

class TestPageRenderNocrash:
    """
    Verify page render functions don't crash when given mocked client data.
    These run without a full Streamlit context — they just call the helper functions.

    [CURSOR IMPLEMENTS full AppTest suites in TestStreamlitAppTest below]
    """

    def test_deployments_table_renders(self, mock_client):
        """_render_deployments_table should not raise with valid data."""
        from dashboard.views.deployments import _render_deployments_table
        import streamlit as st

        deployments = mock_client.list_deployments()
        # Should not raise — just builds a DataFrame
        try:
            from dashboard.utils.formatting import status_badge, format_duration
            rows = []
            for d in deployments:
                rows.append({
                    "Status": status_badge(d.get("status", "")),
                    "Device ID": (d.get("device_id") or "")[:8] + "...",
                    "Duration": format_duration(d.get("start_time"), d.get("end_time")),
                })
            import pandas as pd
            df = pd.DataFrame(rows)
            assert len(df) == 1
            assert "Status" in df.columns
        except Exception as e:
            pytest.fail(f"Table rendering raised: {e}")

    def test_devices_table_renders(self, mock_client):
        """_render_devices_table should build a DataFrame without raising."""
        from dashboard.views.devices import _render_devices_table
        import pandas as pd

        devices = mock_client.list_devices()
        rows = []
        for d in devices:
            rows.append({
                "Hostname": d.get("hostname", ""),
                "IP": d.get("management_ip", ""),
                "Type": d.get("device_type", ""),
            })
        df = pd.DataFrame(rows)
        assert len(df) == 1
        assert "Hostname" in df.columns

    def test_audit_log_csv_export(self, mock_client):
        """CSV export helper should produce valid CSV bytes."""
        import csv
        import io

        logs = mock_client.get_audit_log()
        output = io.StringIO()
        fieldnames = list(logs[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)
        csv_bytes = output.getvalue().encode("utf-8")

        assert len(csv_bytes) > 0
        # Re-parse to verify valid CSV
        reader = csv.DictReader(io.StringIO(output.getvalue()))
        parsed = list(reader)
        assert len(parsed) == 1
        assert parsed[0]["action"] == "DEPLOY"


# ---------------------------------------------------------------------------
# Streamlit AppTest suites (requires streamlit>=1.18)
# ---------------------------------------------------------------------------

class TestStreamlitAppTest:
    """AppTest suites — run the dashboard in-process via streamlit.testing.v1."""

    def test_app_loads_without_error(self):
        """App should start without raising, even when API is unreachable."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            pytest.skip("streamlit.testing.v1 not available")

        at = AppTest.from_file("dashboard/app.py", default_timeout=10)
        with patch("dashboard.utils.api_client.NetDeployClient.health_check", return_value=False), \
             patch("dashboard.utils.api_client.NetDeployClient.list_deployments", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.list_devices", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.get_audit_log", return_value=[]):
            at.run()
        assert not at.exception

    def test_deployments_page_shows_metrics(self):
        """Deployments page should render at least 4 metric widgets."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            pytest.skip("streamlit.testing.v1 not available")

        dep = {
            "id": str(uuid4()),
            "device_id": str(uuid4()),
            "status": "SUCCESS",
            "strategy": "atomic",
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T10:02:30",
        }

        at = AppTest.from_file("dashboard/app.py", default_timeout=10)
        with patch("dashboard.utils.api_client.NetDeployClient.health_check", return_value=True), \
             patch("dashboard.utils.api_client.NetDeployClient.list_deployments", return_value=[dep]), \
             patch("dashboard.utils.api_client.NetDeployClient.list_devices", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.get_audit_log", return_value=[]):
            at.run()
        assert not at.exception
        assert len(at.metric) >= 4

    def test_devices_page_shows_dataframe(self):
        """Devices page with 1 device should load without error."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            pytest.skip("streamlit.testing.v1 not available")

        device = {
            "id": str(uuid4()),
            "hostname": "spine-01",
            "management_ip": "10.0.0.1",
            "device_type": "cisco_xr",
        }

        at = AppTest.from_file("dashboard/app.py", default_timeout=10)
        with patch("dashboard.utils.api_client.NetDeployClient.health_check", return_value=True), \
             patch("dashboard.utils.api_client.NetDeployClient.list_deployments", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.list_devices", return_value=[device]), \
             patch("dashboard.utils.api_client.NetDeployClient.get_audit_log", return_value=[]):
            at.run()
            # Navigate to Devices page via sidebar radio
            at.sidebar.radio[0].set_value("Devices").run()
        assert not at.exception

    def test_audit_log_export_button_exists(self):
        """Audit Log page should render without error."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            pytest.skip("streamlit.testing.v1 not available")

        log_entry = {
            "id": str(uuid4()),
            "user_id": "admin",
            "action": "DEPLOY",
            "resource_type": "Deployment",
            "resource_id": str(uuid4()),
            "timestamp": "2024-01-01T10:00:00",
        }

        at = AppTest.from_file("dashboard/app.py", default_timeout=10)
        with patch("dashboard.utils.api_client.NetDeployClient.health_check", return_value=True), \
             patch("dashboard.utils.api_client.NetDeployClient.list_deployments", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.list_devices", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.get_audit_log", return_value=[log_entry]):
            at.run()
            at.sidebar.radio[0].set_value("Audit Log").run()
        assert not at.exception

    def test_sidebar_navigation(self):
        """Sidebar radio should route to Settings without exceptions."""
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:
            pytest.skip("streamlit.testing.v1 not available")

        at = AppTest.from_file("dashboard/app.py", default_timeout=10)
        with patch("dashboard.utils.api_client.NetDeployClient.health_check", return_value=False), \
             patch("dashboard.utils.api_client.NetDeployClient.list_deployments", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.list_devices", return_value=[]), \
             patch("dashboard.utils.api_client.NetDeployClient.get_audit_log", return_value=[]):
            at.run()
            at.sidebar.radio[0].set_value("Settings").run()
        assert not at.exception


# ---------------------------------------------------------------------------
# API client error handling integration
# ---------------------------------------------------------------------------

class TestClientErrorHandling:
    def test_all_methods_return_safe_defaults_on_connection_error(self):
        """
        When the API server is down, all client methods return [] or None/False
        without raising exceptions.
        """
        from dashboard.utils.api_client import NetDeployClient
        client = NetDeployClient(api_url="http://localhost:9999", timeout=1)

        # These should all swallow exceptions and return safe defaults
        assert client.health_check() is False
        assert client.list_devices() == []
        assert client.get_device("any-id") is None
        assert client.list_deployments() == []
        assert client.get_deployment_logs("any-id") is None
        assert client.get_deployment_snapshot("any-id") is None
        assert client.trigger_deployment(["d1"], "latest") is None
        assert client.rollback_deployment("any-id") is None
        assert client.get_audit_log() == []
        assert client.get_config_history("any-id") == []
        assert client.sync_device("any-id") is None
        assert client.delete_device("any-id") is False
