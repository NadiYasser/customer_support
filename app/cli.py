"""Interactive CLI for testing the support graph (M3).

A tiny REPL: type a message, the graph runs (supervisor → routed agent), and we
print BOTH the route the supervisor chose and the agent's reply. Seeing the route
on every turn is the point — it makes the orchestration decision visible instead
of hidden behind the final answer.

Talks to the compiled graph DIRECTLY (no HTTP), so what you see is exactly the
graph's behavior. Single-turn for now: M3 compiles without a checkpointer, so each
message is independent — no memory across turns until M5.

Run:  python -m app.cli
Exit: type 'quit', 'exit', or Ctrl-D.
"""
from langchain_core.messages import HumanMessage

from app.graph import support_graph


def main():
    print("Support graph CLI — type a message, or 'quit' to exit.\n")
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

        result = support_graph.invoke({"messages": [HumanMessage(message)]})
        route = result.get("route", "?")
        reply = result["messages"][-1].content
        print(f"  [routed → {route}]")
        print(f"bot> {reply}\n")


if __name__ == "__main__":
    main()
