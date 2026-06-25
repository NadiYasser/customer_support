"""Refund agent (M5) — human-in-the-loop gate lives in the tool.

Same shape as tracking.py: a create_agent loop with one tool, process_refund.
The agent figures out the order ID and amount from the conversation and calls the
tool. The approval gate is inside process_refund (app/tools/refund.py): refunds
at/above REFUND_APPROVAL_THRESHOLD call interrupt() to pause for human approval
before the repository write; below-threshold refunds execute immediately.
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.orders import get_order_total
from app.tools.refund import process_refund

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Help customers with refunds. When a customer asks for a refund, determine the "
    "order ID and the refund amount, then use the process_refund tool. "
    "If the customer wants a full refund but does not state an amount, do NOT ask "
    "them for it — call get_order_total to look up what they paid and refund that. "
    "Only ask the customer when the order ID itself is missing. "
    "If the message is not actually about a refund — or is unrelated to this store "
    "entirely (general knowledge, coding, math, trivia, AI questions) — do NOT "
    "answer it. Politely say you can only help with store orders and support, and "
    "invite the customer to ask about order tracking, refunds, returns, order "
    "changes, or store policies. "
    "Answer in a friendly, concise way."
)

refund_agent = create_agent(
    model=get_model(),
    tools=[get_order_total, process_refund],
    system_prompt=SYSTEM_PROMPT,
)
