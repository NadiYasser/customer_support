"""The search_kb tool (M2, extended M8) — the FAQ/RAG agent's only tool.

Same shape as tools/orders.py: a thin @tool function the LLM can call. The
docstring is what the model reads to decide when to call it.

Crucially, this tool returns the RETRIEVED CHUNKS, not a finished answer. The
agent must compose its reply FROM these chunks — that is what makes the answer
"grounded" and what makes RAG visible: you can see exactly what text the model
was given to work from.

M8 precision gate: we use retrieve_relevant(), which drops chunks below a
relevance-score floor. If nothing clears it the tool returns an explicit
"no relevant entry" message, so the agent declines instead of grounding an
answer on the least-irrelevant policy chunk it could find.
"""
from langchain_core.tools import tool

from app.rag.retriever import retrieve_relevant

NO_MATCH = (
    "No relevant knowledge-base entries found. The knowledge base does not cover "
    "this question. Do NOT make up an answer. Instead reply warmly: briefly say you "
    "can't help with that particular question, then invite the customer to ask about "
    "things you CAN help with — order tracking, shipping, returns and refunds, or "
    "product and policy questions. Keep it short and friendly, and do not add a "
    "Source line."
)


@tool
def search_kb(query: str) -> str:
    """Search the store's knowledge base (shipping, returns, refunds, FAQ, policies).

    Use this for any question about store policy or how things work — return
    windows, shipping times/costs, refund rules, etc. Always base your answer on
    what this returns; do not answer policy questions from memory.

    Args:
        query: A natural-language search query, e.g. "return policy for sale items".
    """
    hits = retrieve_relevant(query)
    if not hits:
        return NO_MATCH

    blocks = []
    for doc, score in hits:
        section = doc.metadata.get("section") or doc.metadata.get("doc") or "KB"
        source = doc.metadata.get("source", "kb")
        blocks.append(f"[{source} — {section}] (relevance {score:.2f})\n{doc.page_content}")
    return "\n\n".join(blocks)

