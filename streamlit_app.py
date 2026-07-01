"""Streamlit test UI for the customer-support chatbot.

Talks to the running FastAPI server over HTTP (not the graph directly), so it
exercises the real /chat -> pending_approval -> /resume flow. Start the API
first:  uvicorn app.main:app --reload

Then:  streamlit run streamlit_app.py
"""
import json
import uuid
import re
from pathlib import Path
import requests
import streamlit as st

API_URL = "http://localhost:8000"

# Words that suggest a refund/approval-gated action: route these through the
# blocking /chat so a possible pending_approval comes back. Everything else
# streams.
_REFUND_HINTS = ("refund", "money back", "reimburse", "chargeback")

st.set_page_config(page_title="Support Ops Center", page_icon="💬", layout="wide")

# --- CSS Injection for Premium Look ---
st.markdown(
    """
    <style>
    /* Import Outfit and Inter fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@500;600;700&display=swap');

    /* Apply fonts globally */
    html, body, [class*="css"], .stText, .stMarkdown, p, li, span, div {
        font-family: 'Inter', sans-serif !important;
    }
    h1, h2, h3, h4, h5, h6, strong {
        font-family: 'Outfit', sans-serif !important;
    }

    /* Hide standard Streamlit header and footer */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Tighten container padding */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 1.5rem !important;
        max-width: 95% !important;
    }

    /* Section headers */
    .section-header {
        font-family: 'Outfit', sans-serif !important;
        font-size: 1.5rem !important;
        font-weight: 600 !important;
        color: #f8fafc !important;
        margin-bottom: 1rem !important;
        padding-bottom: 0.5rem !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
    }

    /* Scrollable chat container styling */
    .stChatMessageContainer {
        height: 520px !important;
        overflow-y: auto !important;
        padding-right: 10px !important;
    }

    /* Style the default chat message blocks to look like premium speech bubbles */
    div[data-testid="stChatMessage"] {
        background-color: rgba(30, 41, 59, 0.45) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 16px !important;
        margin-bottom: 0.75rem !important;
        padding: 12px 16px !important;
        transition: all 0.2s ease-in-out;
    }
    
    div[data-testid="stChatMessage"]:hover {
        background-color: rgba(30, 41, 59, 0.6) !important;
        border-color: rgba(99, 102, 241, 0.2) !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
    }

    /* Ops cards */
    .ops-card {
        background: rgba(15, 23, 42, 0.3) !important;
        border: 1px solid rgba(255, 255, 255, 0.05) !important;
        border-radius: 16px !important;
        padding: 16px !important;
        margin-bottom: 12px !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
        backdrop-filter: blur(10px) !important;
    }

    .ops-card.pending {
        border: 1px solid #fbbf24 !important;
        background: rgba(245, 158, 11, 0.05) !important;
        box-shadow: 0 0 20px rgba(245, 158, 11, 0.15) !important;
        animation: pulseBorder 2s infinite;
    }
    @keyframes pulseBorder {
        0% { border-color: rgba(245, 158, 11, 0.4); }
        50% { border-color: rgba(245, 158, 11, 1); }
        100% { border-color: rgba(245, 158, 11, 0.4); }
    }

    /* Telemetry terminal styling */
    .telemetry-terminal {
        background-color: #05070f !important;
        border: 1px solid rgba(99, 102, 241, 0.2) !important;
        border-radius: 12px !important;
        padding: 14px !important;
        font-family: 'Courier New', Courier, monospace !important;
        font-size: 0.85rem !important;
        color: #67e8f9 !important;
        height: 180px !important;
        overflow-y: auto !important;
        white-space: pre-wrap !important;
        box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.5) !important;
    }

    /* Status badges */
    .badge {
        padding: 4px 10px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        display: inline-block !important;
        letter-spacing: 0.05em !important;
    }
    .badge-shipped { background-color: rgba(59, 130, 246, 0.15) !important; color: #60a5fa !important; border: 1px solid rgba(59, 130, 246, 0.3) !important; }
    .badge-processing { background-color: rgba(245, 158, 11, 0.15) !important; color: #fbbf24 !important; border: 1px solid rgba(245, 158, 11, 0.3) !important; }
    .badge-delivered { background-color: rgba(16, 185, 129, 0.15) !important; color: #34d399 !important; border: 1px solid rgba(16, 185, 129, 0.3) !important; }
    .badge-refunded { background-color: rgba(139, 92, 246, 0.15) !important; color: #c084fc !important; border: 1px solid rgba(139, 92, 246, 0.3) !important; }
    .badge-cancelled { background-color: rgba(239, 68, 68, 0.15) !important; color: #f87171 !important; border: 1px solid rgba(239, 68, 68, 0.3) !important; }
    .badge-return_initiated { background-color: rgba(236, 72, 153, 0.15) !important; color: #f472b6 !important; border: 1px solid rgba(236, 72, 153, 0.3) !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- session state ---------------------------------------------------------
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = None
if "trace" not in st.session_state:
    st.session_state.trace = None
if "orders" not in st.session_state:
    # Initialize orders in session state from file
    try:
        orders_path = Path(__file__).resolve().parent / "app" / "data" / "orders.json"
        if orders_path.exists():
            st.session_state.orders = json.loads(orders_path.read_text())
        else:
            st.session_state.orders = []
    except Exception:
        st.session_state.orders = []


def post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API_URL}{path}", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get(path: str) -> dict:
    resp = requests.get(f"{API_URL}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def stream_chat(payload: dict):
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


def sync_orders_from_reply(reply: str, trace_text: str = ""):
    """Sync the mock orders database in UI state with chatbot interactions."""
    reply_lower = reply.lower()
    trace_lower = (trace_text or "").lower()
    
    # 1. Order Cancelled
    if "cancel" in reply_lower or "cancel" in trace_lower:
        for order in st.session_state.orders:
            order_id = order['order_id']
            if f"order {order_id}" in reply_lower or f"order #{order_id}" in reply_lower or f"order_id='{order_id}'" in trace_lower or f"order_id=\"{order_id}\"" in trace_lower:
                if "cancelled" in reply_lower or "cancelled" in trace_lower or "cancel" in reply_lower:
                    order["status"] = "cancelled"

    # 2. Return Initiated
    if "return" in reply_lower or "return" in trace_lower:
        for order in st.session_state.orders:
            order_id = order['order_id']
            if f"order {order_id}" in reply_lower or f"order #{order_id}" in reply_lower or f"order_id='{order_id}'" in trace_lower or f"order_id=\"{order_id}\"" in trace_lower:
                if "initiated" in reply_lower or "return" in reply_lower:
                    order["status"] = "return_initiated"

    # 3. Address Modified
    if "address" in reply_lower or "address" in trace_lower:
        for order in st.session_state.orders:
            order_id = order['order_id']
            if f"order {order_id}" in reply_lower or f"order #{order_id}" in reply_lower or f"order_id='{order_id}'" in trace_lower or f"order_id=\"{order_id}\"" in trace_lower:
                if "change" in reply_lower or "update" in reply_lower or "modify" in reply_lower:
                    match = re.search(r'(?:to|address is now)\s+([^.\n]+)', reply)
                    if match:
                        order["shipping_address"] = match.group(1).strip()
                    else:
                        order["shipping_address"] = "Updated Address"

    # 4. Low-Value / Auto Refund
    if "refund" in reply_lower or "refund" in trace_lower:
        for order in st.session_state.orders:
            order_id = order['order_id']
            if f"order {order_id}" in reply_lower or f"order #{order_id}" in reply_lower or f"order_id='{order_id}'" in trace_lower or f"order_id=\"{order_id}\"" in trace_lower:
                if "refunded" in reply_lower or "refunded" in trace_lower or "processed" in reply_lower:
                    order["status"] = "refunded"
                    # Try to extract the refund amount
                    amount_match = re.search(r'\$(\d+(?:\.\d{2})?)', reply)
                    if amount_match:
                        order["refunded_amount"] = float(amount_match.group(1))
                    else:
                        order["refunded_amount"] = order.get("total", 0.0)


def handle_result(result: dict) -> None:
    """Turn a /chat or /resume response into UI state."""
    status = result.get("status")
    trace_text = result.get("trace", "")
    st.session_state.trace = trace_text
    
    if status == "pending_approval":
        st.session_state.pending = result["pending_action"]
    else:
        st.session_state.pending = None
        reply = result.get("reply", "")
        st.session_state.messages.append({"role": "assistant", "content": reply})
        sync_orders_from_reply(reply, trace_text)


# --- sidebar ---------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 20px;">
            <span style="font-size: 3rem;">💬</span>
            <h2 style="font-family: Outfit; font-weight: 700; margin: 0; background: linear-gradient(135deg, #6366F1 0%, #A855F7 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Support Ops</h2>
            <p style="color: #94a3b8; font-size: 0.9rem;">Customer Chat & HITL Dashboard</p>
        </div>
        """, 
        unsafe_allow_html=True
    )
    
    st.subheader("Session Control")
    st.caption(f"**thread_id:** `{st.session_state.thread_id}`")
    if st.button("New Conversation", type="primary", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.pending = None
        st.session_state.trace = None
        # Reset local orders from file
        try:
            orders_path = Path(__file__).resolve().parent / "app" / "data" / "orders.json"
            if orders_path.exists():
                st.session_state.orders = json.loads(orders_path.read_text())
        except Exception:
            pass
        st.rerun()
        
    st.divider()
    
    st.markdown(
        """
        ### 💡 Sample Scenarios
        Copy-paste these in the chat to test:
        1. **FAQ Retrieval (RAG)**
           - *Query:* "What is your return policy?"
        2. **Order Tracking**
           - *Query:* "Where is my order #1001?"
        3. **Low-Value Refund (Auto)**
           - *Query:* "Refund order 1001 for $20"
        4. **High-Value Refund (HITL)**
           - *Query:* "Refund order 1003 for $120 because it arrived damaged"
        5. **Order Modification**
           - *Query:* "Cancel my order 1002"
        """,
        unsafe_allow_html=True
    )

# --- main layout -----------------------------------------------------------
st.markdown('<h1 class="app-title">💬 Customer Support Operations Center</h1>', unsafe_allow_html=True)
st.markdown('<p style="color: #94a3b8; margin-top: -10px; margin-bottom: 20px; font-size: 1.05rem;">Simulating customer interactions & human-in-the-loop overrides in real-time.</p>', unsafe_allow_html=True)

# Split page into columns
chat_col, ops_col = st.columns([5, 4])

# --- left column: support chat ---------------------------------------------
with chat_col:
    st.markdown('<h2 class="section-header">💬 Customer Support Chat</h2>', unsafe_allow_html=True)
    
    # Scrollable chat message viewport
    chat_container = st.container(height=520)
    with chat_container:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

# --- right column: operations center ---------------------------------------
with ops_col:
    st.markdown('<h2 class="section-header">🛡️ Operations Control</h2>', unsafe_allow_html=True)
    
    # 1. HITL Pending Card
    if st.session_state.pending:
        action = st.session_state.pending
        st.markdown(
            f"""
            <div class="ops-card pending">
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 1.2rem; margin-right: 8px;">⚠️</span>
                    <strong style="color: #fbbf24; font-family: Outfit; font-size: 1.1rem;">Refund Approval Required</strong>
                </div>
                <div style="margin-top: 10px; font-size: 0.95rem; color: #e2e8f0; line-height: 1.6;">
                    <p style="margin: 4px 0;"><strong>Action:</strong> {action.get('action')}</p>
                    <p style="margin: 4px 0;"><strong>Order ID:</strong> #{action.get('order_id')}</p>
                    <p style="margin: 4px 0;"><strong>Amount:</strong> <span style="color: #f43f5e; font-weight: 600;">${action.get('amount')}</span></p>
                    <p style="margin: 10px 0 4px 0; padding-top: 8px; border-top: 1px solid rgba(255,255,255,0.1);">
                        <strong>Reason:</strong> <em>"{action.get('reason', '')}"</em>
                    </p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        col1, col2 = st.columns(2)
        if col1.button("Approve Refund", type="primary", use_container_width=True):
            result = post("/resume", {"thread_id": st.session_state.thread_id, "approved": True})
            # Explicitly sync approved refund locally
            order_id = action.get("order_id")
            amount = action.get("amount")
            for order in st.session_state.orders:
                if str(order["order_id"]) == str(order_id):
                    order["status"] = "refunded"
                    order["refunded_amount"] = amount
            handle_result(result)
            st.rerun()
            
        if col2.button("Deny Refund", use_container_width=True):
            result = post("/resume", {"thread_id": st.session_state.thread_id, "approved": False})
            handle_result(result)
            st.rerun()
    else:
        st.markdown(
            """
            <div class="ops-card" style="border-left: 4px solid #10b981;">
                <div style="display: flex; align-items: center;">
                    <span style="font-size: 1.2rem; margin-right: 8px;">💚</span>
                    <strong style="color: #34d399; font-family: Outfit; font-size: 1rem;">System Status: Active</strong>
                </div>
                <p style="margin: 6px 0 0 0; font-size: 0.85rem; color: #94a3b8;">
                    No pending actions require human approval at this checkpoint.
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

    # 2. Inbound Channel Approvals (WhatsApp / M13).
    # The card above handles THIS dashboard's own simulated chat (one thread_id).
    # WhatsApp refunds arrive on a DIFFERENT thread (wa:<phone>) from a separate
    # process — the customer is on their phone, not here. We poll the API's /pending
    # queue to surface those, and approve/deny drives the same /resume; the API then
    # pushes the outcome back to the customer over WhatsApp.
    st.divider()
    st.markdown('<h3 style="font-family: Outfit; font-weight: 600; font-size: 1.1rem; color: #f1f5f9;">📲 Inbound Channel Approvals</h3>', unsafe_allow_html=True)
    try:
        inbound = get("/pending").get("pending", [])
    except requests.RequestException:
        inbound = []
        st.caption("API unreachable — can't load the approval queue.")

    if not inbound:
        st.caption("No WhatsApp refunds awaiting approval.")
    for item in inbound:
        tid = item["thread_id"]
        action = item["action"]
        phone = tid.split(":", 1)[1] if ":" in tid else tid
        st.markdown(
            f"""
            <div class="ops-card pending">
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 1.2rem; margin-right: 8px;">📲</span>
                    <strong style="color: #fbbf24; font-family: Outfit; font-size: 1.05rem;">WhatsApp Refund · +{phone}</strong>
                </div>
                <div style="margin-top: 8px; font-size: 0.92rem; color: #e2e8f0; line-height: 1.6;">
                    <p style="margin: 4px 0;"><strong>Order ID:</strong> #{action.get('order_id')}</p>
                    <p style="margin: 4px 0;"><strong>Amount:</strong> <span style="color: #f43f5e; font-weight: 600;">${action.get('amount')}</span></p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        c1, c2 = st.columns(2)
        if c1.button("Approve", type="primary", use_container_width=True, key=f"wa_ok_{tid}"):
            post("/resume", {"thread_id": tid, "approved": True})
            for order in st.session_state.orders:
                if str(order["order_id"]) == str(action.get("order_id")):
                    order["status"] = "refunded"
                    order["refunded_amount"] = action.get("amount")
            st.rerun()
        if c2.button("Deny", use_container_width=True, key=f"wa_no_{tid}"):
            post("/resume", {"thread_id": tid, "approved": False})
            st.rerun()

    # 2. Active Orders Grid
    st.markdown('<h3 style="font-family: Outfit; font-weight: 600; margin-top: 1rem; font-size: 1.1rem; color: #f1f5f9;">📦 Active Orders Database</h3>', unsafe_allow_html=True)
    for order in st.session_state.orders:
        status = order.get("status", "").lower()
        badge_class = f"badge-{status}"
        items_str = ", ".join(order.get("items", []))
        
        refund_info = ""
        if status == "refunded" and "refunded_amount" in order:
            refund_info = f'<span style="color: #c084fc; font-weight: 600; margin-left: 10px;">(Refunded: ${order["refunded_amount"]})</span>'
            
        # Extract modified address if it exists
        address_info = ""
        if "shipping_address" in order:
            address_info = f' | <strong>Address:</strong> {order["shipping_address"]}'

        st.markdown(
            f"""
            <div class="ops-card" style="padding: 12px 14px; margin-bottom: 8px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-family: Outfit; font-weight: 600; font-size: 0.95rem; color: #f8fafc;">
                        Order #{order.get('order_id')} <span style="font-size: 0.8rem; color: #94a3b8; font-weight: normal; margin-left: 8px;">{order.get('customer')}</span>
                    </span>
                    <span class="badge {badge_class}">{status.replace('_', ' ')}</span>
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: #cbd5e1; line-height: 1.4;">
                    <p style="margin: 2px 0;"><strong>Items:</strong> {items_str}</p>
                    <p style="margin: 2px 0;"><strong>Total:</strong> ${order.get('total'):.2f} {refund_info}</p>
                    <p style="margin: 2px 0; color: #94a3b8; font-size: 0.78rem;">
                        <strong>ETA:</strong> {order.get('eta')} | <strong>Tracking:</strong> {order.get('tracking_number') or 'N/A'}{address_info}
                    </p>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # 3. Agent Trace Telemetry
    st.markdown('<h3 style="font-family: Outfit; font-weight: 600; margin-top: 1rem; font-size: 1.1rem; color: #f1f5f9;">📊 Supervisor Telemetry</h3>', unsafe_allow_html=True)
    if st.session_state.trace:
        st.markdown(
            f"""
            <div class="telemetry-terminal">
{st.session_state.trace}
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            """
            <div class="telemetry-terminal" style="color: #64748b; font-style: italic; display: flex; align-items: center; justify-content: center; height: 180px;">
Waiting for agent execution trace...
            </div>
            """,
            unsafe_allow_html=True
        )

# --- chat input ------------------------------------------------------------
prompt = st.chat_input(
    "Ask about an order, refund, return policy...",
    disabled=st.session_state.pending is not None,
)
if prompt:
    # Immediately render user message inside the container
    with chat_container:
        with st.chat_message("user"):
            st.markdown(prompt)
            
    st.session_state.messages.append({"role": "user", "content": prompt})

    is_refund = any(h in prompt.lower() for h in _REFUND_HINTS)
    try:
        if is_refund:
            # Blocking path: may return a pending_approval the HITL card renders.
            result = post("/chat", {"thread_id": st.session_state.thread_id, "message": prompt})
            handle_result(result)
        else:
            # Streaming path: render tokens into a placeholder as they arrive.
            with chat_container:
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
            sync_orders_from_reply(acc)
    except requests.RequestException as e:
        error_msg = f"Request failed: {e}. Is the API running on {API_URL}?"
        with chat_container:
            with st.chat_message("assistant"):
                st.markdown(error_msg)
        st.session_state.messages.append({"role": "assistant", "content": error_msg})
    st.rerun()
