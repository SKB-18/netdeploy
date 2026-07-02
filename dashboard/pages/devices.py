"""Devices page — list devices, health status, config drift."""

import streamlit as st
from dashboard.utils.api_client import NetDeployClient


def render(client: NetDeployClient):
    st.title("Devices")

    # CURSOR: Add device registration form in expander
    with st.expander("Register New Device"):
        st.info("CURSOR: Implement device registration form here.")

    st.divider()
    st.subheader("Device Inventory")

    devices = client.list_devices()
    if not devices:
        st.info("No devices registered. Use the form above to add your first device.")
    else:
        # CURSOR: Render table with hostname, IP, type, BGP ASN, health indicator
        st.json(devices)

    st.divider()

    # Device detail / sync
    st.subheader("Device Detail")
    if devices:
        device_hostnames = [d.get("hostname") for d in devices]
        selected = st.selectbox("Select Device", device_hostnames)
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Check Health"):
                st.info("CURSOR: Implement SSH health check call.")
        with col2:
            if st.button("Sync Config"):
                st.info("CURSOR: Implement sync button → POST /api/devices/{id}/sync.")
