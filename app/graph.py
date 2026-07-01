"""LangGraph graph assembly (M3).

Wires the supervisor + the five specialized agents into ONE runnable graph.

Control flow:

    START → input_guard → (blocked? → END)
                        → supervisor → (conditional edge on state["route"]) → one agent → END

- add_node registers each piece as a node. The prebuilt agents are themselves
  runnables, so they slot in directly as nodes.
- START goes to the input_guard (M10): a deterministic prompt-injection gate runs
  before any LLM. If it flags the message, a conditional edge jumps straight to END
  (the guard already appended a refusal) so no supervisor/agent/tool ever runs.
- Otherwise control passes to the supervisor: every non-blocked turn is classified.
- add_conditional_edges is the routing made literal. After the supervisor runs,
  _pick_route(state) returns state["route"], and the mapping below sends control
  to the matching agent node.
- Each agent edges to END: once it has answered, the turn is over.

The agents share our SupportState because they key on "messages" with the same
add_messages reducer — an agent reads the messages, appends its reply, and that
update merges back into the shared state.

Memory (M4): the graph compiles WITH a checkpointer. LangGraph snapshots the
state after every step, keyed by the thread_id passed in the call config. On the
next call with the same thread_id, it restores that snapshot before applying the
new input — and because "messages" uses the add_messages reducer (append, not
overwrite), the new turn piles onto the restored history. Persistence + an
appending reducer = multi-turn memory.

We use SqliteSaver: snapshots are written to a file on disk, so conversations
survive a server restart (unlike MemorySaver's in-process dict). A file-backed
saver needs an open DB connection, which has a lifecycle MemorySaver never had —
the connection must outlive every request. Since the graph compiles ONCE at
import and lives as long as the process, we open one sqlite3 connection here and
hand it to SqliteSaver; its lifetime is tied to the process, which is what we
want for a long-running server.

check_same_thread=False: uvicorn serves requests on a thread pool, but a sqlite3
connection is bound to its creating thread by default. We share one connection
across worker threads; SqliteSaver serializes its own writes, so this is safe.
"""
import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agents.faq_rag import faq_rag_node
from app.agents.it_support import it_support_agent
from app.agents.modify import modify_agent
from app.agents.refund import refund_agent
from app.agents.tracking import tracking_agent
from app.guards.injection import detect_injection
from app.state import SupportState
from app.supervisor import supervisor

# What the user sees when the input guard blocks a turn (M10). Deliberately generic:
# we don't echo the matched pattern or explain the detector, which would just teach
# an attacker how to word around it.
BLOCKED_MESSAGE = (
    "I can't help with that request. I'm here to help with this store's orders and "
    "support — tracking, refunds, returns, order changes, and policy questions. "
    "What can I help you with?"
)


def input_guard(state: SupportState) -> dict:
    """M10 — the security gate that runs BEFORE the supervisor.

    A node is just `state -> partial update`. This one inspects the latest customer
    message with a deterministic detector (app/guards/injection.py). On a hit it
    sets blocked=True and appends a canned refusal; otherwise it clears the flag so
    a prior turn's block doesn't linger in the restored state.

    Why a separate node in FRONT of the supervisor, instead of a check inside it?
    The supervisor and agents are the LLMs we're defending — one of them can issue
    refunds. A guard's value is being INDEPENDENT of what it protects: a regex gate
    can't be argued out of its verdict by "ignore your instructions" text, which is
    the whole point of an injection. Putting it ahead of the supervisor means a
    flagged message never reaches any model or tool.
    """
    last_message = state["messages"][-1]
    hit = detect_injection(last_message.content)
    if hit:
        return {"blocked": True, "messages": [AIMessage(BLOCKED_MESSAGE)]}
    return {"blocked": False}

_AGENT_NODES = {
    "faq_rag": faq_rag_node,
    "tracking": tracking_agent,
    "refund": refund_agent,
    "modify": modify_agent,
    "it_support": it_support_agent,
}

# The canned reply for messages the supervisor routes to out_of_scope. Shared with
# the streaming path (streaming.py) so both surfaces refuse identically.
OUT_OF_SCOPE_MESSAGE = (
    "I'm a customer support assistant for this store, so I can only help with "
    "shopping-related questions. Here's what I can do for you:\n"
    "  - Track an order (status, ETA, tracking number)\n"
    "  - Process a refund\n"
    "  - Cancel or modify an order, or start a return\n"
    "  - Answer questions about our shipping, returns, and refund policies\n"
    "  - Open a support ticket for a website/technical problem\n"
    "What can I help you with?"
)


def out_of_scope(state: SupportState) -> dict:
    """Fallback node: not an LLM agent, just a fixed refusal.

    A LangGraph node is only `state -> partial update` — it need not call a model.
    For a refusal we want deterministic, controlled text (no tokens, no chance of
    the model answering the off-topic question anyway), so this node simply appends
    one canned AIMessage. The add_messages reducer merges it into the history like
    any agent reply.
    """
    return {"messages": [AIMessage(OUT_OF_SCOPE_MESSAGE)]}

# Where the conversation snapshots live. Absolute path derived from this module's
# location so the DB is the same file no matter the server's launch directory.
_DB_PATH = str(Path(__file__).parent / "data" / "checkpoints.sqlite")


def _pick_route(state: SupportState) -> str:
    # The conditional edge's decision function: just surface the route the
    # supervisor already chose. The Literal in supervisor.py guarantees it is
    # one of the keys below.
    return state["route"]


def _guard_gate(state: SupportState) -> str:
    # The conditional edge AFTER the input guard. Reads the blocked flag the guard
    # set and turns it into control flow: blocked → END (skip everything), else →
    # supervisor. Same decision-becomes-control-flow trick as _pick_route, used as
    # a safety gate at the front of the graph.
    return "blocked" if state.get("blocked") else "supervisor"


def build_graph():
    graph = StateGraph(SupportState)

    graph.add_node("input_guard", input_guard)
    graph.add_node("supervisor", supervisor)
    for name, agent in _AGENT_NODES.items():
        graph.add_node(name, agent)
    graph.add_node("out_of_scope", out_of_scope)

    # Every turn enters the guard first. Its conditional edge either short-circuits
    # to END (flagged) or hands off to the supervisor (clean).
    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges(
        "input_guard",
        _guard_gate,
        {"blocked": END, "supervisor": "supervisor"},
    )
    # Map each route value to its node. The keys here MUST match the route names
    # the supervisor can emit — including out_of_scope, which maps to the canned
    # refusal node rather than an LLM agent.
    _route_targets = list(_AGENT_NODES) + ["out_of_scope"]
    graph.add_conditional_edges(
        "supervisor",
        _pick_route,
        {name: name for name in _route_targets},
    )
    for name in _route_targets:
        graph.add_edge(name, END)

    # The checkpointer is what turns this from a single-shot graph into a
    # stateful one. Without it, .invoke starts from whatever dict you pass.
    # With it, LangGraph loads the saved snapshot for the call's thread_id first.
    # SqliteSaver persists those snapshots to checkpoints.sqlite on disk, so the
    # conversation history outlives a server restart.
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    return graph.compile(checkpointer=SqliteSaver(conn))


# Compiled once at import; main.py invokes this.
support_graph = build_graph()
