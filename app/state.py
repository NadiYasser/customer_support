"""Graph state schema (M3+).

The state object is what flows between LangGraph nodes. It will hold the running
message history plus routing/pending-action fields. Defined here so every node
imports one shared schema.
"""
# TODO(M3): define the TypedDict / pydantic state (messages, route, pending_action, ...).
