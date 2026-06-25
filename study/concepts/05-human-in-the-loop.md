# 05 — Human-in-the-Loop (HITL)

> Roadmap: **M5** · Code: [app/tools/refund.py](../../app/tools/refund.py), [app/main.py](../../app/main.py), [app/agents/refund.py](../../app/agents/refund.py)

## TL;DR

Some actions are too risky to let an agent do unsupervised (here: large refunds). HITL
**pauses the graph mid-run** right before the risky write, surfaces the proposed action to a
human, and only continues — executing the write — once a human approves via a separate call.

## Mental model

```
/chat: "refund order 1003 for $120"
   ▼
refund agent decides → process_refund(order_id=1003, amount=120)
   ▼
amount >= threshold?
   ├── no  → write immediately, return confirmation
   └── yes → interrupt(payload)  ──► graph CHECKPOINTS & PAUSES
                                      /chat returns {status: "pending_approval", ...}
                                          ⏸  (human reviews)
   POST /resume {thread_id, approved: true}
   ▼
Command(resume={"approved": true}) → interrupt() RETURNS that value
   ▼
approved? → do the repository write → confirmation
```

## How `interrupt()` works

[tools/refund.py](../../app/tools/refund.py):

```python
if amount >= REFUND_APPROVAL_THRESHOLD:
    decision = interrupt({          # pauses the WHOLE graph; checkpoints state
        "action": "process_refund", "order_id": order_id,
        "amount": amount, "reason": "...needs human approval.",
    })
    if not decision.get("approved"):
        return "...declined by a human reviewer. No refund was processed."

order = _orders.process_refund(order_id, amount)   # the actual write — AFTER the gate
```

- `interrupt(payload)` **checkpoints the state and stops execution**. The `invoke()` call
  returns early with an `__interrupt__` field instead of a final answer.
- Later, `invoke(Command(resume=value))` on the **same thread_id** makes that paused
  `interrupt()` call **return `value`**, and execution picks up from exactly there.

## The endpoints

[main.py](../../app/main.py) splits the flow across two calls:

- `/chat` runs the graph. If it paused, `result["__interrupt__"]` is present → respond with
  `status: "pending_approval"` and the proposed action (no answer yet).
- `/resume {thread_id, approved}` calls `invoke(Command(resume={"approved": ...}))` on the
  **same thread_id**, so the checkpoint holding the pending refund is the one that continues.

This is why HITL needs the **same checkpointer as memory** ([04](04-state-and-memory.md)) —
the pause is just a saved snapshot you resume from.

## The subtle correctness point: why the write comes AFTER interrupt

On resume, LangGraph **re-runs the paused node from its start**. Already-resolved
`interrupt()` calls return their cached decision instead of pausing again — but **any code
before the interrupt runs a second time**. Putting the repository write *after* the gate
guarantees the mutation happens **exactly once**, only on approval — never while paused, never
on denial.

> Rule of thumb: in an interruptible node, **side effects go after the interrupt**, because
> everything before it is replayed on resume.

## Interview Q&A

**Q: What is human-in-the-loop and when do you use it?**
A pause point where a human approves/edits/rejects before the agent takes a consequential
action — refunds, sending money, irreversible writes, anything high-stakes. Use it wherever an
agent mistake is expensive and hard to undo.

**Q: How is the pause implemented technically?**
The framework checkpoints graph state and returns control to the caller (`interrupt()`).
Resuming replays from that checkpoint with the human's decision injected as the interrupt's
return value (`Command(resume=...)`).

**Q: Why does resume need the same thread_id?**
The pending state lives in the checkpoint keyed by thread_id. Resuming a different thread would
load the wrong (or empty) snapshot. Same id = continue the exact paused run.

**Q: A node that mutates a DB gets interrupted before the write, then resumed. Any risk of a
double write?**
Only if the write is before the interrupt — because the node replays from the start on resume.
Put side effects after the interrupt so they run exactly once, on approval.

**Q: Why build memory before HITL?**
Both rely on the same checkpointer. Once persistence exists, the interrupt is just "pause at a
saved state and resume" — no new infrastructure.

## Gotchas

- **Side effects before `interrupt()` replay** on resume — classic double-execution bug.
- **Threshold tuning**: gate too low = approval fatigue; too high = risky autonomy. Here it's
  env-configurable (`REFUND_APPROVAL_THRESHOLD`).
- **The pause is a real stored state** — a stale/abandoned approval sits in the checkpoint
  until resumed; production needs timeouts/expiry.
- **Security**: `/chat` and `/resume` are unauthenticated in this learning build — they can
  trigger refunds. Add auth before any real exposure.

## Related

- [04 — State & memory](04-state-and-memory.md) (the checkpointer this is built on)
- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (the gate lives inside a tool)
