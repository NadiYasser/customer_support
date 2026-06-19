"""Order tracking agent (M1) — first agent we build.

Read-only. Tool: get_order_status(order_id) -> status, ETA, tracking number.
This is where we learn the basic agent loop: LLM decides to call the tool,
we run it, feed the result back, LLM writes the final answer.
"""
from langgraph.prebuilt import create_react_agent

from app.config import get_model
from app.tools.orders import get_order_status

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Help customers track their orders. When a customer asks about an order, "
    "use the get_order_status tool to look it up, then answer in a friendly, "
    "concise way. If you don't have an order ID, ask for it."
)

# create_react_agent builds the agent loop for us:
#   model + tools + system prompt  ->  a runnable graph that loops
#   (call model -> run any requested tool -> call model again -> ... -> answer)
tracking_agent = create_react_agent(
    model=get_model(),
    tools=[get_order_status],
    prompt=SYSTEM_PROMPT,
)
