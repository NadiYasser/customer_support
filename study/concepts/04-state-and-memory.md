# 04 — State & Memory

> Roadmap: **M4** · Code: [app/state.py](../../app/state.py), [app/graph.py](../../app/graph.py), [app/main.py](../../app/main.py)

## TL;DR

LLMs are **stateless** — each call forgets the last. Multi-turn memory comes from two pieces:
a **state object** that flows between graph nodes, and a **checkpointer** that snapshots that
state after every step, keyed by a `thread_id`. Same `thread_id` next turn → restore the
snapshot → the conversation continues.

## Mental model

```
turn 1 (thread "abc")          turn 2 (thread "abc")
─────────────────────          ─────────────────────
load snapshot (empty)          load snapshot (turn 1 history)  ◀── checkpointer restores
  ▼                              ▼
run graph, append messages     run graph, append more messages
  ▼                              ▼
save snapshot ──────────────▶  save snapshot
```

**Persistence + an appending reducer = memory.** Neither alone is enough.

## Piece 1 — the state object

[state.py](../../app/state.py) defines what flows between nodes. Every node is
`state -> partial update`; LangGraph merges the update back in.

```python
class SupportState(TypedDict):
    messages: Annotated[list, add_messages]   # the reducer is the magic
    route: str
```

The `Annotated[list, add_messages]` wires in a **reducer**. When a node returns
`{"messages": [reply]}`, LangGraph does **not overwrite** the list — `add_messages`
**appends**. That's how each turn piles onto history instead of clobbering it.

> A **reducer** answers: "when a node returns a value for this field, how do I combine it with
> what's already there?" Default = replace. `add_messages` = append.

## Piece 2 — the checkpointer

[graph.py](../../app/graph.py) compiles the graph **with a checkpointer**:

```python
conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
return graph.compile(checkpointer=SqliteSaver(conn))
```

- Without a checkpointer, `.invoke` starts from whatever dict you pass — **no memory**.
- With one, LangGraph **loads the saved snapshot for the call's `thread_id`** before applying
  the new input, and saves a new snapshot after each step.

**`MemorySaver` vs `SqliteSaver`:** MemorySaver keeps snapshots in an in-process dict (gone on
restart). This project uses `SqliteSaver` → snapshots persist to a file on disk, so
conversations survive a server restart.

## Piece 3 — thread_id (the conversation key)

[main.py](../../app/main.py) passes it per request:

```python
config = {"configurable": {"thread_id": req.thread_id}}
support_graph.invoke({"messages": [HumanMessage(req.message)]}, config)
```

Same `thread_id` → history accumulates. New `thread_id` → fresh conversation. The client owns
identity; the server stays stateless between calls because all state lives in the checkpoint.

## Two operational details worth knowing

- **One DB connection for the process.** The graph compiles once at import and lives as long
  as the server, so one sqlite3 connection is opened and handed to `SqliteSaver` — its
  lifetime is tied to the process.
- **`check_same_thread=False`.** uvicorn serves on a thread pool, but a sqlite3 connection is
  bound to its creating thread by default. The connection is shared across worker threads;
  SqliteSaver serializes its own writes, so it's safe.

## Interview Q&A

**Q: LLMs are stateless — how do chatbots remember?**
You persist the conversation outside the model and replay it. Here: a state object holds the
message list, a checkpointer snapshots it per `thread_id`, and each turn restores then appends.

**Q: What's a reducer and why does it matter for memory?**
A merge function for a state field. `add_messages` appends instead of overwriting, so each
node's reply adds to history. Without it, every turn would replace the whole conversation.

**Q: MemorySaver vs SqliteSaver?**
MemorySaver = in-process dict, fast, lost on restart, fine for tests. SqliteSaver = file-backed,
survives restarts, needs a managed DB connection. Same interface, different durability.

**Q: What does thread_id do?**
It's the conversation key the checkpointer uses to fetch/store the right snapshot. Same id =
continue; new id = start fresh. It's how one server multiplexes many independent conversations.

**Q: Where does this same machinery show up again?**
Human-in-the-loop. `interrupt()`/resume relies on the exact same checkpointer — that's why
memory is built *before* HITL in the roadmap. See [05](05-human-in-the-loop.md).

## Gotchas

- **No checkpointer = no memory**, silently. The graph still runs; it just forgets.
- **Forgetting the reducer** → each turn overwrites history; the bot "forgets" mid-conversation.
- **Connection threading**: file-backed savers need `check_same_thread=False` under a
  threaded server, and a connection that outlives requests.
- **Unbounded growth**: message history grows forever; real systems trim/summarize old turns
  to stay within context limits.

## Related

- [02 — Orchestration](02-multi-agent-orchestration.md) (`route` is the other state field)
- [05 — Human-in-the-loop](05-human-in-the-loop.md) (built on this same checkpointer)
