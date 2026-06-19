"""LangGraph graph assembly (M1+).

Builds the graph: supervisor node + specialized agent nodes, wired with a
checkpointer so conversations persist by thread_id. Built incrementally —
M1 starts with a single tracking agent, later milestones add the supervisor
and the other agents.
"""
# TODO(M1): build a minimal graph with the tracking agent + tool loop.
# TODO(M3): add the supervisor router and the remaining agent nodes.
# TODO(M5): attach a checkpointer keyed by thread_id for multi-turn memory.
