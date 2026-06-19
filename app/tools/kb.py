"""The search_kb tool (M2) — the FAQ/RAG agent's only tool.

Same shape as tools/orders.py: a thin @tool function the LLM can call. The
docstring is what the model reads to decide when to call it.

Crucially, this tool returns the RETRIEVED CHUNKS, not a finished answer. The
agent must compose its reply FROM these chunks — that is what makes the answer
"grounded" and what makes RAG visible: you can see exactly what text the model
was given to work from.
"""
from langchain_core.tools import tool

from app.rag.retriever import get_retriever

# One shared retriever (opens the Chroma collection once).
_retriever = get_retriever(k=3)


@tool
def search_kb(query: str) -> str:
    """Search the store's knowledge base (shipping, returns, refunds, FAQ, policies).

    Use this for any question about store policy or how things work — return
    windows, shipping times/costs, refund rules, etc. Always base your answer on
    what this returns; do not answer policy questions from memory.

    Args:
        query: A natural-language search query, e.g. "return policy for sale items".
    """
    docs = _retriever.invoke(query)
    if not docs:
        return "No relevant knowledge-base entries found."

    blocks = []
    for d in docs:
        section = d.metadata.get("section") or d.metadata.get("doc") or "KB"
        source = d.metadata.get("source", "kb")
        blocks.append(f"[{source} — {section}]\n{d.page_content}")
    return "\n\n".join(blocks)
