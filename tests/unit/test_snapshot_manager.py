"""Unit tests for SnapshotManager — config snapshot save/restore/diff."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from core.snapshot_manager import SnapshotManager


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_ssh():
    ssh = MagicMock()
    ssh.device_type = "cisco_xr"
    ssh.get_running_config = AsyncMock(return_value="interface Lo0\n ip address 10.0.0.1/32")
    ssh.send_config_set = AsyncMock(return_value=True)
    return ssh


@pytest.fixture
def snap(mock_db, mock_ssh):
    return SnapshotManager(db_session=mock_db, ssh_device=mock_ssh)


@pytest.fixture
def snap_no_ssh(mock_db):
    return SnapshotManager(db_session=mock_db, ssh_device=None)


# ---------------------------------------------------------------------------
# save_snapshot
# ---------------------------------------------------------------------------

class TestSaveSnapshot:
    @pytest.mark.asyncio
    async def test_saves_before_snapshot(self, snap, mock_db):
        dep_id = uuid4()
        dev_id = uuid4()
        config = {"bgp": {"local_asn": 65001}}

        mock_snapshot = MagicMock()
        mock_snapshot.id = uuid4()

        with patch("api.models.ConfigSnapshot") as MockSnap:
            instance = MockSnap.return_value
            instance.id = mock_snapshot.id
            mock_db.refresh.side_effect = lambda obj: None

            result = await snap.save_snapshot(dep_id, dev_id, config, is_before=True)

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        call_kwargs = MockSnap.call_args[1]
        assert call_kwargs["config_before"] == config
        assert call_kwargs["config_after"] is None

    @pytest.mark.asyncio
    async def test_saves_after_snapshot(self, snap, mock_db):
        dep_id = uuid4()
        dev_id = uuid4()
        config = {"bgp": {"local_asn": 65001}}

        with patch("api.models.ConfigSnapshot") as MockSnap:
            instance = MockSnap.return_value
            instance.id = uuid4()
            mock_db.refresh.side_effect = lambda obj: None

            await snap.save_snapshot(dep_id, dev_id, config, is_before=False)

        call_kwargs = MockSnap.call_args[1]
        assert call_kwargs["config_after"] == config
        assert call_kwargs["config_before"] is None

    @pytest.mark.asyncio
    async def test_snapshot_hash_computed(self, snap, mock_db):
        dep_id = uuid4()
        dev_id = uuid4()
        config = {"key": "value"}

        with patch("api.models.ConfigSnapshot") as MockSnap:
            instance = MockSnap.return_value
            instance.id = uuid4()
            mock_db.refresh.side_effect = lambda obj: None

            await snap.save_snapshot(dep_id, dev_id, config, is_before=True)

        call_kwargs = MockSnap.call_args[1]
        import hashlib
        expected_hash = hashlib.sha256(
            json.dumps(config, sort_keys=True).encode()
        ).hexdigest()
        assert call_kwargs["snapshot_hash"] == expected_hash

    @pytest.mark.asyncio
    async def test_exception_returns_none(self, snap, mock_db):
        mock_db.add.side_effect = Exception("DB error")
        with patch("api.models.ConfigSnapshot"):
            result = await snap.save_snapshot(uuid4(), uuid4(), {}, is_before=True)
        assert result is None


# ---------------------------------------------------------------------------
# restore_snapshot
# ---------------------------------------------------------------------------

class TestRestoreSnapshot:
    @pytest.mark.asyncio
    async def test_restore_with_raw_config(self, snap, mock_db, mock_ssh):
        dep_id = uuid4()
        dev_id = uuid4()
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {
            "raw": "interface Lo0\n ip address 10.0.0.1/32\n! comment",
            "format": "text",
        }
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )

        result = await snap.restore_snapshot(dep_id, dev_id)

        mock_ssh.send_config_set.assert_awaited_once()
        applied_cmds = mock_ssh.send_config_set.call_args[0][0]
        assert any("interface Lo0" in cmd for cmd in applied_cmds)
        assert result is True

    @pytest.mark.asyncio
    async def test_restore_no_snapshot_returns_false(self, snap, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        result = await snap.restore_snapshot(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_no_config_before_returns_false(self, snap, mock_db):
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = None
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )
        result = await snap.restore_snapshot(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_no_ssh_returns_false(self, snap_no_ssh, mock_db):
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {"bgp": {"local_asn": 65001}}
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )
        result = await snap_no_ssh.restore_snapshot(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_with_structured_config(self, snap, mock_db, mock_ssh):
        dep_id = uuid4()
        dev_id = uuid4()
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {
            "bgp": {"local_asn": 65001, "neighbors": []}
        }
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )

        result = await snap.restore_snapshot(dep_id, dev_id)

        mock_ssh.send_config_set.assert_awaited_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_restore_exception_returns_false(self, snap, mock_db):
        mock_db.query.side_effect = Exception("DB connection lost")
        result = await snap.restore_snapshot(uuid4(), uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_restore_ssh_failure_returns_false(self, snap, mock_db, mock_ssh):
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {"raw": "interface Lo0\n hostname test", "format": "text"}
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )
        mock_ssh.send_config_set = AsyncMock(return_value=False)

        result = await snap.restore_snapshot(uuid4(), uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------

class TestDiffSnapshots:
    def test_diff_before_and_after(self, snap, mock_db):
        dep_id = uuid4()
        dev_id = uuid4()
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {"bgp": {"local_asn": 65001}}
        mock_snapshot.config_after = {"bgp": {"local_asn": 65002}}
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )

        diff = snap.diff_snapshots(dep_id, dev_id)

        assert diff is not None
        assert "65001" in diff
        assert "65002" in diff

    def test_no_changes_returns_no_changes_string(self, snap, mock_db):
        dep_id = uuid4()
        dev_id = uuid4()
        config = {"bgp": {"local_asn": 65001}}
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = config
        mock_snapshot.config_after = config
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )

        diff = snap.diff_snapshots(dep_id, dev_id)
        assert diff == "(no changes)"

    def test_no_snapshot_returns_none(self, snap, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
        diff = snap.diff_snapshots(uuid4(), uuid4())
        assert diff is None

    def test_exception_returns_none(self, snap, mock_db):
        mock_db.query.side_effect = Exception("DB error")
        diff = snap.diff_snapshots(uuid4(), uuid4())
        assert diff is None

    def test_diff_includes_unified_diff_markers(self, snap, mock_db):
        mock_snapshot = MagicMock()
        mock_snapshot.config_before = {"x": 1}
        mock_snapshot.config_after = {"x": 2}
        mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_snapshot
        )
        diff = snap.diff_snapshots(uuid4(), uuid4())
        assert "---" in diff
        assert "+++" in diff


# ---------------------------------------------------------------------------
# capture_running_config
# ---------------------------------------------------------------------------

class TestCaptureRunningConfig:
    @pytest.mark.asyncio
    async def test_capture_returns_dict_with_raw(self, snap, mock_ssh):
        result = await snap.capture_running_config(uuid4())
        assert result is not None
        assert "raw" in result
        assert "format" in result
        assert result["format"] == "text"

    @pytest.mark.asyncio
    async def test_capture_no_ssh_returns_none(self, snap_no_ssh):
        result = await snap_no_ssh.capture_running_config(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_capture_ssh_error_returns_none(self, snap, mock_ssh):
        mock_ssh.get_running_config = AsyncMock(side_effect=RuntimeError("SSH failed"))
        result = await snap.capture_running_config(uuid4())
        assert result is None
