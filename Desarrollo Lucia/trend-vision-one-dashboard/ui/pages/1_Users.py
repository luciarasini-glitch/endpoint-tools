from __future__ import annotations

import sys
from pathlib import Path

import requests
import streamlit as st

try:
    from ui.backend import BACKEND_URL
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend import BACKEND_URL


def fetch_users(search: str, risk_level: str) -> list[dict]:
    response = requests.get(
        f"{BACKEND_URL}/api/v1/users",
        params={"search": search, "risk_level": risk_level},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


st.title("Users")
search = st.text_input("Search by name or email")
risk_level = st.selectbox("Risk level", options=["", "critical", "high", "medium", "low", "unknown"])

try:
    users = fetch_users(search, risk_level)
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not load users: {exc}")
    st.stop()

if not users:
    st.info("No users matched the current filters.")
else:
    st.dataframe(users, use_container_width=True)
    inferred_count = sum(1 for user in users if user.get("source") == "endpoint_inventory")
    if inferred_count:
        st.caption(
            f"{inferred_count} users were inferred from Endpoint Inventory because the Accounts endpoint is not fully integrated yet."
        )
    else:
        st.caption("Open the User Detail page and select a user to navigate the graph.")
