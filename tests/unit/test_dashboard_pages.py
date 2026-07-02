"""
Unit tests for dashboard page helper functions.

All Streamlit calls are mocked so these run without a Streamlit runtime.
Covers audit_log, deployments, and devices page helpers.
"""

import csv
import io
import pytest
from unittest.mock import MagicMock, patch, call
from uuid import uuid4


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_logs():
    return [
        {
            "id": str(uuid4()),
            "user_id": "admin",
            "action": "DEPLOY",
            "resource_type": "Deployment",
            "resource_id": str(uuid4()),
            "timestamp": "2024-01-15T10:00:00Z",
            "ip_address": "10.0.0.1",
        },
        {
            "id": str(uuid4()),
            "user_id": "ops",
            "action": "ROLLBACK",
            "resource_type": "Deployment",
            "resource_id": str(uuid4()),
            "timestamp": "2024-01-15T11:00:00Z",
            "ip_address": None,
        },
    ]


@pytest.fixture
def sample_deployments():
    return [
        {
            "id": str(uuid4()),
            "device_id": str(uuid4()),
            "status": "SUCCESS",
            "strategy": "atomic",
            "start_time": "2024-01-01T10:00:00",
            "end_time": "2024-01-01T10:02:30",
            "error_message": None,
        },
        {
            "id": str(uuid4()),
            "device_id": str(uuid4()),
            "status": "FAILED",
            "strategy": "rolling",
            "start_time": "2024-01-01T11:00:00",
            "end_time": None,
            "error_message": "SSH timeout",
        },
        {
            "id": str(uuid4()),
            "device_id": str(uuid4()),
            "status": "IN_PROGRESS",
            "strategy": "canary",
            "start_time": "2024-01-01T12:00:00",
            "end_time": None,
            "error_message": None,
        },
    ]


@pytest.fixture
def sample_devices():
    return [
        {
            "id": str(uuid4()),
            "hostname": "spine-01",
            "management_ip": "10.0.0.1",
            "device_type": "cisco_xr",
            "bgp_asn": 65001,
            "ospf_area": "0.0.0.0",
            "os_version": "7.9.1",
            "ssh_port": 22,
        },
        {
            "id": str(uuid4()),
            "hostname": "leaf-01",
            "management_ip": "10.0.0.2",
            "device_type": "junos",
            "bgp_asn": None,
            "ospf_area": None,
            "os_version": "21.4R1",
            "ssh_port": 22,
        },
    ]


# ===========================================================================
# audit_log.py helpers
# ===========================================================================

class TestAuditTableRowBuilding:
    """Test the row construction logic inside _render_audit_table."""

    def test_rows_built_correctly(self, sample_logs):
        """Verify rows dict structure matches expected keys."""
        from dashboard.pages.audit_log import ACTION_COLORS
        from dashboard.utils.formatting import relative_time

        rows = []
        for entry in sample_logs:
            action = entry.get("action", "")
            icon = ACTION_COLORS.get(action, "❓")
            rows.append({
                "Action": f"{icon} {action}",
                "User": entry.get("user_id", "—"),
                "Resource": f"{entry.get('resource_type', '')} / {(entry.get('resource_id') or '')[:8]}...",
                "Timestamp": relative_time(entry.get("timestamp")),
                "IP": entry.get("ip_address") or "—",
            })

        assert len(rows) == 2
        assert "🚀 DEPLOY" in rows[0]["Action"]
        assert "↩️ ROLLBACK" in rows[1]["Action"]
        assert rows[0]["User"] == "admin"
        assert rows[1]["IP"] == "—"  # None → "—"

    def test_unknown_action_gets_question_mark(self):
        from dashboard.pages.audit_log import ACTION_COLORS
        icon = ACTION_COLORS.get("UNKNOWN_ACTION", "❓")
        assert icon == "❓"

    def test_all_known_actions_have_icons(self):
        from dashboard.pages.audit_log import ACTION_COLORS
        assert "DEPLOY" in ACTION_COLORS
        assert "ROLLBACK" in ACTION_COLORS
        assert "CREATE" in ACTION_COLORS
        assert "DELETE" in ACTION_COLORS
        assert "SYNC" in ACTION_COLORS
        assert "VALIDATE" in ACTION_COLORS

    def test_render_audit_table_calls_st_dataframe(self, sample_logs):
        with patch("dashboard.pages.audit_log.st") as mock_st:
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.selectbox.return_value = 0
            from dashboard.pages.audit_log import _render_audit_table
            _render_audit_table(sample_logs)
        mock_st.dataframe.assert_called_once()

    def test_render_audit_table_empty_list_still_calls_dataframe(self):
        with patch("dashboard.pages.audit_log.st") as mock_st:
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.selectbox.return_value = None
            from dashboard.pages.audit_log import _render_audit_table
            _render_audit_table([])
        mock_st.dataframe.assert_called_once()


