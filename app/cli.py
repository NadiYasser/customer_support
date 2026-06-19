"""Interactive CLI for testing the support graph (M5).

A tiny REPL: type a message, the graph runs (supervisor → routed agent), and we
print BOTH the route the supervisor chose and the agent's reply. Seeing the route
on every turn is the point — it makes the orchestration decision visible instead
of hidden behind the final answer.

Talks to the compiled graph DIRECTLY (no HTTP), so what you see is exactly the
graph's behavior. Because the graph now compiles WITH a checkpointer (M4), every
invoke needs a thread_id in its config — we use ONE id per CLI session, so memory
carries across turns within a run and a new run starts fresh.

It also handles the M5 approval gate: a large refund makes the graph interrupt()
and pause. Direct callers see that as an "__interrupt__" field instead of a final
message, so we prompt y/n at the terminal and resume the SAME thread with
Command(resume=...) — the CLI equivalent of the /chat → /resume HTTP flow.

Run:  python -m app.cli
Exit: type 'quit', 'exit', or Ctrl-D.
"""
import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.graph import support_graph


def _run(graph_input, config):
    # Run the graph, then keep resolving approval gates until it finishes. If the
    # result carries "__interrupt__", the graph paused inside the refund tool:
    # we show the proposed action, ask the human, and resume the same thread with
    # the decision. Looping covers the (rare here) case of more than one gate.
    result = support_graph.invoke(graph_input, config)
    while result.get("__interrupt__"):
        action = result["__interrupt__"][0].value
        print(f"  [approval needed] {action.get('reason', action)}")
        answer = input("  approve? (y/n)> ").strip().lower()
        approved = answer in {"y", "yes"}
        result = support_graph.invoke(Command(resume={"approved": approved}), config)
    return result


def main():
    print("Support graph CLI — type a message, or 'quit' to exit.\n")
    # One thread id for the whole session → multi-turn memory within this run.
    config = {"configurable": {"thread_id": f"cli-{uuid.uuid4()}"}}
    while True:
        try:
            message = input("you> ").strip()
        except EOFError:
            print()
            break
        if not message:
            continue
        if message.lower() in {"quit", "exit"}:
            break

        result = _run({"messages": [HumanMessage(message)]}, config)
        route = result.get("route", "?")
        reply = result["messages"][-1].content
        print(f"  [routed → {route}]")
        print(f"bot> {reply}\n")


if __name__ == "__main__":
    main()
