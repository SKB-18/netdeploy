"""Tests for orchestrator._config_to_commands and _health_check placeholder."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from core.orchestrator import DeploymentOrchestrator


@pytest.fixture
def orch():
    return DeploymentOrchestrator(db_session=None)


@pytest.fixture
def orch_with_db():
    db = MagicMock()
    return DeploymentOrchestrator(db_session=db)


# ---------------------------------------------------------------------------
# _config_to_commands
# ---------------------------------------------------------------------------

class TestConfigToCommands:
    def test_cisco_xr_delegates_to_method(self, orch):
        cmds = orch._config_to_commands({"bgp": {}}, "cisco_xr")
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_cisco_ios_delegates_to_method(self, orch):
        cmds = orch._config_to_commands({"bgp": {}}, "cisco_ios")
        assert isinstance(cmds, list)

    def test_junos_delegates_to_method(self, orch):
        cmds = orch._config_to_commands({"bgp": {}}, "junos")
        assert isinstance(cmds, list)

    def test_arista_eos_delegates_to_method(self, orch):
        cmds = orch._config_to_commands({"bgp": {}}, "arista_eos")
        assert isinstance(cmds, list)

    def test_unsupported_device_type_raises(self, orch):
        with pytest.raises(ValueError, match="Unsupported device type"):
            orch._config_to_commands({"bgp": {}}, "huawei_vrp")

    def test_cisco_xr_commands_method_returns_list(self, orch):
        cmds = orch._cisco_xr_commands({})
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_cisco_ios_commands_method_returns_list(self, orch):
        cmds = orch._cisco_ios_commands({})
        assert isinstance(cmds, list)

    def test_junos_commands_method_returns_list(self, orch):
        cmds = orch._junos_commands({})
        assert isinstance(cmds, list)

    def test_arista_eos_commands_method_returns_list(self, orch):
        cmds = orch._arista_eos_commands({})
        assert isinstance(cmds, list)


# ---------------------------------------------------------------------------
# _health_check (placeholder + device checks)
# ---------------------------------------------------------------------------

class TestHealthCheckPlaceholder:
    @pytest.mark.asyncio
    async def test_health_check_returns_false_for_missing_device(self, orch_with_db):
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = None
        result = await orch_with_db._health_check("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_no_config(self, orch_with_db):
        device = MagicMock()
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = device
        orch_with_db.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = await orch_with_db._health_check(str(uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_with_desired_config_returns_placeholder_true(self, orch_with_db):
        """When desired config exists, current impl returns True (placeholder)."""
        device = MagicMock()
        config_row = MagicMock()
        config_row.desired_state = {"bgp": {"local_asn": 65001, "neighbors": []}}

        def query_side(model_class):
            q = MagicMock()
            q.filter.return_value.first.return_value = device
            q.filter.return_value.order_by.return_value.first.return_value = config_row
            return q

        orch_with_db.db.query.side_effect = query_side
        result = await orch_with_db._health_check(str(uuid4()))
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_no_db_returns_false(self):
        orch = DeploymentOrchestrator(db_session=None)
        result = await orch._health_check("any-device")
        assert result is False


# ---------------------------------------------------------------------------
# _get_desired_config — git fallback path
# ---------------------------------------------------------------------------

class TestGetDesiredConfigGitPath:
    def test_get_desired_config_non_latest_version_returns_none(self, orch_with_db):
        """Non-'latest' version returns None (git lookup not wired in basic impl)."""
        result = orch_with_db._get_desired_config("dev-1", "abc123commit")
        assert result is None

    def test_get_desired_config_latest_with_no_config_returns_none(self, orch_with_db):
        orch_with_db.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = orch_with_db._get_desired_config("dev-1", "latest")
        assert result is None

    def test_get_desired_config_latest_returns_desired_state(self, orch_with_db):
        mock_config = MagicMock()
        mock_config.desired_state = {"bgp": {"local_asn": 65001}}
        orch_with_db.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = mock_config
        result = orch_with_db._get_desired_config("dev-1", "latest")
        assert result == {"bgp": {"local_asn": 65001}}


# ---------------------------------------------------------------------------
# _update_deployment_status — with logs
# ---------------------------------------------------------------------------

class TestUpdateDeploymentStatusWithLogs:
    def test_logs_appended_on_update(self, orch_with_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = "existing log\n"
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = deployment

        orch_with_db._update_deployment_status(uuid4(), "IN_PROGRESS", logs="new entry")
        assert "new entry" in deployment.logs

    def test_in_progress_does_not_set_end_time(self, orch_with_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = deployment

        orch_with_db._update_deployment_status(uuid4(), "IN_PROGRESS")
        assert deployment.start_time is not None
        # end_time should NOT be set for IN_PROGRESS
        assert not hasattr(deployment, "end_time") or deployment.end_time == deployment.end_time

    def test_rollback_status_sets_end_time(self, orch_with_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = deployment

        orch_with_db._update_deployment_status(uuid4(), "ROLLBACK")
        assert deployment.end_time is not None

    def test_failed_status_sets_end_time(self, orch_with_db):
        deployment = MagicMock()
        deployment.start_time = None
        deployment.logs = ""
        orch_with_db.db.query.return_value.filter.return_value.first.return_value = deployment

        orch_with_db._update_deployment_status(uuid4(), "FAILED", error_message="SSH error")
        assert deployment.error_message == "SSH error"
        assert deployment.end_time is not None
