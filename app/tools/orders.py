"""Tools the tracking agent can call (M1).

A "tool" is a normal Python function exposed to the LLM. The @tool decorator
reads the function's name, type hints, and docstring and turns them into a
schema the model sees. That docstring is not human documentation — it is the
instruction the model reads to decide WHEN and HOW to call this function.
"""
from langchain_core.tools import tool

from app.repositories.orders import OrderRepository

# One shared repository instance (loads orders.json once).
_orders = OrderRepository()


@tool
def get_order_status(order_id: str) -> str:
    """Look up the status of a customer order by its order ID.

    Use this whenever a customer asks where their order is, its delivery
    status, its ETA, or its tracking number.

    Args:
        order_id: The order's ID, e.g. "1001".
    """
    order = _orders.get_order(order_id)
    if order is None:
        return f"No order found with ID {order_id}."
    return (
        f"Order {order['order_id']} for {order['customer']}: "
        f"status={order['status']}, ETA={order['eta']}, "
        f"tracking={order['tracking_number'] or 'not yet assigned'}."
    )


@tool
def get_order_total(order_id: str) -> str:
    """Look up how much a customer paid for an order, by its order ID.

    Use this to find the refund amount when a customer asks for a full refund
    but does not state a figure — look up what they paid instead of asking them.

    Args:
        order_id: The order's ID, e.g. "1001".
    """
    order = _orders.get_order(order_id)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Order {order['order_id']} total paid: {order['total']}."
