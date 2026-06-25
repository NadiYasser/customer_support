"""Order tracking agent (M1) — first agent we build.

Read-only. Tool: get_order_status(order_id) -> status, ETA, tracking number.
This is where we learn the basic agent loop: LLM decides to call the tool,
we run it, feed the result back, LLM writes the final answer.
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.orders import get_order_status

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Help customers track their orders. When a customer asks about an order, "
    "use the get_order_status tool to look it up, then answer in a friendly, "
    "concise way. If you don't have an order ID, ask for it. "
    "If the message is not actually about tracking an order — or is unrelated to "
    "this store entirely (general knowledge, coding, math, trivia, AI questions) — "
    "do NOT answer it. Politely say you can only help with store orders and support, "
    "and invite the customer to ask about order tracking, refunds, returns, order "
    "changes, or store policies."
)

# create_react_agent builds the agent loop for us:
#   model + tools + system prompt  ->  a runnable graph that loops
#   (call model -> run any requested tool -> call model again -> ... -> answer)
tracking_agent = create_agent(
    model=get_model(),
    tools=[get_order_status],
    system_prompt=SYSTEM_PROMPT,
)
