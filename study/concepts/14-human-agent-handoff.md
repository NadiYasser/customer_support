# 14 — Human-Agent Handoff (Takeover)

> Roadmap: **M14** · Code: [app/state.py](../../app/state.py), [app/main.py](../../app/main.py), [streamlit_app.py](../../streamlit_app.py)

## TL;DR

**Takeover** is the bot→human escalation every real support console has: the agent
handles a conversation until a human decides to step in, at which point the agent goes
**silent** so it doesn't talk over the human, and the admin replies by hand — until they
**release** the thread back to the agent. It's distinct from HITL approval
([05](05-human-in-the-loop.md)): HITL pauses *one risky action* mid-run; takeover mutes the
*whole agent* for a conversation, indefinitely, at the operator's discretion.

## Mental model — a per-conversation mute switch that lives in graph state

The switch is one boolean, `muted`, added to `SupportState`. The key design question is
*where it lives*, and the answer teaches the whole mechanism: it lives in the **graph state**,
persisted by the checkpointer per `thread_id` — the same place the message history lives.

```
customer message ─► webhook ─► get_state(thread_id).muted?
                                   │
                    muted=True ────┤   record message into state, DON'T run agent
                                   │
                    muted=False ───┘   run agent as normal, send reply
```

Because it's checkpointed, takeover survives restarts and is naturally per-customer: muting
`wa:212...` has no effect on `wa:634...`. It's a plain bool with no reducer, like `blocked`
([10](10-guardrails.md)) — but with the opposite lifetime. `blocked` is *recomputed every
turn*; `muted` must *persist* until the admin flips it. It persists precisely because the
checkpointer restores the full state each turn and **no graph node writes it** — only the
admin endpoint does, via `update_state`.

## Why record the message but not run the agent

When muted, the webhook still appends the customer's incoming message to state
([main.py](../../app/main.py)) — it just skips `graph.invoke`. Two reasons:

1. The admin needs to **see** what the customer said (it shows in the console transcript).
2. If the thread is later **released**, the agent resumes with the *full* history, including
   everything said during takeover — so it doesn't answer blind.

This is the same "capture context even when you don't act on it" discipline behind the async
HITL pending store ([13](13-channel-adapters-async-hitl.md)).

## The admin surface — the dashboard never touches the graph directly

All state changes go through API endpoints ([main.py](../../app/main.py)); the Streamlit
console is a pure HTTP client. This keeps the **graph the single owner** of conversation
state (same boundary discipline as the channel adapter):

| Endpoint | Purpose |
|---|---|
| `GET /admin/threads` | list WhatsApp conversations (enumerate `wa:` threads from the checkpointer) + preview + muted flag |
| `GET /admin/threads/{id}` | full transcript + muted state for the open thread |
| `POST /admin/mute` | toggle takeover (`update_state({muted})`) |
| `POST /admin/send` | admin reply: `send_text` over WhatsApp **and** record it in state, tagged `name="admin"` |

### Telling admin from agent in the transcript

Both an admin reply and an agent reply are `AIMessage` objects. To render them differently,
admin messages are tagged with `name="admin"` when recorded; `_role_of` reads that tag to
split `customer` / `agent` / `admin`. Tool-call turns and `ToolMessage` results are filtered
out — an operator monitors the *human-facing* chat, not the internal tool plumbing.

## Auto-refresh — monitoring means the screen updates itself

Monitoring is worthless if you have to click to see new messages. The console body is a
`@st.fragment(run_every=4)` ([streamlit_app.py](../../streamlit_app.py)): every 4 seconds
Streamlit re-runs *just that fragment* (not the whole script), re-polling `/admin/threads`,
the open transcript, and `/pending`. Button clicks inside it use `st.rerun(scope="fragment")`
to repaint immediately without a full-page reload.

## Key terms

| Term | Meaning |
|---|---|
| **Takeover / handoff** | A human assumes control of a conversation; the bot stops auto-replying. |
| **Mute** | The per-thread flag (`muted`) that suppresses the agent while keeping history. |
| **Release** | Flipping `muted` back off; the agent resumes with full context. |
| **Fragment** | A Streamlit region that re-runs on its own timer, independent of the page. |

## Interview Q&A

**Q: How does takeover differ from human-in-the-loop approval?**
HITL pauses a single risky *action* (a large refund) mid-run and resumes after a yes/no.
Takeover mutes the *entire agent* for a conversation for as long as the operator wants, so a
human can converse directly. One is action-scoped and automatic; the other is
conversation-scoped and operator-driven.

**Q: Where does the mute flag live and why there?**
In the graph state, persisted by the checkpointer per `thread_id`. That gives per-customer
scope and restart-survival for free, and it sits next to the message history it gates. Storing
it in a side dict would risk drifting out of sync with the conversation it controls.

**Q: Why record the customer's message when the agent is muted?**
So the admin sees it, and so the agent has complete context if the thread is released back to
it. Dropping messages during takeover would make the agent answer blind afterward.

**Q: Why do all changes go through API endpoints instead of the dashboard editing state?**
To keep the graph the single owner of conversation state. The dashboard is one of several
possible operator UIs; putting state mutation behind the API means every client goes through
the same validated path, and the graph's invariants hold regardless of client.

## Gotchas

- **`muted` must not be written by any graph node**, or a normal turn would silently clear
  takeover. Only the admin endpoint touches it.
- **In-flight HITL + takeover.** If a thread is paused at a refund `interrupt()` and then
  muted, the pause still exists in the checkpoint — muting doesn't cancel it. Resolve the
  approval (or release) to keep state clean.
- **No auth.** The admin endpoints can send messages and toggle the agent. Fine for a
  local-only learning build; real exposure needs auth in front of `/admin/*`.
- **Fragment reruns cost API calls.** Every `run_every` tick hits the API 3× (threads,
  detail, pending). Fine locally; a real deployment would widen the interval or push via
  websockets.

## Related

- [05 — Human-in-the-loop](05-human-in-the-loop.md) (action-scoped pause vs. this conversation-scoped mute)
- [13 — Channel adapters & async HITL](13-channel-adapters-async-hitl.md) (the WhatsApp threads this console monitors)
- [04 — State & memory](04-state-and-memory.md) (checkpointer per thread_id — where `muted` persists)
