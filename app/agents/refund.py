"""Refund agent (M5) — human-in-the-loop gate lives in the tool.

Same shape as tracking.py: a create_agent loop with one tool, process_refund.
The agent figures out the order ID and amount from the conversation and calls the
tool. The approval gate is inside process_refund (app/tools/refund.py): refunds
at/above REFUND_APPROVAL_THRESHOLD call interrupt() to pause for human approval
before the repository write; below-threshold refunds execute immediately.
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.refund import process_refund

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Help customers with refunds. When a customer asks for a refund, determine the "
    "order ID and the refund amount, then use the process_refund tool. If you are "
    "missing the order ID or the amount, ask for it before refunding. "
    "Answer in a friendly, concise way."
)

refund_agent = create_agent(
    model=get_model(),
    tools=[process_refund],
    system_prompt=SYSTEM_PROMPT,
)
