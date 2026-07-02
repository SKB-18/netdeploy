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
    queued = [d for d in deployments if d.get("status") == "QUEUED"]
    successful = [d for d in deployments if d.get("status") == "SUCCESS"]
    success_rate = (
        f"{len(successful) / len(deployments) * 100:.0f}%"
        if deployments else "N/A"
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("In Progress", len(active))
    with col2:
        st.metric("Queued", len(queued))
    with col3:
        st.metric("Success Rate", success_rate)
    with col4:
        st.metric("Total Deployments", len(deployments))

    st.divider()

    # ------------------------------------------------------------------
    # Section 2: Trigger new deployment
    # ------------------------------------------------------------------
    st.subheader("➕ Trigger New Deployment")
    _render_trigger_form(client, devices)

    st.divider()

    # ------------------------------------------------------------------
    # Section 3: Recent deployments table
    # ------------------------------------------------------------------
    st.subheader("Recent Deployments")

    col_refresh, col_limit = st.columns([3, 1])
    with col_refresh:
        auto_refresh = st.checkbox("Auto-refresh every 5s", value=True)
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


def _default_desired_state(device: dict, bgp_asn: int, ospf_area: str) -> dict:
    """Build a minimal valid BGP+OSPF config from device inventory fields."""
    router_id = device.get("management_ip") or "10.0.0.1"
    parts = router_id.rsplit(".", 1)
    network = f"{parts[0]}.0/24" if len(parts) == 2 else "10.0.0.0/24"
    return {
        "bgp": {
            "local_asn": int(bgp_asn),
            "router_id": router_id,
            "neighbors": [],
            "route_policies": [],
        },
        "ospf": {
            "process_id": 1,
            "router_id": router_id,
            "areas": [{"area_id": ospf_area, "networks": [network]}],
        },
    }


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
    devices_by_id = {d.get("id"): d for d in devices}

    if selected_labels:
        missing_config = []
        for label in selected_labels:
            device_id = device_options[label]
            if not client.get_config_history(device_id, limit=1):
                missing_config.append(label)
        if missing_config:
            st.warning(
                "No saved configuration yet for: "
                + ", ".join(f"**{name}**" for name in missing_config)
                + ". Fill in the fields below — a config will be created automatically when you deploy."
            )

    st.markdown("**Initial configuration** *(required for new devices)*")
    default_asn = 65001
    if selected_labels:
        first_device = devices_by_id.get(device_options[selected_labels[0]], {})
        default_asn = first_device.get("bgp_asn") or 65001
    bgp_asn = st.number_input("BGP local ASN", min_value=1, max_value=4294967295, value=int(default_asn))
    ospf_area = st.text_input("OSPF area ID", value="0.0.0.0")

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
        if not selected_labels:
            st.caption("Select at least one device to enable deployment.")

    if submitted and selected_labels:
        device_ids = [device_options[label] for label in selected_labels]

        for label in selected_labels:
            device_id = device_options[label]
            if client.get_config_history(device_id, limit=1):
                continue
            device = devices_by_id.get(device_id, {})
            desired_state = _default_desired_state(device, bgp_asn, ospf_area)
            created = client.create_config(
                device_id,
                desired_state,
                description=f"Dashboard config for {device.get('hostname', device_id)}",
            )
            if not created:
                st.error(f"Could not save configuration for **{label}**. Fix validation errors and try again.")
                return

        result = client.trigger_deployment_detailed(device_ids, config_version, strategy)
        if result.get("success"):
            batch_id = result.get("batch_id")
            st.success(f"Deployment queued! Batch ID: `{batch_id}`")
            st.info("The worker usually finishes in a few seconds. Refresh the table below for status.")
        else:
            detail = result.get("detail")
            if isinstance(detail, dict):
                st.error(detail.get("message", "Deployment rejected"))
                missing = detail.get("missing_device_ids") or []
                if missing:
                    st.caption(f"Missing config for device(s): {', '.join(missing)}")
            else:
                st.error(f"Failed to trigger deployment: {detail or 'Check API logs.'}")


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
    st.dataframe(df, use_container_width=True, hide_index=True)


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
        status = detail.get("status", "")
        # Rollback only applies when config was actually applied (SUCCESS)
        can_rollback = status == "SUCCESS"
        if status == "FAILED":
            st.caption("Nothing to roll back — failed before config was applied.")
        elif status == "QUEUED":
            st.caption("Still processing — wait a few seconds.")
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
        elif detail.get("error_message"):
            st.code(detail["error_message"], language="text")
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
