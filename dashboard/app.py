"""NetDeploy Streamlit dashboard — main entry point."""

import streamlit as st

st.set_page_config(
    page_title="NetDeploy",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dashboard.utils.api_client import NetDeployClient
from dashboard.pages import deployments as deployments_page
from dashboard.pages import devices as devices_page
from dashboard.pages import audit_log as audit_log_page
import os

API_URL = os.getenv("NETDEPLOY_API_URL", "http://localhost:8000")
client = NetDeployClient(api_url=API_URL)

# Sidebar
with st.sidebar:
    st.title("🌐 NetDeploy")
    st.caption("Automated Network Provisioning")
    st.divider()
    page = st.radio(
        "Navigate",
        ["Deployments", "Devices", "Audit Log", "Settings"],
        label_visibility="collapsed",
    )
    st.divider()

    # API health indicator
    healthy = client.health_check()
    if healthy:
        st.success("API: Connected", icon="✅")
    else:
        st.error("API: Unreachable", icon="❌")

# Route to pages
if page == "Deployments":
    deployments_page.render(client)
elif page == "Devices":
    devices_page.render(client)
elif page == "Audit Log":
    audit_log_page.render(client)
elif page == "Settings":
    st.title("Settings")
    st.text_input("API URL", value=API_URL, disabled=True)
    st.info("Configure via NETDEPLOY_API_URL environment variable.")
