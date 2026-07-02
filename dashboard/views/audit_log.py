"""
Audit Log page — searchable, filterable compliance trail.

Phase 4 Cowork: full UI scaffold with filters, styled dataframe, CSV export,
                detail modal, and entry count metrics.

Cursor implements:
  - Filter by user, action, resource_type, date range
  - Styled dataframe with action color-coding
  - CSV export via st.download_button
  - Audit entry detail click-to-expand
"""

import csv
import io
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from dashboard.utils.api_client import NetDeployClient
from dashboard.utils.formatting import format_audit_action, relative_time


ACTION_COLORS = {
    "DEPLOY": "🚀",
    "ROLLBACK": "↩️",
    "CREATE": "➕",
    "DELETE": "🗑️",
    "SYNC": "🔄",
    "VALIDATE": "✅",
}


def render(client: NetDeployClient):
    """Render the Audit Log page."""
    st.title("📋 Audit Log")

    # ------------------------------------------------------------------
    # Section 1: Filters
    # ------------------------------------------------------------------
    st.subheader("Filters")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        user_filter = st.text_input("User ID", placeholder="Leave blank for all")
    with col2:
        action_filter = st.selectbox(
            "Action",
            ["", "DEPLOY", "ROLLBACK", "CREATE", "DELETE", "SYNC", "VALIDATE"],
        )
    with col3:
        resource_filter = st.selectbox(
            "Resource Type",
            ["", "Device", "Configuration", "Deployment"],
        )
    with col4:
        limit = st.slider("Max entries", 10, 500, 100, step=10)

    col_date1, col_date2 = st.columns(2)
    with col_date1:
        date_from = st.date_input(
            "From date",
            value=datetime.utcnow().date() - timedelta(days=30),
        )
    with col_date2:
        date_to = st.date_input("To date", value=datetime.utcnow().date())

    st.divider()

    # ------------------------------------------------------------------
    # Section 2: Fetch + display
    # ------------------------------------------------------------------
    logs = client.get_audit_log(
        user=user_filter or None,
        action=action_filter or None,
        limit=limit,
    )

    # Client-side date filter (server may not support date range)
    # [CURSOR IMPLEMENTS server-side date filtering if API supports it]
    if date_from and logs:
        logs = [
            entry for entry in logs
            if _parse_date(entry.get("timestamp")) >= str(date_from)
        ]

    # Metrics row
    total = len(logs)
    deploys = sum(1 for e in logs if e.get("action") == "DEPLOY")
    rollbacks = sum(1 for e in logs if e.get("action") == "ROLLBACK")

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("Total Entries", total)
    with mc2:
        st.metric("Deployments", deploys)
    with mc3:
        st.metric("Rollbacks", rollbacks)

    st.divider()

    if not logs:
        st.info("No audit log entries match the current filters.")
        return

    # ------------------------------------------------------------------
    # Section 3: Log table
    # ------------------------------------------------------------------
    _render_audit_table(logs)

    st.divider()

    # ------------------------------------------------------------------
    # Section 4: CSV export
    # ------------------------------------------------------------------
    _render_export_button(logs)


def _render_audit_table(logs: list):
    """
    Render audit log as a styled dataframe.

    Cursor implements:
    - Action column with emoji prefix via ACTION_COLORS map
    - Timestamp formatted as local time
    - Resource column linking to device/deployment ID
    - Click a row → expand JSON details below

    [CURSOR IMPLEMENTS emoji column + detail expand]
    """
    rows = []
    for entry in logs:
        action = entry.get("action", "")
        icon = ACTION_COLORS.get(action, "❓")
        rows.append({
            "Action": f"{icon} {action}",
            "User": entry.get("user_id", "—"),
            "Resource": f"{entry.get('resource_type', '')} / {(entry.get('resource_id') or '')[:8]}...",
            "Timestamp": relative_time(entry.get("timestamp")),
            "IP": entry.get("ip_address") or "—",
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Entry detail viewer
    with st.expander("🔍 Entry Detail (select index above, then expand)"):
        entry_indices = list(range(len(logs)))
        selected_idx = st.selectbox("Entry #", entry_indices, format_func=lambda i: f"#{i} — {logs[i].get('action', '?')}")
        if selected_idx is not None:
            entry = logs[selected_idx]
            st.json(entry)


def _render_export_button(logs: list):
    """
    CSV export of audit log entries.

    Cursor implements:
    - Convert logs list to CSV in-memory
    - st.download_button with filename = netdeploy_audit_{date}.csv

    [CURSOR IMPLEMENTS CSV serialization]
    """
    st.subheader("Export")

    # Build CSV in memory
    output = io.StringIO()
    if logs:
        fieldnames = list(logs[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"netdeploy_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"

    st.download_button(
        label="⬇️ Export CSV",
        data=csv_bytes,
        file_name=filename,
        mime="text/csv",
    )


def _parse_date(timestamp_str) -> str:
    """Parse ISO timestamp to date string for comparison."""
    if not timestamp_str:
        return ""
    try:
        return str(datetime.fromisoformat(str(timestamp_str)).date())
    except Exception:
        return str(timestamp_str)[:10]
