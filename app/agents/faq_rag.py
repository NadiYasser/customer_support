"""FAQ / Policy agent — the RAG path (M2).

Mirrors agents/tracking.py: same create_agent loop, but its tool is search_kb
instead of get_order_status. The agent calls search_kb, gets back raw KB chunks,
and must write its answer FROM those chunks.

The system prompt enforces the grounding discipline that is the whole point of
RAG: answer only from retrieved text, and admit when the KB doesn't cover the
question rather than inventing policy.
"""
from langchain.agents import create_agent

from app.config import get_model
from app.tools.kb import search_kb

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. "
    "Answer questions about store policy — shipping, returns, refunds, and general "
    "FAQ — by calling the search_kb tool and basing your answer ONLY on what it "
    "returns. Do not rely on prior knowledge for policy details. "
    "If the knowledge base does not contain the answer — or the question is "
    "unrelated to the store (e.g. weather, math, general trivia) — do NOT guess. "
    "Politely say you can't help with that particular question, then invite the "
    "customer to ask about what you CAN help with: order tracking, shipping, "
    "returns and refunds, or product and policy questions. Keep answers friendly "
    "and concise. "
    "Each chunk search_kb returns is prefixed with its source in the form "
    "[file — section]. After your answer, cite the section(s) you used on a new "
    "line starting with 'Source:' (e.g. 'Source: returns_policy.md — Sale items'). "
    "Only cite sections you actually used; if you had no relevant KB entry, do not "
    "add a Source line."
)

faq_rag_agent = create_agent(
    model=get_model(),
    tools=[search_kb],
    system_prompt=SYSTEM_PROMPT,
)
