"""Supervisor / router node (M3) — the orchestration heart.

A node in LangGraph is just a function: state -> partial state update. This one
reads the latest customer message and decides WHICH specialized agent should
handle it. It writes that decision into state["route"]; a conditional edge in
graph.py then reads state["route"] and sends control to the matching agent node.

How the decision is made reliably:
  We don't parse free-form model text ("I think this is a refund..."). Instead we
  give the model a SCHEMA — a Pydantic class whose one field is constrained to the
  five valid route names — and call with_structured_output. The model is forced to
  return one of those exact labels, so state["route"] is always a value the
  conditional edge knows how to handle. This is the same tool/JSON mechanism the
  agents use, pointed at classification instead of an action.
"""
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_model
from app.state import SupportState

# The valid destinations. Keeping them in one place: the Literal below (what the
# model may choose) and the graph's conditional edge must agree on these names.
# out_of_scope is NOT an agent — it's the "none of these fit" label that routes to
# a canned refusal node instead of an LLM agent (see graph.py).
Route = Literal[
    "faq_rag", "tracking", "refund", "modify", "it_support", "out_of_scope"
]


class RoutingDecision(BaseModel):
    """The supervisor's choice of which agent handles the current message."""

    route: Route = Field(
        description=(
            "Which specialized agent should handle this message:\n"
            "- faq_rag: questions about store policy (shipping, returns, refund "
            "rules, sizing, general FAQ)\n"
            "- tracking: where is my order / status / ETA / tracking number\n"
            "- refund: the customer wants money back for an order\n"
            "- modify: cancel an order, change its shipping address, or start a return\n"
            "- it_support: a merchant reports a website/technical problem\n"
            "- out_of_scope: anything NOT about this store's orders or support — "
            "general knowledge, coding/technical how-tos, math, trivia, the weather, "
            "AI/prompt questions, or any topic unrelated to shopping with this store"
        )
    )


SYSTEM_PROMPT = (
    "You are the supervisor of a customer-support system for an online store. "
    "Read the customer's latest message and route it to exactly one destination. "
    "Choose the best single fit based on what the customer is actually asking for. "
    "You ONLY handle questions about this store's orders and support. If the message "
    "is about anything else — general knowledge, programming, math, AI, trivia, the "
    "weather — route it to out_of_scope. Do not try to be helpful by stretching an "
    "unrelated question into one of the agent categories."
)

# Bind the schema to the model once. _router.invoke(messages) now returns a
# RoutingDecision instance instead of a chat message.
#
# method="json_schema" is important here. By default with_structured_output uses
# TOOL CALLING to extract the fields — but this Groq model intermittently emits a
# malformed tool call (it picks the right route, then serializes the call with the
# wrong tool name), which Groq rejects with 400 tool_use_failed. json_schema asks
# Groq to constrain the raw response to our schema directly, skipping tool
# serialization entirely — so routing is reliable.
_router = get_model().with_structured_output(RoutingDecision, method="json_schema")


def supervisor(state: SupportState) -> dict:
    last_message = state["messages"][-1]
    decision = _router.invoke(
        [
            ("system", SYSTEM_PROMPT),
            ("human", last_message.content),
        ]
    )
    return {"route": decision.route}
