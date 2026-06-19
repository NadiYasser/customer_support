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
    "If the knowledge base does not contain the answer, say you don't have that "
    "information rather than guessing. Keep answers friendly and concise."
)

faq_rag_agent = create_agent(
    model=get_model(),
    tools=[search_kb],
    system_prompt=SYSTEM_PROMPT,
)
