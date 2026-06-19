"""Graph state schema (M3).

The state object is what flows between LangGraph nodes. Every node is a function
state -> partial-state-update; LangGraph merges that update back into the shared
state and moves to the next node.

Two fields for M3:

- messages: the running conversation. The Annotated[..., add_messages] part wires
  in a REDUCER. When a node returns {"messages": [some_message]}, LangGraph does
  NOT overwrite the list — the add_messages reducer APPENDS to it. That is how each
  agent's reply piles onto the history instead of clobbering it.

- route: the supervisor node writes the name of the agent that should handle this
  turn ("faq_rag", "tracking", ...). A conditional edge then reads this field to
  decide which agent node runs next. This single field is how a *decision* made by
  the supervisor becomes actual *control flow* in the graph.
"""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SupportState(TypedDict):
    messages: Annotated[list, add_messages]
    route: str
