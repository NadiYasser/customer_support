"""Tools for the order-modification agent (M3).

Three thin @tool wrappers over OrderRepository write methods. The agent picks
which one to call based on what the customer wants — cancel, change shipping
address, or start a return. Each docstring tells the model when that specific
tool applies.
"""
from langchain_core.tools import tool

from app.repositories.orders import get_order_repository

_orders = get_order_repository()


@tool
def cancel_order(order_id: str) -> str:
    """Cancel a customer's order.

    Use this when a customer wants to cancel an order they placed.

    Args:
        order_id: The order's ID, e.g. "1002".
    """
    order = _orders.cancel_order(order_id)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Order {order_id} has been cancelled."


@tool
def change_address(order_id: str, address: str) -> str:
    """Change the shipping address on a customer's order.

    Use this when a customer wants their order delivered to a different address.

    Args:
        order_id: The order's ID, e.g. "1002".
        address: The new shipping address.
    """
    order = _orders.change_address(order_id, address)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Shipping address for order {order_id} updated to: {address}."


@tool
def initiate_return(order_id: str) -> str:
    """Start a return for a customer's order.

    Use this when a customer wants to return an item they received.

    Args:
        order_id: The order's ID, e.g. "1003".
    """
    order = _orders.initiate_return(order_id)
    if order is None:
        return f"No order found with ID {order_id}."
    return f"Return initiated for order {order_id}. Status is now '{order['status']}'."
