"""Tools for the refund agent (M5 — human-in-the-loop gate).

process_refund is a thin @tool over OrderRepository.process_refund, now wrapped
in an approval gate:

- amount <  REFUND_APPROVAL_THRESHOLD  → write immediately (as before).
- amount >= REFUND_APPROVAL_THRESHOLD  → call interrupt(payload) BEFORE the write.
  interrupt() checkpoints the state and pauses the whole graph; the payload
  describes the proposed refund so a human can review it. The graph resumes when
  /resume calls invoke(Command(resume=decision)) on the same thread_id — at which
  point interrupt() RETURNS that decision and we either write or decline.

Why the interrupt() comes BEFORE the repository write: on resume, LangGraph
re-runs the paused node from its start. Already-resolved interrupt() calls return
their cached decision instead of pausing again, but any code before the interrupt
runs a second time. Putting the write AFTER the gate guarantees the mutation
happens exactly once, only on approval — never while paused, never on denial.
"""
from langchain_core.tools import tool
from langgraph.types import interrupt

from app.config import REFUND_APPROVAL_THRESHOLD
from app.repositories.orders import get_order_repository

_orders = get_order_repository()


@tool
def process_refund(order_id: str, amount: float) -> str:
    """Refund a customer's order.

    Use this when a customer asks for a refund and you know the order ID and the
    amount to refund.

    Args:
        order_id: The order's ID, e.g. "1003".
        amount: The amount to refund, in the store's currency, e.g. 120.00.
    """
    if amount >= REFUND_APPROVAL_THRESHOLD:
        # Pause here. The graph checkpoints and /chat returns with this payload;
        # execution only continues when /resume supplies a decision. On resume,
        # `decision` is whatever was passed as Command(resume=...).
        decision = interrupt(
            {
                "action": "process_refund",
                "order_id": order_id,
                "amount": amount,
                "reason": f"Refund of {amount} is at/above the approval threshold "
                f"of {REFUND_APPROVAL_THRESHOLD} and needs human approval.",
            }
        )
        if not decision.get("approved"):
            return (
                f"Refund of {amount} for order {order_id} was declined by a human "
                f"reviewer. No refund was processed."
            )

    order = _orders.process_refund(order_id, amount)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Refund of {amount} processed for order {order_id}. Status is now '{order['status']}'."
