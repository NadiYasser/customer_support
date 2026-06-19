"""LangGraph graph assembly (M3).

Wires the supervisor + the five specialized agents into ONE runnable graph.

Control flow:

    START → supervisor → (conditional edge on state["route"]) → one agent → END

- add_node registers each piece as a node. The prebuilt agents are themselves
  runnables, so they slot in directly as nodes.
- START always goes to the supervisor: every turn is classified first.
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

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agents.faq_rag import faq_rag_agent
from app.agents.it_support import it_support_agent
from app.agents.modify import modify_agent
from app.agents.refund import refund_agent
from app.agents.tracking import tracking_agent
from app.state import SupportState
from app.supervisor import supervisor

_AGENT_NODES = {
    "faq_rag": faq_rag_agent,
    "tracking": tracking_agent,
    "refund": refund_agent,
    "modify": modify_agent,
    "it_support": it_support_agent,
}

# Where the conversation snapshots live. Absolute path derived from this module's
# location so the DB is the same file no matter the server's launch directory.
_DB_PATH = str(Path(__file__).parent / "data" / "checkpoints.sqlite")


def _pick_route(state: SupportState) -> str:
    # The conditional edge's decision function: just surface the route the
    # supervisor already chose. The Literal in supervisor.py guarantees it is
    # one of the keys below.
    return state["route"]


def build_graph():
    graph = StateGraph(SupportState)

    graph.add_node("supervisor", supervisor)
    for name, agent in _AGENT_NODES.items():
        graph.add_node(name, agent)

    graph.add_edge(START, "supervisor")
    # Map each route value to its agent node. The keys here MUST match the route
    # names the supervisor can emit.
    graph.add_conditional_edges(
        "supervisor",
        _pick_route,
        {name: name for name in _AGENT_NODES},
    )
    for name in _AGENT_NODES:
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
