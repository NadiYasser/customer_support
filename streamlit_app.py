"""Streamlit test UI for the customer-support chatbot.

Talks to the running FastAPI server over HTTP (not the graph directly), so it
exercises the real /chat -> pending_approval -> /resume flow. Start the API
first:  uvicorn app.main:app --reload

Then:  streamlit run streamlit_app.py
"""
import uuid

import requests
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Support Chatbot", page_icon="💬")

# --- session state ---------------------------------------------------------
# thread_id keys the conversation on the server's checkpointer; one per session.
# messages is purely for display. pending holds a refund proposal returned by
# /chat when the graph paused at interrupt() — while it's set, the chat input is
# locked because the same thread can't take a new turn until it's resolved.
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None


def post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API_URL}{path}", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def handle_result(result: dict) -> None:
    """Turn a /chat or /resume response into UI state."""
    status = result.get("status")
    if status == "pending_approval":
        st.session_state.pending = result["pending_action"]
    else:
        st.session_state.pending = None
        st.session_state.messages.append({"role": "assistant", "content": result["reply"]})


# --- sidebar ---------------------------------------------------------------
with st.sidebar:
    st.subheader("Session")
    st.caption(f"thread_id: {st.session_state.thread_id}")
    if st.button("New conversation"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.pending = None
        st.rerun()
    st.divider()
    st.caption("Sample orders: 1001 (shipped), 1002 (processing), 1003 (delivered, $120)")

# --- chat history ----------------------------------------------------------
st.title("💬 Support Chatbot")
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- pending approval card -------------------------------------------------
# Rendered when the graph interrupted on a high-value refund. Approve/Deny call
# /resume on the same thread_id, which continues the paused graph.
if st.session_state.pending:
    action = st.session_state.pending
    with st.chat_message("assistant"):
        st.warning("Refund needs human approval")
        st.markdown(
            f"- **Action:** {action.get('action')}\n"
            f"- **Order:** {action.get('order_id')}\n"
            f"- **Amount:** {action.get('amount')}\n\n"
            f"{action.get('reason', '')}"
        )
        col1, col2 = st.columns(2)
        if col1.button("Approve", type="primary"):
            result = post("/resume", {"thread_id": st.session_state.thread_id, "approved": True})
            handle_result(result)
            st.rerun()
        if col2.button("Deny"):
            result = post("/resume", {"thread_id": st.session_state.thread_id, "approved": False})
            handle_result(result)
            st.rerun()

# --- chat input ------------------------------------------------------------
prompt = st.chat_input(
    "Ask about an order, refund, return policy...",
    disabled=st.session_state.pending is not None,
)
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        result = post("/chat", {"thread_id": st.session_state.thread_id, "message": prompt})
        handle_result(result)
    except requests.RequestException as e:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"Request failed: {e}. Is the API running on {API_URL}?"}
        )
    st.rerun()
