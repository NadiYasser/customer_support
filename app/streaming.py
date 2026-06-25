"""Streaming the answer token-by-token (M9).

The non-streaming path (main.py /chat) calls support_graph.invoke(): it blocks
until the whole graph finishes, then returns the complete reply. This module is
the streaming counterpart — it yields the answer's text as the model generates
it, so a UI can render it incrementally.

Why we DON'T just stream the compiled graph
--------------------------------------------
Streaming support_graph.stream(stream_mode="messages") flattens the chosen
agent's output into a SINGLE message chunk at the sub-graph boundary — no
token-by-token deltas (verified during M9 step 1). Streaming the AGENT directly,
by contrast, yields real per-token AIMessageChunks. So we split the run:

    1. invoke the supervisor once  -> get the route (its JSON should NOT stream
       to the user anyway, so buffering it is correct, not a workaround)
    2. stream the chosen agent     -> forward only its final-answer tokens

Memory note
-----------
Because we bypass the compiled graph, the checkpointer never sees this turn. We
load prior history from it up front and write the new turn back afterward, so the
streamed path keeps the same multi-turn memory as /chat.
"""
from collections.abc import Iterator

from langchain_core.messages import AIMessage, HumanMessage

from app.graph import support_graph, OUT_OF_SCOPE_MESSAGE
from app.supervisor import supervisor
from app.agents.faq_rag import faq_rag_agent
from app.agents.it_support import it_support_agent
from app.agents.modify import modify_agent
from app.agents.refund import refund_agent
from app.agents.tracking import tracking_agent

_AGENTS = {
    "faq_rag": faq_rag_agent,
    "tracking": tracking_agent,
    "refund": refund_agent,
    "modify": modify_agent,
    "it_support": it_support_agent,
}


def _is_tool_chunk(chunk) -> bool:
    """True if this chunk is carrying a tool CALL, not answer text."""
    return bool(
        getattr(chunk, "tool_calls", None) or getattr(chunk, "tool_call_chunks", None)
    )


def stream_answer(thread_id: str, message: str) -> Iterator[str]:
    """Yield the assistant's answer text in token-sized pieces.

    Routes via the supervisor, then streams the chosen agent. Only final-answer
    text is yielded — routing JSON, tool-call chunks, and tool results are
    filtered out. After the stream ends, the turn is persisted to the checkpointer
    so the conversation remembers it next time.
    """
    config = {"configurable": {"thread_id": thread_id}}

    # Load prior conversation from the checkpointer (empty list on a new thread),
    # then append this turn's human message — the agent answers with full context.
    snapshot = support_graph.get_state(config)
    history = snapshot.values.get("messages", []) if snapshot.values else []
    human = HumanMessage(message)
    agent_input = {"messages": history + [human]}

    # 1) Route. One quick invoke; the supervisor reads only the latest message.
    route = supervisor({"messages": [human]})["route"]

    # out_of_scope has no agent — the graph handles it with a canned refusal node,
    # but this path bypasses the graph, so we mirror that refusal here: yield the
    # fixed message, persist the turn, and stop. No agent, no LLM call.
    if route == "out_of_scope":
        yield OUT_OF_SCOPE_MESSAGE
        support_graph.update_state(
            config, {"messages": [human, AIMessage(OUT_OF_SCOPE_MESSAGE)]}
        )
        return

    agent = _AGENTS[route]

    # 2) Stream the chosen agent, forwarding only answer-text tokens.
    pieces: list[str] = []
    for chunk, meta in agent.stream(agent_input, stream_mode="messages"):
        if type(chunk).__name__ != "AIMessageChunk":
            continue  # ToolMessage (tool result) etc.
        if _is_tool_chunk(chunk) or not chunk.content:
            continue  # tool-call deltas / empty keep-alive chunks
        pieces.append(chunk.content)
        yield chunk.content

    # 3) Persist the turn (human + final answer) so memory survives to next turn.
    answer = "".join(pieces)
    support_graph.update_state(config, {"messages": [human, AIMessage(answer)]})
