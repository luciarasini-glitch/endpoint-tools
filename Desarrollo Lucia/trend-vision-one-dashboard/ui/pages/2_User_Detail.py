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


def fetch_users() -> list[dict]:
    response = requests.get(f"{BACKEND_URL}/api/v1/users", timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_detail(user_id: str) -> dict:
    response = requests.get(f"{BACKEND_URL}/api/v1/users/{user_id}", timeout=20)
    response.raise_for_status()
    return response.json()


st.title("User Detail")

try:
    user_rows = fetch_users()
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not load users: {exc}")
    st.stop()

user_map = {row["display_name"]: row["id"] for row in user_rows}
selected_label = st.selectbox("User", options=list(user_map.keys())) if user_map else None

if not selected_label:
    st.info("No users available.")
    st.stop()

user_id = user_map[selected_label]

try:
    detail = fetch_detail(user_id)
except Exception as exc:  # noqa: BLE001
    st.error(f"Could not load user detail: {exc}")
    st.stop()

snapshot = detail["snapshot"]
user = next(user for user in snapshot["users"] if user["id"] == user_id)
devices = [device for device in snapshot["devices"] if device["id"] in user["device_ids"]]
signals = [signal for signal in snapshot["signals"] if signal["id"] in user["signal_ids"]]
coverage = [item for item in snapshot["coverage"] if item["id"] in user["coverage_ids"]]

st.subheader("Identity")
st.json(user)
if user.get("source") == "endpoint_inventory":
    st.caption("This user was inferred from Endpoint Inventory, using fields like lastLoggedOnUser.")

st.subheader("Devices")
if devices:
    st.dataframe(devices, use_container_width=True)
else:
    st.info("No devices associated with this user.")

st.subheader("Signals")
if signals:
    st.dataframe(signals, use_container_width=True)
else:
    st.info("No signals associated with this user.")

st.subheader("Coverage / tools")
if coverage:
    st.dataframe(coverage, use_container_width=True)
else:
    st.info("No coverage data associated with this user.")

st.subheader("Correlation links")
links = [link for link in snapshot["correlations"] if link["user_id"] == user_id]
if links:
    st.dataframe(links, use_container_width=True)
else:
    st.info("No correlation links available for this user.")
