"""
Phase 4 unit tests for dashboard formatting utilities.
"""

import pytest
from dashboard.utils.formatting import (
    format_duration,
    status_badge,
    config_status_badge,
    format_audit_action,
    truncate_id,
    relative_time,
    format_iso,
)


class TestFormatDuration:
    def test_seconds(self):
        assert format_duration("2024-01-01T00:00:00", "2024-01-01T00:00:45") == "45s"

    def test_minutes(self):
        assert format_duration("2024-01-01T00:00:00", "2024-01-01T00:02:30") == "2m 30s"

    def test_missing_start(self):
        assert format_duration(None, "2024-01-01T00:01:00") == "—"

    def test_missing_end(self):
        assert format_duration("2024-01-01T00:00:00", None) == "—"

    def test_both_none(self):
        assert format_duration(None, None) == "—"

    def test_invalid_timestamps(self):
        assert format_duration("not-a-date", "also-not") == "—"


class TestStatusBadge:
    def test_success(self):
        badge = status_badge("SUCCESS")
        assert "✅" in badge or "Success" in badge

    def test_failed(self):
        badge = status_badge("FAILED")
        assert "❌" in badge or "Failed" in badge

    def test_in_progress(self):
        badge = status_badge("IN_PROGRESS")
        assert "🔄" in badge or "Progress" in badge

    def test_queued(self):
        badge = status_badge("QUEUED")
        assert "⏳" in badge or "Queued" in badge

    def test_rollback(self):
        badge = status_badge("ROLLBACK")
        assert "↩️" in badge or "Roll" in badge

    def test_unknown_status(self):
        badge = status_badge("WEIRD_STATUS")
        assert "WEIRD_STATUS" in badge

    def test_lowercase_input(self):
        """Input should be case-insensitive."""
        badge = status_badge("success")
        assert "Success" in badge or "✅" in badge

    def test_empty_string(self):
        badge = status_badge("")
        assert isinstance(badge, str)


class TestConfigStatusBadge:
    def test_synced(self):
        assert "Synced" in config_status_badge("SYNCED") or "🟢" in config_status_badge("SYNCED")

    def test_drift(self):
        assert "Drift" in config_status_badge("DRIFT") or "🟡" in config_status_badge("DRIFT")

    def test_pending(self):
        assert "Pending" in config_status_badge("PENDING")

    def test_failed(self):
        assert "Failed" in config_status_badge("FAILED")


class TestFormatAuditAction:
    def test_deploy(self):
        result = format_audit_action("DEPLOY")
        assert "Deploy" in result or "🚀" in result

    def test_rollback(self):
        result = format_audit_action("ROLLBACK")
        assert "Rollback" in result or "↩️" in result

    def test_unknown(self):
        result = format_audit_action("UNKNOWN_ACTION")
        assert "UNKNOWN_ACTION" in result

    def test_empty(self):
        result = format_audit_action("")
        assert isinstance(result, str)


class TestTruncateId:
    def test_default_length(self):
        uid = "12345678-abcd-1234-efgh-000000000000"
        result = truncate_id(uid)
        assert result.startswith("12345678")
        assert "..." in result

    def test_custom_length(self):
        uid = "abcdefgh-1234"
        result = truncate_id(uid, length=4)
        assert result.startswith("abcd")
        assert "..." in result

    def test_none_input(self):
        assert truncate_id(None) == "—"

    def test_empty_string(self):
        assert truncate_id("") == "—"


class TestRelativeTime:
    def test_recent_seconds(self):
        from datetime import datetime, timezone, timedelta
        recent = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        result = relative_time(recent)
        assert "ago" in result

    def test_minutes_ago(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        result = relative_time(ts)
        assert "m ago" in result or "min" in result

    def test_hours_ago(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        result = relative_time(ts)
        assert "h ago" in result or "hr" in result

    def test_days_ago(self):
        """3 days ago → 'Xd ago' path (line 112-113)."""
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        result = relative_time(ts)
        assert "d ago" in result

    def test_over_one_week_returns_date(self):
        """More than 7 days ago → formatted date string (lines 114-115)."""
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
        result = relative_time(ts)
        # Should return a formatted date like "2026-06-18"
        assert "-" in result
        assert len(result) == 10  # YYYY-MM-DD

    def test_z_suffix_utc(self):
        """Z suffix is treated as UTC (covers the .replace('Z', '+00:00') path)."""
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(seconds=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = relative_time(ts)
        assert "ago" in result

    def test_naive_datetime_treated_as_utc(self):
        """Naive datetime (no tzinfo) is assumed UTC (line 101)."""
        from datetime import datetime, timezone, timedelta
        # ISO string without timezone suffix → naive datetime
        naive_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
        result = relative_time(naive_ts)
        assert "ago" in result

    def test_none_returns_dash(self):
        assert relative_time(None) == "—"

    def test_invalid_returns_string(self):
        result = relative_time("not-a-timestamp")
        assert isinstance(result, str)

    def test_empty_string_returns_dash(self):
        assert relative_time("") == "—"


class TestFormatIso:
    def test_valid_timestamp(self):
        result = format_iso("2024-01-15T10:30:00")
        assert "2024" in result
        assert "10:30" in result

    def test_none_returns_dash(self):
        assert format_iso(None) == "—"

    def test_invalid_returns_string(self):
        result = format_iso("not-a-date")
        assert isinstance(result, str)
