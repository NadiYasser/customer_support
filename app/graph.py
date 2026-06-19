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

Memory: M3 compiles WITHOUT a checkpointer, so each /chat call is single-turn.
M5 attaches a checkpointer keyed by thread_id for multi-turn memory.
"""
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

    return graph.compile()


# Compiled once at import; main.py invokes this.
support_graph = build_graph()
