# 02 — Multi-Agent Orchestration (Supervisor pattern)

> Roadmap: **M3** · Code: [app/supervisor.py](../../app/supervisor.py), [app/graph.py](../../app/graph.py), [app/state.py](../../app/state.py)

## TL;DR

Instead of one giant agent with every tool, you have **many specialized agents** and a
**supervisor** that reads each message and routes it to exactly one. Each agent stays small,
focused, and easy to reason about; adding a capability is a localized change.

## Mental model

```
              START
                │
                ▼
          ┌───────────┐   classifies intent, writes state["route"]
          │ supervisor │
          └─────┬─────┘
   conditional edge reads state["route"]
        ┌────┬──┴──┬────┬────────┐
        ▼    ▼     ▼    ▼        ▼
     faq_rag track refund modify it_support
        └────┴──┬──┴────┴────────┘
                ▼
               END
```

Every turn: **classify first (supervisor), then act (one agent), then END.**

## Why supervisor instead of one mega-agent

- **Focus**: each agent has a narrow prompt + only its own tools → fewer wrong tool calls.
- **Locality**: adding a 6th capability = new agent module + one entry in the route map. You
  don't touch the other agents.
- **Debuggability**: you can see exactly which agent handled a turn, and evaluate routing
  separately from answering (see [07 — Evaluation](07-evaluation.md)).
- **Cost/latency control**: a cheap classifier picks one expensive agent, instead of stuffing
  every tool into every call.

## How routing becomes control flow

The trick is that a **decision** (which agent?) is turned into actual **graph control flow**:

1. The supervisor is a node: `state -> {"route": "refund"}`. It uses **structured output**
   (see [06](06-structured-output.md)) so the model is forced to return one of five exact
   labels — never free-form text to parse.
2. The route name is written into shared **state** ([state.py](../../app/state.py)).
3. A **conditional edge** in the graph reads `state["route"]` and dispatches to the matching
   agent node:

```python
graph.add_conditional_edges(
    "supervisor",
    _pick_route,                       # returns state["route"]
    {name: name for name in _AGENT_NODES},
)
```

`Literal["faq_rag", "tracking", "refund", "modify", "it_support"]` in the supervisor and the
keys of the route map **must agree** — that's the contract that makes routing safe.

## Shared state across agents

All agents operate on the same `SupportState`, keying on `messages` with the `add_messages`
reducer. An agent reads the conversation, appends its reply, and that update **merges** back
into shared state — no agent clobbers another's history.

## Interview Q&A

**Q: What is the supervisor / orchestrator pattern?**
A router node classifies the incoming request and delegates to one of several specialized
sub-agents, each with its own tools and prompt. The supervisor owns *routing*; the agents own
*doing*.

**Q: Why not just give one agent all the tools?**
More tools = more chances to pick the wrong one, longer prompts, harder to evaluate, harder
to extend. Specialization keeps each agent reliable and makes the system modular.

**Q: How do you make routing reliable instead of parsing model text?**
Constrain the model's output to a fixed set of labels via structured output (schema /
`with_structured_output`). The route is always a valid value the dispatcher understands.

**Q: How does a routing *decision* become a control-flow *transition*?**
The decision is written to graph state; a conditional edge reads that field and sends control
to the matching node. Decision → state field → edge → node.

**Q: How do multiple agents share conversation history without overwriting each other?**
They share one state object whose `messages` field uses an append reducer (`add_messages`),
so each agent's output is merged in, not substituted.

**Q: What are alternatives to a supervisor?**
Network/swarm (agents hand off to each other directly), hierarchical (supervisors of
supervisors), or a single ReAct agent. Supervisor is the simplest that still scales by
adding leaves.

## Gotchas

- **Route map and the `Literal` must stay in sync** — a route the model can emit but the edge
  can't dispatch is a crash.
- **One agent per turn here** — this graph routes to exactly one agent then ENDs. Multi-hop
  (agent → back to supervisor → another agent) is a different, more complex design.
- The supervisor sees only the **latest message** for classification here, which is simple but
  can misroute follow-ups that depend on prior context.

## Related

- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (what each leaf node is)
- [06 — Structured output](06-structured-output.md) (how the route is constrained)
- [04 — State & memory](04-state-and-memory.md) (the state the route lives in)
