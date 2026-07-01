"""FAQ / Policy agent — the RAG path (M2).

Mirrors agents/tracking.py: same create_agent loop, but its tool is search_kb
instead of get_order_status. The agent calls search_kb, gets back raw KB chunks,
and must write its answer FROM those chunks.

The system prompt enforces the grounding discipline that is the whole point of
RAG: answer only from retrieved text, and admit when the KB doesn't cover the
question rather than inventing policy.
"""
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from app.cache.semantic_cache import faq_cache
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


def _latest_question(state) -> str:
    """The text of the most recent human message — what we key the cache on."""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


def faq_rag_node(state):
    """M11 — the FAQ agent wrapped in a semantic cache.

    This is the node the graph runs for the faq_rag route, in place of the bare
    agent. The flow:

        question -> cache.get(question)
                       hit  -> append the cached answer, DONE (no retrieval, no LLM)
                       miss -> run faq_rag_agent, store its answer, return it

    Why a wrapper instead of caching inside the agent loop: the win of a cache is
    skipping the expensive work entirely — retrieval + the LLM call. Checking BEFORE
    the agent runs is what buys the latency/cost saving. On a miss we let the normal
    agent loop run untouched, then learn from its answer for next time.

    Only the final-answer text is cached, keyed on the question — never tool calls or
    intermediate state. Reuse is safe here precisely because FAQ answers are grounded
    in static policy and have no side effects (see app/cache/semantic_cache.py).
    """
    question = _latest_question(state)

    cached = faq_cache.get(question)
    if cached is not None:
        return {"messages": [AIMessage(cached)]}

    result = faq_rag_agent.invoke(state)
    answer = result["messages"][-1].content
    faq_cache.put(question, answer)
    # Return only the new answer; add_messages appends it to the shared history.
    return {"messages": [AIMessage(answer)]}
