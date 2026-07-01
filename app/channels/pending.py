"""Pending-approval store for async channels (M13).

WHY THIS EXISTS. With HTTP /chat the caller holds the connection and reads the
`pending_approval` straight off the response, then calls /resume itself. A channel
like WhatsApp is ASYNCHRONOUS: the inbound webhook returns immediately to Meta,
and whoever approves the refund (an admin on the Streamlit dashboard) is a
DIFFERENT process arriving LATER. The "request" event and the "approve" event are
fully decoupled, so the proposed action can't live on a request/response cycle —
it needs an out-of-band place both sides can see. That place is this store.

The LangGraph checkpointer already persists the PAUSED GRAPH (keyed by thread_id),
so resuming is safe whenever it happens. What the checkpointer does NOT give us is
a *queryable list* of "which threads are currently waiting for a human" — that's
what we add here: a tiny index of pending actions the dashboard can poll.

SCOPE. In-process dict, single server. That's the honest minimum for a learning
build and it makes the mechanism visible. A real multi-worker deployment would
back this with Redis/a table (and the checkpointer would still be the source of
truth for the graph state itself) — but the shape of the code wouldn't change.
"""
import threading

# thread_id -> the interrupt payload our refund tool passed to interrupt()
# (action, order_id, amount, reason). Guarded by a lock because uvicorn serves
# requests on a thread pool and both the webhook and /pending touch this dict.
_pending: dict[str, dict] = {}
_lock = threading.Lock()


def add(thread_id: str, action: dict) -> None:
    """Record that `thread_id` is paused awaiting human approval of `action`."""
    with _lock:
        _pending[thread_id] = action


def remove(thread_id: str) -> None:
    """Clear a thread's pending entry once it's been approved or denied."""
    with _lock:
        _pending.pop(thread_id, None)


def list_all() -> list[dict]:
    """Snapshot of everything awaiting approval, for the dashboard to render."""
    with _lock:
        return [{"thread_id": tid, "action": action} for tid, action in _pending.items()]
