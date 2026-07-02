"""
Deployments page — real-time deployment monitoring and control.

Phase 4 Cowork: full UI scaffold — metrics, dataframe, detail panel,
                log viewer, rollback button, trigger form.

Cursor implements:
  - Real-time auto-refresh (st.rerun + time.sleep)
  - Status color-coding in dataframe (pd.DataFrame + st.dataframe column_config)
  - Log streaming in deployment detail
  - Rollback button calling client.rollback_deployment()
  - Trigger deployment form with device multi-select + strategy picker
"""

import ipaddress
import time

import pandas as pd
import streamlit as st

from dashboard.utils.api_client import NetDeployClient
from dashboard.utils.formatting import format_duration, status_badge


def render(client: NetDeployClient):
    """Render the Deployments page."""
    st.title("🚀 Deployments")

    # ------------------------------------------------------------------
    # Section 1: Summary metrics
    # ------------------------------------------------------------------
    deployments = client.list_deployments(limit=100)
    devices = client.list_devices()

    active = [d for d in deployments if d.get("status") == "IN_PROGRESS"]
    successful = [d for d in deployments if d.get("status") == "SUCCESS"]
    success_rate = (
        f"{len(successful) / len(deployments) * 100:.0f}%"
        if deployments else "N/A"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Active", len(active))
    with col2:
        st.metric("Success Rate", success_rate)
    with col3:
        st.metric("Total Deployments", len(deployments))
    with col4:
        st.metric("Devices Managed", len(devices))

    st.divider()

    # ------------------------------------------------------------------
    # Section 2: Trigger new deployment
    # ------------------------------------------------------------------
    with st.expander("➕ Trigger New Deployment"):
        _render_trigger_form(client, devices)

    st.divider()

    # ------------------------------------------------------------------
    # Section 3: Recent deployments table
    # ------------------------------------------------------------------
    st.subheader("Recent Deployments")

    col_refresh, col_limit = st.columns([3, 1])
    with col_refresh:
        auto_refresh = st.checkbox("Auto-refresh every 5s", value=False)
    with col_limit:
        limit = st.selectbox("Show", [20, 50, 100], index=0, label_visibility="collapsed")

    deployments = client.list_deployments(limit=limit)

    if not deployments:
        st.info("No deployments yet. Use the form above to trigger one.")
    else:
        _render_deployments_table(deployments)

    st.divider()

    # ------------------------------------------------------------------
    # Section 4: Deployment detail + logs
    # ------------------------------------------------------------------
    st.subheader("Deployment Detail & Logs")
    _render_deployment_detail(client, deployments)

    # ------------------------------------------------------------------
    # Auto-refresh
    # ------------------------------------------------------------------
    if auto_refresh:
        time.sleep(5)
        st.rerun()


def _render_trigger_form(client: NetDeployClient, devices: list):
    """
    Form to trigger a new deployment batch.

    Cursor implements:
    - Multi-select for device_ids (shows hostname + IP)
    - Strategy radio: canary / rolling / atomic
    - Config version text input (default "latest")
    - Submit → client.trigger_deployment() → show batch_id
    - Disable submit button while active deployment exists

    [CURSOR IMPLEMENTS]
    """
    st.caption("Select devices, choose a strategy, and deploy the latest validated config.")

    device_options = {
        f"{d.get('hostname')} ({d.get('management_ip')})": d.get("id")
        for d in devices
    }

    if not device_options:
        st.warning("No devices registered. Go to the Devices page to add devices first.")
        return

    selected_labels = st.multiselect("Devices", list(device_options.keys()))
    strategy = st.radio(
        "Strategy",
        ["atomic", "rolling", "canary"],
        horizontal=True,
        help="atomic=all-or-nothing | rolling=sequential | canary=test one first",
    )
    config_version = st.text_input("Config version", value="latest")

    col_submit, col_hint = st.columns([1, 3])
    with col_submit:
        submitted = st.button("🚀 Deploy", type="primary", disabled=not selected_labels)
    with col_hint:
        st.caption("Select at least one device to enable deployment.")

    if submitted and selected_labels:
        # [CURSOR IMPLEMENTS actual call + success/error feedback]
        device_ids = [device_options[label] for label in selected_labels]
        batch_id = client.trigger_deployment(device_ids, config_version, strategy)
        if batch_id:
            st.success(f"Deployment queued! Batch ID: `{batch_id}`")
        else:
            st.error("Failed to trigger deployment. Check API logs.")


def _render_deployments_table(deployments: list):
    """
    Render deployments as a colored dataframe.
    Rows are color-coded: ❌ → red, ✅ → green, 🔄 → blue.
    """
    rows = []
    for d in deployments:
        rows.append({
            "Status": status_badge(d.get("status", "")),
            "Device ID": (d.get("device_id") or "")[:8] + "...",
            "Strategy": d.get("strategy", "—"),
            "Started": d.get("start_time", "—"),
            "Duration": format_duration(d.get("start_time"), d.get("end_time")),
            "ID": (d.get("id") or "")[:8] + "...",
        })

    df = pd.DataFrame(rows)

    def _row_color(row):
        status = row["Status"]
        if "❌" in status:
            return ["background-color: #ffd6d6"] * len(row)
        if "✅" in status:
            return ["background-color: #d6f5d6"] * len(row)
        if "🔄" in status:
            return ["background-color: #d6e8ff"] * len(row)
        return [""] * len(row)

    styled = df.style.apply(_row_color, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_deployment_detail(client: NetDeployClient, deployments: list):
    """
    Show deployment logs, snapshot diff, and rollback button.

    Cursor implements:
    - Logs in st.code() block (monospace)
    - Config diff in st.code(language='diff')
    - Rollback button → client.rollback_deployment(id)

    [CURSOR IMPLEMENTS log fetch + diff display + rollback action]
    """
    if not deployments:
        st.info("No deployments to show.")
        return

    options = {
        f"{status_badge(d.get('status',''))} — {(d.get('id') or '')[:8]}...": d.get("id")
        for d in deployments
    }
    selected_label = st.selectbox("Select deployment", list(options.keys()))
    selected_id = options.get(selected_label)

    if not selected_id:
        return

    detail = client.get_deployment(selected_id)
    if not detail:
        st.error("Could not load deployment.")
        return

    col_meta, col_actions = st.columns([3, 1])
    with col_meta:
        st.write(f"**Status:** {status_badge(detail.get('status', ''))}")
        st.write(f"**Device:** `{detail.get('device_id', 'N/A')}`")
        st.write(f"**Duration:** {format_duration(detail.get('start_time'), detail.get('end_time'))}")
        if detail.get("error_message"):
            st.error(f"Error: {detail['error_message']}")

    with col_actions:
        st.write("")
        can_rollback = detail.get("status") in ("SUCCESS", "FAILED")
        if st.button("↩️ Rollback", disabled=not can_rollback, type="secondary"):
            # [CURSOR IMPLEMENTS rollback call]
            result = client.rollback_deployment(selected_id)
            if result:
                st.success(f"Rollback queued: task `{result}`")
            else:
                st.error("Rollback failed.")

    # Logs panel
    with st.expander("📋 Deployment Logs", expanded=True):
        with st.spinner("Loading logs..."):
            logs_data = client.get_deployment_logs(selected_id)
        if logs_data and logs_data.get("logs"):
            log_text = "\n".join(logs_data["logs"])
            st.code(log_text, language="text")
        else:
            st.caption("No logs available yet.")

    # Config diff panel
    with st.expander("🔀 Config Diff (Before → After)"):
        snap_data = client.get_deployment_snapshot(selected_id)
        if snap_data and snap_data.get("diff"):
            st.code(snap_data["diff"], language="diff")
        elif snap_data and snap_data.get("snapshots"):
            st.write(f"{len(snap_data['snapshots'])} snapshot(s) captured — diff pending.")
        else:
            st.caption("No snapshot available.")
