"""
Devices page — device inventory, health status, config drift, registration.

Phase 4 Cowork: full UI scaffold with registration form, health table,
                device detail, sync button, config drift indicator.

Cursor implements:
  - Device registration form → client.create_device()
  - Health-check button → client.check_device_health()
  - Sync button → client.sync_device()
  - Config drift badge: SYNCED=green, DRIFT=yellow, PENDING=gray
  - Device detail expander with BGP/OSPF desired state as JSON
"""

import ipaddress
import streamlit as st
import pandas as pd

from dashboard.utils.api_client import NetDeployClient

DEVICE_TYPES = ["cisco_xr", "cisco_ios", "junos", "arista_eos", "nokia_sros"]


def render(client: NetDeployClient):
    """Render the Devices page."""
    st.title("🖧 Devices")

    with st.expander("➕ Register New Device"):
        _render_registration_form(client)

    st.divider()
    st.subheader("Device Inventory")

    devices = client.list_devices()
    if not devices:
        st.info("No devices registered. Use the form above to add your first device.")
    else:
        _render_devices_table(devices)
        st.divider()
        st.subheader("Device Actions")
        _render_device_actions(client, devices)


def _render_registration_form(client: NetDeployClient):
    """
    Form to register a new network device.

    Fields: hostname, management_ip, device_type, ssh_port, bgp_asn, ospf_area, os_version.
    On submit → client.create_device() → show success with device ID.

    [CURSOR IMPLEMENTS form validation + API call]
    """
    st.caption("Add a network device to the NetDeploy inventory.")

    with st.form("register_device"):
        col1, col2 = st.columns(2)
        with col1:
            hostname = st.text_input("Hostname *", placeholder="spine-01")
            management_ip = st.text_input("Management IP *", placeholder="10.0.0.1")
            device_type = st.selectbox("Device Type *", DEVICE_TYPES)
            ssh_port = st.number_input("SSH Port", value=22, min_value=1, max_value=65535)
        with col2:
            bgp_asn = st.number_input("BGP ASN", value=0, min_value=0, max_value=4294967295,
                                       help="Leave 0 if not applicable")
            ospf_area = st.text_input("OSPF Area", placeholder="0.0.0.0")
            os_version = st.text_input("OS Version", placeholder="7.9.1")

        submitted = st.form_submit_button("Register Device", type="primary")

    if submitted:
        if not hostname or not management_ip:
            st.error("Hostname and Management IP are required.")
            return

        # IP address format validation
        try:
            ipaddress.IPv4Address(management_ip)
        except ValueError:
            st.error(f"Invalid IP address: '{management_ip}'. Must be a valid IPv4 address (e.g. 10.0.0.1).")
            return

        device_data = {
            "hostname": hostname,
            "management_ip": management_ip,
            "device_type": device_type,
            "ssh_port": ssh_port,
        }
        if bgp_asn > 0:
            device_data["bgp_asn"] = bgp_asn
        if ospf_area:
            device_data["ospf_area"] = ospf_area
        if os_version:
            device_data["os_version"] = os_version

        # [CURSOR IMPLEMENTS]: call client.create_device() + handle 422 duplicate hostname
        result = client.create_device(device_data)
        if result:
            st.success(f"Device registered! ID: `{result.get('id', 'N/A')}`")
        else:
            st.error("Registration failed. Hostname may already exist or API is unreachable.")


def _render_devices_table(devices: list):
    """
    Render device inventory as a styled dataframe sorted by hostname.
    """
    rows = []
    for d in sorted(devices, key=lambda x: x.get("hostname", "")):
        rows.append({
            "Hostname": d.get("hostname", ""),
            "IP": d.get("management_ip", ""),
            "Type": d.get("device_type", ""),
            "BGP ASN": d.get("bgp_asn") or "—",
            "OSPF Area": d.get("ospf_area") or "—",
            "OS": d.get("os_version") or "—",
        })

    df = pd.DataFrame(rows)

    def _highlight_type(row):
        device_type = row.get("Type", "")
        if "xr" in device_type or "ios" in device_type:
            return ["background-color: #e8f4ff"] * len(row)
        if "junos" in device_type:
            return ["background-color: #fff8e8"] * len(row)
        return [""] * len(row)

    styled = df.style.apply(_highlight_type, axis=1)
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_device_actions(client: NetDeployClient, devices: list):
    """
    Device detail panel: health check, sync, config inspection.

    Cursor implements:
    - Health check → GET /api/devices/{id}/health → show Healthy/Unhealthy
    - Sync → POST /api/devices/{id}/sync → show result
    - Config history list (last 5 versions)

    [CURSOR IMPLEMENTS all action handlers]
    """
    device_map = {d.get("hostname"): d for d in devices}
    selected_hostname = st.selectbox("Select Device", list(device_map.keys()))
    device = device_map.get(selected_hostname, {})
    if not device:
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔍 Check Health"):
            # [CURSOR IMPLEMENTS: GET /api/devices/{id}/health]
            result = client.check_device_health(device.get("id"))
            if result:
                if result.get("healthy"):
                    st.success("Device is healthy ✅")
                else:
                    st.warning(f"Unhealthy: {result.get('message', 'check failed')}")
            else:
                st.error("Health check failed — device unreachable.")
    with col2:
        if st.button("🔄 Sync Config"):
            # [CURSOR IMPLEMENTS: POST /api/devices/{id}/sync]
            result = client.sync_device(device.get("id"))
            if result:
                st.success("Sync triggered.")
            else:
                st.error("Sync failed.")

    with st.expander(f"Device Info: {selected_hostname}"):
        col_a, col_b = st.columns(2)
        with col_a:
            st.write(f"**ID:** `{device.get('id', 'N/A')}`")
            st.write(f"**Type:** {device.get('device_type', 'N/A')}")
            st.write(f"**SSH Port:** {device.get('ssh_port', 22)}")
        with col_b:
            st.write(f"**BGP ASN:** {device.get('bgp_asn') or 'N/A'}")
            st.write(f"**OSPF Area:** {device.get('ospf_area') or 'N/A'}")
            st.write(f"**OS Version:** {device.get('os_version') or 'N/A'}")

    with st.expander("📜 Configuration History"):
        # [CURSOR IMPLEMENTS: GET /api/configs/history?device_id=...]
        configs = client.get_config_history(device.get("id"))
        if configs:
            for cfg in configs[:5]:
                st.write(
                    f"- `{cfg.get('version', 'N/A')}` — "
                    f"{cfg.get('status', '?')} — "
                    f"by {cfg.get('created_by', '?')} — "
                    f"{cfg.get('deployed_at', '?')}"
                )
        else:
            st.caption("No configuration history.")
