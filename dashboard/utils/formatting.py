"""
Dashboard formatting helpers.

Phase 4 additions:
  - format_audit_action()
  - config_status_badge()
  - truncate_id()
  - relative_time()
"""

from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Duration
# ---------------------------------------------------------------------------

def format_duration(start: Optional[str], end: Optional[str]) -> str:
    """Format deployment duration as human-readable string."""
    if not start or not end:
        return "—"
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
        seconds = int((e - s).total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        return f"{seconds // 60}m {seconds % 60}s"
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# Status badges
# ---------------------------------------------------------------------------

def status_badge(status: str) -> str:
    """Return an emoji badge for a deployment status string."""
    badges = {
        "SUCCESS": "✅ Success",
        "FAILED": "❌ Failed",
        "IN_PROGRESS": "🔄 In Progress",
        "QUEUED": "⏳ Queued",
        "ROLLBACK": "↩️ Rolled Back",
    }
    return badges.get((status or "").upper(), f"❓ {status}")


def config_status_badge(status: str) -> str:
    """Return a badge for Configuration.status (SYNCED / DRIFT / PENDING / FAILED)."""
    badges = {
        "SYNCED": "🟢 Synced",
        "DRIFT": "🟡 Drift",
        "PENDING": "⚪ Pending",
        "FAILED": "🔴 Failed",
    }
    return badges.get((status or "").upper(), f"❓ {status}")


def format_audit_action(action: str) -> str:
    """Return emoji + label for an AuditLog action."""
    icons = {
        "DEPLOY": "🚀 Deploy",
        "ROLLBACK": "↩️ Rollback",
        "CREATE": "➕ Create",
        "DELETE": "🗑️ Delete",
        "SYNC": "🔄 Sync",
        "VALIDATE": "✅ Validate",
    }
    return icons.get((action or "").upper(), f"❓ {action}")


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def truncate_id(uuid_str: Optional[str], length: int = 8) -> str:
    """Return first N characters of a UUID for display."""
    if not uuid_str:
        return "—"
    return uuid_str[:length] + "..."


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def relative_time(iso_str: Optional[str]) -> str:
    """
    Convert ISO timestamp to relative human-readable string.
    Examples: "2 minutes ago", "3 hours ago", "yesterday".

    [CURSOR IMPLEMENTS full relative time calculation]
    """
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return f"{seconds}s ago"
        elif seconds < 3600:
            return f"{seconds // 60}m ago"
        elif seconds < 86400:
            return f"{seconds // 3600}h ago"
        elif seconds < 604800:
            return f"{seconds // 86400}d ago"
        else:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso_str[:10] if iso_str else "—"


def format_iso(iso_str: Optional[str]) -> str:
    """Format ISO timestamp to 'YYYY-MM-DD HH:MM:SS' in local-ish format."""
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(iso_str)