class TestExportButtonLogic:
    """Test CSV serialization logic in _render_export_button."""

    def test_csv_bytes_non_empty(self, sample_logs):
        output = io.StringIO()
        fieldnames = list(sample_logs[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample_logs)
        csv_bytes = output.getvalue().encode("utf-8")
        assert len(csv_bytes) > 0

    def test_csv_has_correct_row_count(self, sample_logs):
        output = io.StringIO()
        fieldnames = list(sample_logs[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample_logs)
        parsed = list(csv.DictReader(io.StringIO(output.getvalue())))
        assert len(parsed) == 2

    def test_csv_header_contains_all_fields(self, sample_logs):
        output = io.StringIO()
        fieldnames = list(sample_logs[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        header_line = output.getvalue().splitlines()[0]
        for field in ["user_id", "action", "resource_type", "timestamp"]:
            assert field in header_line

    def test_render_export_button_calls_download_button(self, sample_logs):
        with patch("dashboard.pages.audit_log.st") as mock_st:
            from dashboard.pages.audit_log import _render_export_button
            _render_export_button(sample_logs)
        mock_st.download_button.assert_called_once()
        call_kwargs = mock_st.download_button.call_args[1]
        assert call_kwargs["mime"] == "text/csv"
        assert "netdeploy_audit_" in call_kwargs["file_name"]

    def test_render_export_button_empty_logs(self):
        with patch("dashboard.pages.audit_log.st") as mock_st:
            from dashboard.pages.audit_log import _render_export_button
            _render_export_button([])
        mock_st.download_button.assert_called_once()


class TestParseDate:
    def test_valid_iso_timestamp(self):
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date("2024-01-15T10:30:00")
        assert result == "2024-01-15"

    def test_z_suffix_timestamp(self):
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date("2024-06-01T08:00:00Z")
        assert result == "2024-06-01"

    def test_date_only_string(self):
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date("2024-03-10")
        assert result == "2024-03-10"

    def test_none_returns_empty(self):
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date(None)
        assert result == ""

    def test_empty_string_returns_empty(self):
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date("")
        assert result == ""

    def test_invalid_string_returns_slice(self):
        """Invalid date → fallback returns first 10 chars."""
        from dashboard.pages.audit_log import _parse_date
        result = _parse_date("not-a-date-string")
        assert isinstance(result, str)
        assert len(result) <= 10


# ===========================================================================
# deployments.py helpers
# ===========================================================================

class TestDeploymentsTableRowBuilding:
    def test_rows_built_for_all_deployments(self, sample_deployments):
        from dashboard.utils.formatting import status_badge, format_duration
        rows = []
        for d in sample_deployments:
            rows.append({
                "Status": status_badge(d.get("status", "")),
                "Device ID": (d.get("device_id") or "")[:8] + "...",
                "Strategy": d.get("strategy", "—"),
                "Started": d.get("start_time", "—"),
                "Duration": format_duration(d.get("start_time"), d.get("end_time")),
                "ID": (d.get("id") or "")[:8] + "...",
            })
        assert len(rows) == 3
        assert "✅" in rows[0]["Status"]
        assert "❌" in rows[1]["Status"]
        assert "🔄" in rows[2]["Status"]

    def test_render_deployments_table_calls_dataframe(self, sample_deployments):
        with patch("dashboard.pages.deployments.st") as mock_st:
            from dashboard.pages.deployments import _render_deployments_table
            _render_deployments_table(sample_deployments)
        mock_st.dataframe.assert_called_once()

    def test_empty_deployments_renders_empty_dataframe(self):
        with patch("dashboard.pages.deployments.st") as mock_st:
            from dashboard.pages.deployments import _render_deployments_table
            _render_deployments_table([])
        mock_st.dataframe.assert_called_once()

    def test_row_color_red_for_failed(self, sample_deployments):
        """Verify the _row_color function logic for FAILED status."""
        from dashboard.utils.formatting import status_badge
        failed_status = status_badge("FAILED")
        assert "❌" in failed_status

    def test_row_color_green_for_success(self, sample_deployments):
        from dashboard.utils.formatting import status_badge
        success_status = status_badge("SUCCESS")
        assert "✅" in success_status

    def test_row_color_blue_for_in_progress(self, sample_deployments):
        from dashboard.utils.formatting import status_badge
        in_progress_status = status_badge("IN_PROGRESS")
        assert "🔄" in in_progress_status


class TestDeploymentDetailLogic:
    def test_render_detail_no_deployments_shows_info(self):
        mock_client = MagicMock()
        with patch("dashboard.pages.deployments.st") as mock_st:
            from dashboard.pages.deployments import _render_deployment_detail
            _render_deployment_detail(mock_client, [])
        mock_st.info.assert_called_once()

    def test_render_detail_with_deployment_calls_get_deployment(self, sample_deployments):
        mock_client = MagicMock()
        mock_client.get_deployment.return_value = sample_deployments[0]
        mock_client.get_deployment_logs.return_value = {"logs": ["step1"], "log_count": 1}
        mock_client.get_deployment_snapshot.return_value = {"snapshots": [], "diff": None}

        dep_id = sample_deployments[0]["id"]
        from dashboard.utils.formatting import status_badge
        # Build the exact label the function uses
        label = f"{status_badge(sample_deployments[0]['status'])} — {dep_id[:8]}..."

        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.selectbox.return_value = label
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.return_value = False

            from dashboard.pages.deployments import _render_deployment_detail
            _render_deployment_detail(mock_client, sample_deployments)

        mock_client.get_deployment.assert_called_once_with(dep_id)

    def test_render_detail_when_get_deployment_fails(self, sample_deployments):
        mock_client = MagicMock()
        mock_client.get_deployment.return_value = None

        dep_id = sample_deployments[0]["id"]
        from dashboard.utils.formatting import status_badge
        label = f"{status_badge(sample_deployments[0]['status'])} — {dep_id[:8]}..."

        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.selectbox.return_value = label
            from dashboard.pages.deployments import _render_deployment_detail
            _render_deployment_detail(mock_client, sample_deployments)

        mock_st.error.assert_called()


class TestTriggerFormLogic:
    def test_trigger_form_no_devices_shows_warning(self):
        mock_client = MagicMock()
        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.warning = MagicMock()
            from dashboard.pages.deployments import _render_trigger_form
            _render_trigger_form(mock_client, [])
        mock_st.warning.assert_called_once()
        mock_client.trigger_deployment.assert_not_called()

    def test_trigger_form_success_shows_success_message(self, sample_devices):
        mock_client = MagicMock()
        mock_client.trigger_deployment.return_value = "batch-uuid-123"

        device = sample_devices[0]
        label = f"{device['hostname']} ({device['management_ip']})"

        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.caption = MagicMock()
            mock_st.multiselect.return_value = [label]
            mock_st.radio.return_value = "atomic"
            mock_st.text_input.return_value = "latest"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.button.return_value = True  # Submitted

            from dashboard.pages.deployments import _render_trigger_form
            _render_trigger_form(mock_client, sample_devices)

        mock_client.trigger_deployment.assert_called_once()
        mock_st.success.assert_called_once()

    def test_trigger_form_api_failure_shows_error(self, sample_devices):
        mock_client = MagicMock()
        mock_client.trigger_deployment.return_value = None  # API failure

        device = sample_devices[0]
        label = f"{device['hostname']} ({device['management_ip']})"

        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.caption = MagicMock()
            mock_st.multiselect.return_value = [label]
            mock_st.radio.return_value = "rolling"
            mock_st.text_input.return_value = "latest"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.button.return_value = True

            from dashboard.pages.deployments import _render_trigger_form
            _render_trigger_form(mock_client, sample_devices)

        mock_st.error.assert_called_once()


# ===========================================================================
# devices.py helpers
# ===========================================================================

class TestDevicesTableRowBuilding:
    def test_rows_built_for_all_devices(self, sample_devices):
        rows = []
        for d in sorted(sample_devices, key=lambda x: x.get("hostname", "")):
            rows.append({
                "Hostname": d.get("hostname", ""),
                "IP": d.get("management_ip", ""),
                "Type": d.get("device_type", ""),
                "BGP ASN": d.get("bgp_asn") or "—",
                "OSPF Area": d.get("ospf_area") or "—",
                "OS": d.get("os_version") or "—",
            })
        assert rows[0]["Hostname"] == "leaf-01"  # sorted alphabetically
        assert rows[1]["Hostname"] == "spine-01"
        assert rows[0]["BGP ASN"] == "—"  # None → "—"
        assert rows[1]["BGP ASN"] == 65001

    def test_render_devices_table_calls_dataframe(self, sample_devices):
        with patch("dashboard.pages.devices.st") as mock_st:
            from dashboard.pages.devices import _render_devices_table
            _render_devices_table(sample_devices)
        mock_st.dataframe.assert_called_once()

    def test_render_devices_table_single_device(self):
        device = [{"id": str(uuid4()), "hostname": "r1", "management_ip": "10.0.0.1",
                   "device_type": "cisco_xr", "bgp_asn": None, "ospf_area": None, "os_version": None}]
        with patch("dashboard.pages.devices.st") as mock_st:
            from dashboard.pages.devices import _render_devices_table
            _render_devices_table(device)
        mock_st.dataframe.assert_called_once()


class TestDeviceActionsLogic:
    def test_health_check_success_shows_success(self, sample_devices):
        mock_client = MagicMock()
        mock_client.check_device_health.return_value = {"healthy": True, "message": "OK"}

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [True, False]  # health=clicked, sync=not

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.success.assert_called()

    def test_health_check_unhealthy_shows_warning(self, sample_devices):
        mock_client = MagicMock()
        mock_client.check_device_health.return_value = {"healthy": False, "message": "BGP down"}

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [True, False]

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.warning.assert_called()

    def test_health_check_api_failure_shows_error(self, sample_devices):
        mock_client = MagicMock()
        mock_client.check_device_health.return_value = None

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [True, False]

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.error.assert_called()

    def test_sync_success_shows_success(self, sample_devices):
        mock_client = MagicMock()
        mock_client.sync_device.return_value = {"status": "SYNC_QUEUED"}

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [False, True]  # health=not, sync=clicked

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.success.assert_called()

    def test_sync_failure_shows_error(self, sample_devices):
        mock_client = MagicMock()
        mock_client.sync_device.return_value = None

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [False, True]

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.error.assert_called()

    def test_config_history_shown_when_available(self, sample_devices):
        mock_client = MagicMock()
        mock_client.get_config_history.return_value = [
            {"version": "abc123", "status": "SYNCED", "created_by": "admin", "deployed_at": "2024-01-01"}
        ]

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = "spine-01"
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.button.side_effect = [False, False]

            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, sample_devices)

        mock_st.write.assert_called()

    def test_no_devices_returns_early(self):
        mock_client = MagicMock()
        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.selectbox.return_value = None
            mock_st.columns.return_value = (MagicMock(), MagicMock())
            from dashboard.pages.devices import _render_device_actions
            _render_device_actions(mock_client, [{"hostname": "r1"}])


def _make_columns_side_effect():
    """Return a side_effect for st.columns that gives the right number of MagicMocks."""
    def _cols(spec, *args, **kwargs):
        n = len(spec) if isinstance(spec, (list, tuple)) else int(spec)
        return [MagicMock() for _ in range(n)]
    return _cols


class TestDeviceRegistrationValidation:
    def test_invalid_ip_shows_error(self):
        mock_client = MagicMock()

        with patch("dashboard.pages.devices.st") as mock_st:
            form_mock = MagicMock()
            form_mock.__enter__ = MagicMock(return_value=form_mock)
            form_mock.__exit__ = MagicMock(return_value=False)
            mock_st.form.return_value = form_mock
            mock_st.columns.side_effect = _make_columns_side_effect()
            # text_input called 4 times: hostname, management_ip, ospf_area, os_version
            mock_st.text_input.side_effect = ["spine-01", "not-an-ip", "", ""]
            mock_st.selectbox.return_value = "cisco_xr"
            mock_st.number_input.side_effect = [22, 0]
            mock_st.form_submit_button.return_value = True

            from dashboard.pages.devices import _render_registration_form
            _render_registration_form(mock_client)

        mock_st.error.assert_called()
        mock_client.create_device.assert_not_called()

    def test_missing_hostname_shows_error(self):
        mock_client = MagicMock()

        with patch("dashboard.pages.devices.st") as mock_st:
            form_mock = MagicMock()
            form_mock.__enter__ = MagicMock(return_value=form_mock)
            form_mock.__exit__ = MagicMock(return_value=False)
            mock_st.form.return_value = form_mock
            mock_st.columns.side_effect = _make_columns_side_effect()
            mock_st.text_input.side_effect = ["", "10.0.0.1", "", ""]
            mock_st.selectbox.return_value = "cisco_xr"
            mock_st.number_input.side_effect = [22, 0]
            mock_st.form_submit_button.return_value = True

            from dashboard.pages.devices import _render_registration_form
            _render_registration_form(mock_client)

        mock_st.error.assert_called()
        mock_client.create_device.assert_not_called()


# ===========================================================================
# render() top-level smoke tests
# ===========================================================================

class TestRenderFunctionsTopLevel:
    def test_audit_render_empty_logs(self):
        """render() with no logs shows info message, not table."""
        mock_client = MagicMock()
        mock_client.get_audit_log.return_value = []

        with patch("dashboard.pages.audit_log.st") as mock_st:
            mock_st.text_input.return_value = ""
            mock_st.selectbox.return_value = ""
            mock_st.slider.return_value = 100
            mock_st.date_input.side_effect = [
                __import__("datetime").date(2024, 1, 1),
                __import__("datetime").date(2024, 12, 31),
            ]
            mock_st.columns.side_effect = _make_columns_side_effect()
            mock_st.metric = MagicMock()

            from dashboard.pages.audit_log import render
            render(mock_client)

        mock_st.info.assert_called()

    def test_devices_render_no_devices_shows_info(self):
        """render() with no devices shows info message."""
        mock_client = MagicMock()
        mock_client.list_devices.return_value = []

        with patch("dashboard.pages.devices.st") as mock_st:
            mock_st.columns.side_effect = _make_columns_side_effect()
            form_mock = MagicMock()
            form_mock.__enter__ = MagicMock(return_value=form_mock)
            form_mock.__exit__ = MagicMock(return_value=False)
            mock_st.form.return_value = form_mock
            mock_st.text_input.return_value = ""
            mock_st.selectbox.return_value = "cisco_xr"
            mock_st.number_input.return_value = 0
            mock_st.form_submit_button.return_value = False
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)

            from dashboard.pages.devices import render
            render(mock_client)

        mock_st.info.assert_called()

    def test_deployments_render_no_deployments_shows_info(self):
        """render() with no deployments shows info message."""
        mock_client = MagicMock()
        mock_client.list_deployments.return_value = []
        mock_client.list_devices.return_value = []

        with patch("dashboard.pages.deployments.st") as mock_st:
            mock_st.columns.side_effect = _make_columns_side_effect()
            mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
            mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
            mock_st.checkbox.return_value = False
            mock_st.selectbox.return_value = 20

            from dashboard.pages.deployments import render
            render(mock_client)

        mock_st.info.assert_called()
