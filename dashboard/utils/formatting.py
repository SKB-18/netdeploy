"""Dashboard formatting helpers."""

from datetime import datetime
from typing import Optional


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


def status_badge(status: str) -> str:
    """Return an emoji badge for a deployment status string."""
    badges = {
        "SUCCESS": "✅ Success",
        "FAILED": "❌ Failed",
        "IN_PROGRESS": "🔄 In Progress",
        "QUEUED": "⏳ Queued",
        "ROLLBACK": "↩️ Rolled Back",
    }
    return badges.get(status.upper(), f"❓ {status}")
