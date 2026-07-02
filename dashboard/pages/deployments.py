"""Deployments page — shows recent deployments, status, logs."""

import streamlit as st
from dashboard.utils.api_client import NetDeployClient


def render(client: NetDeployClient):
    st.title("Deployments")

    # Metrics row
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Active Deployments", "—")  # CURSOR: fetch from API
    with col2:
        st.metric("Success Rate", "—")         # CURSOR: calculate
    with col3:
        st.metric("Devices Managed", "—")      # CURSOR: count devices

    st.divider()

    # Recent deployments table
    st.subheader("Recent Deployments")
    deployments = client.list_deployments(limit=20)

    if not deployments:
        st.info("No deployments yet. Deploy a configuration to get started.")
    else:
        # CURSOR: Render as st.dataframe with status color coding
        st.json(deployments)

    st.divider()

    # Deployment detail
    st.subheader("Deployment Detail")
    deployment_ids = [d.get("id") for d in deployments]
    if deployment_ids:
        selected_id = st.selectbox("Select Deployment", deployment_ids)
        if selected_id:
            detail = client.get_deployment(selected_id)
            # CURSOR: Show logs, status timeline, affected devices
            if detail:
                st.json(detail)
            else:
                st.warning("Could not load deployment detail.")
    else:
        st.caption("No deployments to inspect.")
