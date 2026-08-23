from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st


API_URL = os.getenv("API_URL", "http://localhost:5000").rstrip("/")
TIMEOUT_SECONDS = 5


def api_request(method: str, path: str, **kwargs: Any) -> Any:
    response = requests.request(
        method,
        f"{API_URL}{path}",
        timeout=TIMEOUT_SECONDS,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="SocialAmbers", page_icon="🔥", layout="centered")
st.title("SocialAmbers")
st.caption("A minimal Streamlit frontend connected to a Flask API.")

try:
    health = api_request("GET", "/api/health")
    st.success(f"Backend connected · {health['service']}")
except (requests.RequestException, KeyError):
    st.error(f"Backend unavailable at {API_URL}")
    st.stop()

with st.form("message_form", clear_on_submit=True):
    text = st.text_area("Message", placeholder="Share a customer signal…")
    submitted = st.form_submit_button("Submit", type="primary")

if submitted:
    try:
        api_request("POST", "/api/messages", json={"text": text})
        st.toast("Message saved")
    except requests.HTTPError as exc:
        detail = exc.response.json().get("error", "Request failed")
        st.warning(detail)
    except requests.RequestException as exc:
        st.error(f"Could not reach the backend: {exc}")

st.subheader("Recent messages")
try:
    data = api_request("GET", "/api/messages")
    messages = data.get("messages", [])
    if not messages:
        st.info("No messages yet.")
    for message in messages:
        with st.container(border=True):
            st.write(message["text"])
            st.caption(message["created_at"])
except requests.RequestException as exc:
    st.error(f"Could not load messages: {exc}")
