"""Streamlit ADMIN CONSOLE for the WhatsApp customer-support agent (M14).

This is an operator tool, not a customer chat. It talks to the running FastAPI
server over HTTP (never the graph directly) and lets a human admin:

  - MONITOR every live WhatsApp conversation (wa:<phone> threads),
  - APPROVE/deny refunds paused at the HITL gate (the /pending queue),
  - TAKE OVER a conversation (mute the agent) and reply to the customer by hand,
    then release it back to the agent.

Start the API first:  uvicorn app.main:app --reload
Then:  streamlit run streamlit_app.py

No auth: this is a local-only learning build. If it were ever exposed, the admin
endpoints (which can send messages and toggle the agent) would need protecting.
"""
import json
from pathlib import Path
import requests
import streamlit as st

API_URL = "http://localhost:8000"
REFRESH_SECONDS = 4  # how often the console polls the API for new activity

st.set_page_config(page_title="Support Admin Console", page_icon="🛡️", layout="wide")

# --- CSS (unchanged premium look) ------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@500;600;700&display=swap');
    html, body, [class*="css"], .stText, .stMarkdown, p, li, span, div {
        font-family: 'Inter', sans-serif !important;
    }
    h1, h2, h3, h4, h5, h6, strong { font-family: 'Outfit', sans-serif !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    .block-container { padding-top: 1.5rem !important; padding-bottom: 1.5rem !important; max-width: 95% !important; }
    .section-header {
        font-family: 'Outfit', sans-serif !important; font-size: 1.5rem !important;
        font-weight: 600 !important; color: #f8fafc !important; margin-bottom: 1rem !important;
        padding-bottom: 0.5rem !important; border-bottom: 1px solid rgba(255,255,255,0.05) !important;
    }
    div[data-testid="stChatMessage"] {
        background-color: rgba(30, 41, 59, 0.45) !important; border: 1px solid rgba(255,255,255,0.05) !important;
        border-radius: 16px !important; margin-bottom: 0.75rem !important; padding: 12px 16px !important;
    }
    .ops-card {
        background: rgba(15, 23, 42, 0.3) !important; border: 1px solid rgba(255,255,255,0.05) !important;
        border-radius: 16px !important; padding: 16px !important; margin-bottom: 12px !important;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1) !important; backdrop-filter: blur(10px) !important;
    }
    .ops-card.pending {
        border: 1px solid #fbbf24 !important; background: rgba(245, 158, 11, 0.05) !important;
        box-shadow: 0 0 20px rgba(245, 158, 11, 0.15) !important; animation: pulseBorder 2s infinite;
    }
    @keyframes pulseBorder {
        0% { border-color: rgba(245, 158, 11, 0.4); } 50% { border-color: rgba(245, 158, 11, 1); }
        100% { border-color: rgba(245, 158, 11, 0.4); }
    }
    .badge {
        padding: 4px 10px !important; border-radius: 12px !important; font-size: 0.72rem !important;
        font-weight: 600 !important; text-transform: uppercase !important; display: inline-block !important;
        letter-spacing: 0.05em !important;
    }
    .badge-shipped { background-color: rgba(59,130,246,0.15) !important; color: #60a5fa !important; border: 1px solid rgba(59,130,246,0.3) !important; }
    .badge-processing { background-color: rgba(245,158,11,0.15) !important; color: #fbbf24 !important; border: 1px solid rgba(245,158,11,0.3) !important; }
    .badge-delivered { background-color: rgba(16,185,129,0.15) !important; color: #34d399 !important; border: 1px solid rgba(16,185,129,0.3) !important; }
    .badge-refunded { background-color: rgba(139,92,246,0.15) !important; color: #c084fc !important; border: 1px solid rgba(139,92,246,0.3) !important; }
    .badge-cancelled { background-color: rgba(239,68,68,0.15) !important; color: #f87171 !important; border: 1px solid rgba(239,68,68,0.3) !important; }
    .badge-return_initiated { background-color: rgba(236,72,153,0.15) !important; color: #f472b6 !important; border: 1px solid rgba(236,72,153,0.3) !important; }
    .badge-live { background-color: rgba(16,185,129,0.15) !important; color: #34d399 !important; border: 1px solid rgba(16,185,129,0.3) !important; }
    .badge-takeover { background-color: rgba(245,158,11,0.15) !important; color: #fbbf24 !important; border: 1px solid rgba(245,158,11,0.3) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- HTTP helpers -----------------------------------------------------------
def get(path: str) -> dict:
    resp = requests.get(f"{API_URL}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API_URL}{path}", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def load_orders() -> list:
    try:
        p = Path(__file__).resolve().parent / "app" / "data" / "orders.json"
        return json.loads(p.read_text()) if p.exists() else []
    except Exception:
        return []


# --- session state ----------------------------------------------------------
if "selected" not in st.session_state:
    st.session_state.selected = None  # currently opened thread_id


# --- sidebar ----------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="text-align: center; margin-bottom: 20px;">
            <span style="font-size: 3rem;">🛡️</span>
            <h2 style="font-family: Outfit; font-weight: 700; margin: 0; background: linear-gradient(135deg, #6366F1 0%, #A855F7 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">Admin Console</h2>
            <p style="color: #94a3b8; font-size: 0.9rem;">WhatsApp Support · Monitor & Intervene</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"Polling the API every {REFRESH_SECONDS}s for new activity.")
    st.divider()
    st.markdown(
        """
        ### How takeover works
        - **Take over** mutes the agent for that customer; you reply by hand.
        - The agent stays silent (but still records incoming messages) until you
          **release** it.
        - Refund approvals appear on the right whenever a customer asks for a
          high-value refund over WhatsApp.
        """
    )


st.markdown('<h1>🛡️ Support Admin Console</h1>', unsafe_allow_html=True)
st.markdown(
    '<p style="color:#94a3b8; margin-top:-10px; margin-bottom:20px; font-size:1.05rem;">'
    'Live WhatsApp conversations, human-in-the-loop approvals, and manual takeover.</p>',
    unsafe_allow_html=True,
)


# --- the whole console body auto-refreshes on a timer -----------------------
@st.fragment(run_every=REFRESH_SECONDS)
def console():
    list_col, chat_col, ops_col = st.columns([2, 5, 3])

    # fetch fresh data each run
    try:
        threads = get("/admin/threads").get("threads", [])
    except requests.RequestException:
        st.error(f"API unreachable at {API_URL}. Is the server running?")
        return

    # default selection = first thread
    if st.session_state.selected is None and threads:
        st.session_state.selected = threads[0]["thread_id"]

    # ---- LEFT: conversation list ----
    with list_col:
        st.markdown('<h2 class="section-header">💬 Conversations</h2>', unsafe_allow_html=True)
        if not threads:
            st.caption("No WhatsApp conversations yet.")
        for t in threads:
            tag = "TAKEOVER" if t["muted"] else "LIVE"
            badge = "badge-takeover" if t["muted"] else "badge-live"
            label = f"+{t['phone']}  ·  {t['count']} msgs"
            if st.button(label, key=f"sel_{t['thread_id']}", use_container_width=True):
                st.session_state.selected = t["thread_id"]
                st.rerun(scope="fragment")
            st.markdown(
                f'<div style="margin:-6px 0 10px 4px;"><span class="badge {badge}">{tag}</span>'
                f'<span style="color:#94a3b8; font-size:0.78rem; margin-left:8px;">{t["last"][:38]}</span></div>',
                unsafe_allow_html=True,
            )

    # ---- CENTER: selected transcript + takeover + reply ----
    with chat_col:
        sel = st.session_state.selected
        if not sel:
            st.markdown('<h2 class="section-header">Transcript</h2>', unsafe_allow_html=True)
            st.caption("Select a conversation on the left.")
        else:
            detail = get(f"/admin/threads/{sel}")
            muted = detail["muted"]
            head = f'👤 +{detail["phone"]}'
            state_badge = "badge-takeover" if muted else "badge-live"
            state_txt = "TAKEOVER — you are replying" if muted else "LIVE — agent is replying"
            st.markdown(
                f'<h2 class="section-header">{head} '
                f'<span class="badge {state_badge}" style="font-size:0.6rem; vertical-align:middle;">{state_txt}</span></h2>',
                unsafe_allow_html=True,
            )

            # takeover toggle
            tcol1, tcol2 = st.columns([1, 3])
            if muted:
                if tcol1.button("↩️ Release to agent", use_container_width=True, key="release"):
                    post("/admin/mute", {"thread_id": sel, "muted": False})
                    st.rerun(scope="fragment")
            else:
                if tcol1.button("✋ Take over", type="primary", use_container_width=True, key="takeover"):
                    post("/admin/mute", {"thread_id": sel, "muted": True})
                    st.rerun(scope="fragment")

            # transcript
            box = st.container(height=430)
            with box:
                for m in detail["messages"]:
                    role = m["role"]
                    if role == "customer":
                        avatar, who = "🧑", "user"
                    elif role == "admin":
                        avatar, who = "🧑‍💼", "assistant"
                    else:  # agent
                        avatar, who = "🤖", "assistant"
                    with st.chat_message(who, avatar=avatar):
                        prefix = "**Admin:** " if role == "admin" else ("**Agent:** " if role == "agent" else "")
                        st.markdown(prefix + m["content"])

            # admin reply box — only usable during takeover
            if muted:
                reply = st.chat_input("Reply to the customer as a human agent...", key="admin_reply")
                if reply:
                    post("/admin/send", {"thread_id": sel, "message": reply})
                    st.rerun(scope="fragment")
            else:
                st.caption("Take over the conversation to reply manually.")

    # ---- RIGHT: HITL approvals + orders ----
    with ops_col:
        st.markdown('<h2 class="section-header">🛡️ Approvals</h2>', unsafe_allow_html=True)
        try:
            inbound = get("/pending").get("pending", [])
        except requests.RequestException:
            inbound = []
        if not inbound:
            st.markdown(
                '<div class="ops-card" style="border-left:4px solid #10b981;">'
                '<strong style="color:#34d399;">No pending approvals</strong>'
                '<p style="margin:6px 0 0 0; font-size:0.85rem; color:#94a3b8;">'
                'High-value WhatsApp refunds will appear here for review.</p></div>',
                unsafe_allow_html=True,
            )
        for item in inbound:
            tid = item["thread_id"]
            action = item["action"]
            phone = tid.split(":", 1)[1] if ":" in tid else tid
            st.markdown(
                f"""
                <div class="ops-card pending">
                    <div style="display:flex; align-items:center; margin-bottom:8px;">
                        <span style="font-size:1.2rem; margin-right:8px;">📲</span>
                        <strong style="color:#fbbf24; font-size:1.05rem;">Refund · +{phone}</strong>
                    </div>
                    <div style="font-size:0.92rem; color:#e2e8f0; line-height:1.6;">
                        <p style="margin:4px 0;"><strong>Order:</strong> #{action.get('order_id')}</p>
                        <p style="margin:4px 0;"><strong>Amount:</strong> <span style="color:#f43f5e; font-weight:600;">${action.get('amount')}</span></p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            if c1.button("Approve", type="primary", use_container_width=True, key=f"ok_{tid}"):
                post("/resume", {"thread_id": tid, "approved": True})
                st.rerun(scope="fragment")
            if c2.button("Deny", use_container_width=True, key=f"no_{tid}"):
                post("/resume", {"thread_id": tid, "approved": False})
                st.rerun(scope="fragment")

        st.markdown(
            '<h3 style="font-family:Outfit; font-weight:600; margin-top:1rem; font-size:1.1rem; color:#f1f5f9;">📦 Orders</h3>',
            unsafe_allow_html=True,
        )
        for order in load_orders():
            status = order.get("status", "").lower()
            st.markdown(
                f"""
                <div class="ops-card" style="padding:12px 14px; margin-bottom:8px;">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-weight:600; font-size:0.95rem; color:#f8fafc;">Order #{order.get('order_id')}
                        <span style="font-size:0.8rem; color:#94a3b8; font-weight:normal; margin-left:8px;">{order.get('customer')}</span></span>
                        <span class="badge badge-{status}">{status.replace('_',' ')}</span>
                    </div>
                    <div style="margin-top:6px; font-size:0.8rem; color:#cbd5e1;">
                        <strong>Total:</strong> ${order.get('total',0):.2f} | <strong>ETA:</strong> {order.get('eta')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


console()
