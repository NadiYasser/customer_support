"""Streamlit test UI for the customer-support chatbot.

Talks to the running FastAPI server over HTTP (not the graph directly), so it
exercises the real /chat -> pending_approval -> /resume flow. Start the API
first:  uvicorn app.main:app --reload

Then:  streamlit run streamlit_app.py

M9: normal answers are streamed token-by-token from /chat/stream and rendered
incrementally. Refund-style messages still use the blocking /chat call, because
only that path returns the pending_approval payload the HITL card needs — an
interrupt() can't be expressed mid-stream (see app/main.py /chat/stream scope).
"""
import json
import uuid

import requests
import streamlit as st

API_URL = "http://localhost:8000"

# Words that suggest a refund/approval-gated action: route these through the
# blocking /chat so a possible pending_approval comes back. Everything else
# streams. This is a coarse client-side hint, not the real router — the server's
# supervisor still decides the actual agent for the /chat path.
_REFUND_HINTS = ("refund", "money back", "reimburse", "chargeback")

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


def stream_chat(payload: dict):
    """Yield answer-text deltas from /chat/stream as they arrive.

    stream=True keeps the socket open; iter_lines() hands us each SSE line as the
    server flushes it. We parse the "data: {json}" frames, yielding each delta and
    stopping on the done event.
    """
    with requests.post(
        f"{API_URL}/chat/stream", json=payload, stream=True, timeout=120
    ) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            if not raw or not raw.startswith(b"data: "):
                continue
            event = json.loads(raw[len(b"data: "):])
            if event.get("done"):
                break
            if "error" in event:
                yield f"\n\n_{event['error']}_"
                break
            yield event.get("delta", "")


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
    with st.chat_message("user"):
        st.markdown(prompt)

    is_refund = any(h in prompt.lower() for h in _REFUND_HINTS)
    try:
        if is_refund:
            # Blocking path: may return a pending_approval the HITL card renders.
            result = post("/chat", {"thread_id": st.session_state.thread_id, "message": prompt})
            handle_result(result)
        else:
            # Streaming path: render tokens into a placeholder as they arrive.
            with st.chat_message("assistant"):
                placeholder = st.empty()
                acc = ""
                for delta in stream_chat(
                    {"thread_id": st.session_state.thread_id, "message": prompt}
                ):
                    acc += delta
                    placeholder.markdown(acc + "▌")  # cursor shows it's still typing
                placeholder.markdown(acc)
            st.session_state.messages.append({"role": "assistant", "content": acc})
    except requests.RequestException as e:
        st.session_state.messages.append(
            {"role": "assistant", "content": f"Request failed: {e}. Is the API running on {API_URL}?"}
        )
    st.rerun()
