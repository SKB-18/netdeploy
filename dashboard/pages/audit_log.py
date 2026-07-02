"""Audit Log page — searchable compliance trail."""

import streamlit as st
from dashboard.utils.api_client import NetDeployClient


def render(client: NetDeployClient):
    st.title("Audit Log")

    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        user_filter = st.text_input("Filter by User")
    with col2:
        action_filter = st.selectbox(
            "Filter by Action",
            ["", "CREATE", "DEPLOY", "ROLLBACK", "SYNC", "DELETE"],
        )
    with col3:
        resource_filter = st.selectbox(
            "Filter by Resource",
            ["", "Device", "Configuration", "Deployment"],
        )

    limit = st.slider("Max entries", 10, 500, 100)

    st.divider()

    logs = client.get_audit_log(
        user=user_filter or None,
        action=action_filter or None,
        limit=limit,
    )

    if not logs:
        st.info("No audit log entries found.")
    else:
        # CURSOR: Render as styled dataframe with timestamp, user, action, resource
        st.write(f"Showing {len(logs)} entries")
        st.json(logs)

        # CURSOR: Add CSV export button
        if st.button("Export CSV"):
            st.info("CURSOR: Implement CSV export here.")
