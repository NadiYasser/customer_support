"""Tools for the refund agent (M3).

process_refund is a thin @tool over OrderRepository.process_refund. The docstring
is what the model reads to decide when to call it.

For M3 this executes the refund immediately. M4 wraps it in a human-in-the-loop
gate: if amount >= REFUND_APPROVAL_THRESHOLD, the graph will interrupt() and wait
for approval before the repository write happens. We keep the tool itself simple
now so the gate is a clean addition later, not a rewrite.
"""
from langchain_core.tools import tool

from app.repositories.orders import OrderRepository

_orders = OrderRepository()


@tool
def process_refund(order_id: str, amount: float) -> str:
    """Refund a customer's order.

    Use this when a customer asks for a refund and you know the order ID and the
    amount to refund.

    Args:
        order_id: The order's ID, e.g. "1003".
        amount: The amount to refund, in the store's currency, e.g. 120.00.
    """
    order = _orders.process_refund(order_id, amount)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Refund of {amount} processed for order {order_id}. Status is now '{order['status']}'."
