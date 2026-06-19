"""Order modification agent (M3).

A create_react_agent loop with three tools: cancel_order, change_address,
initiate_return. This agent shows that one agent can hold MULTIPLE tools and let
the model pick the right one based on what the customer wants.
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.modify import cancel_order, change_address, initiate_return

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Help customers modify their orders: cancel an order, change its shipping "
    "address, or start a return. Pick the right tool for what the customer wants. "
    "If you are missing the order ID (or a new address for an address change), ask "
    "for it first. Answer in a friendly, concise way."
)

modify_agent = create_agent(
    model=get_model(),
    tools=[cancel_order, change_address, initiate_return],
    system_prompt=SYSTEM_PROMPT,
)
