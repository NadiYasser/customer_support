# 13 — Channel Adapters & Async HITL (WhatsApp)

> Roadmap: **M13** · Code: [app/channels/whatsapp.py](../../app/channels/whatsapp.py), [app/channels/pending.py](../../app/channels/pending.py), [app/main.py](../../app/main.py), [app/config.py](../../app/config.py), [streamlit_app.py](../../streamlit_app.py)

## TL;DR

The graph only ever speaks one language: `thread_id + message → reply`. A **channel
adapter** is the thin boundary layer that translates *one specific transport* (here,
WhatsApp's Meta Cloud API) into that neutral shape, and translates replies back. Nothing
WhatsApp-specific leaks past the adapter — the supervisor, agents, and tools never learn
WhatsApp exists. The twist WhatsApp forces: it's **asynchronous**, so the human-in-the-loop
refund gate ([05](05-human-in-the-loop.md)) can no longer ride a request/response cycle — the
"under review" reply and the admin's approval become two separate events bridged by a
**pending store**.

## Mental model — the same swappable boundary, on the input side

You already isolate the *data* backend behind [repositories/](../../app/repositories/): the
agent calls `OrderRepository`, never Shopify directly. A channel adapter is the identical
idea applied to the *transport*: the webhook calls the adapter, never the Graph API directly.

```
WhatsApp (Meta) ─► /webhook/whatsapp ─► whatsapp.parse_inbound ─► (phone, text)
                                                                      │
                                                          thread_id = "wa:{phone}"
                                                                      ▼
                                                            support_graph.invoke
                                                                      │
   WhatsApp (Meta) ◄─ whatsapp.send_text ◄────────────────────── reply text
```

The dependency points one way: webhook → adapter → graph. That one-way arrow is what keeps
the graph channel-agnostic — the same compiled `support_graph` serves `/chat`, `/chat/stream`,
and WhatsApp with zero changes.

## The three things the Cloud API needs (and the three adapter functions)

WhatsApp Cloud API is a webhook + a REST send endpoint. The adapter has exactly one function
per obligation:

1. **Verification handshake** — `verify_webhook(mode, token, challenge)`. When you register
   the webhook, Meta sends a `GET` with a `hub.challenge` and the `hub.verify_token` *you*
   typed into the Meta dashboard. You echo the challenge back **only if the token matches**
   your configured secret — that match proves you own the endpoint. Mismatch → the endpoint
   returns 403.
2. **Inbound parse** — `parse_inbound(body)` digs `(phone, text)` out of Meta's deeply nested
   envelope (`entry[0].changes[0].value.messages[0]`). The *same* webhook also receives
   delivery/read receipts (a `statuses` array) and non-text messages — those return `None` so
   the webhook ignores them. Malformed bodies also return `None`, never raise: a 500 makes Meta
   **retry** the delivery, which would re-run the graph.
3. **Outbound send** — `send_text(phone, text)` POSTs to the Graph API. In **mock mode** (no
   credentials configured) it `print`s the outbound instead — so the whole flow runs locally
   with no Meta account. Flipping to real mode is purely setting env vars; the wire shape is
   already the Cloud API's.

## Phone ↔ thread_id — memory comes for free

`thread_id_for(phone)` returns `"wa:{phone}"`. Because memory ([04](04-state-and-memory.md))
is just "the checkpointer keyed by thread_id," mapping each phone to a stable thread means a
WhatsApp customer's conversation history persists and accumulates exactly like a web one —
no new memory code. The `"wa:"` prefix also lets `/resume` tell channel threads from web
threads, which is what triggers the outbound push.

## The real lesson: synchronous vs asynchronous HITL

This is the part worth internalizing. With HTTP `/chat`, the refund gate is **synchronous**:
the caller holds the connection, reads `pending_approval` straight off the response, shows it,
and calls `/resume` itself. Request and approval live on one cycle.

WhatsApp breaks that. Meta sends one POST, expects a fast 200, and closes. The reply goes out
**later**, as a separate API call. And the person who approves a refund — an admin on the
Streamlit dashboard — is a **different process arriving at a different time** than the customer
who asked. The request event and the approve event are fully **decoupled**:

```
Customer (WhatsApp) ──"refund #1003 $120"──► webhook ──► graph hits interrupt()
        ▲                                                     │
        │   "your refund is under review"  ◄──────────────────┤  (reply NOW; graph stays paused)
        │                                                     ▼
        │                                          pending store  (thread_id → proposal)
        │                                                     ▲
        │                                                     │  admin polls /pending, approves
        │                                              Streamlit dashboard
        │                                                     │  POST /resume {wa:..., approved}
        └──"refund processed" ◄── send_text ◄── /resume resumes graph ◄─┘
```

Two pieces of persistence do the bridging, and they're different things:

- The **checkpointer** ([graph.py](../../app/graph.py)) persists the *paused graph state* —
  so resuming whenever the admin gets around to it is safe. This already existed for M5.
- The **pending store** ([pending.py](../../app/channels/pending.py)) is *new*: the
  checkpointer can resume a thread but can't tell you *which* threads are waiting for a human.
  The pending store is that queryable index — `thread_id → proposal` — so the dashboard (a
  separate process) can discover and act on approvals out of band.

`/resume` gained one behavior: if the thread_id starts with `"wa:"`, after resuming it
`send_text`s the outcome back to the customer and clears the pending entry. For web threads it
behaves exactly as before.

## Where it lives

- [app/channels/whatsapp.py](../../app/channels/whatsapp.py) — the adapter (verify / parse / send).
- [app/channels/pending.py](../../app/channels/pending.py) — in-process approval queue (lock-guarded dict).
- [app/main.py](../../app/main.py) — `GET/POST /webhook/whatsapp`, `/pending`, and the `wa:` branch in `/resume`.
- [streamlit_app.py](../../streamlit_app.py) — "Inbound Channel Approvals" panel polls `/pending`, approve/deny drives `/resume`.

## Key terms

| Term | Meaning |
|---|---|
| **Channel adapter** | Boundary layer translating one transport ↔ the graph's neutral `thread_id+message` shape. |
| **Webhook** | An endpoint a provider POSTs to on an event; fire-and-forget, must return fast. |
| **Verification handshake** | One-time GET where you echo `hub.challenge` iff the verify token matches — proves endpoint ownership. |
| **Synchronous HITL** | Approver reads the pause off the same response (web `/chat`). |
| **Asynchronous HITL** | Approver is a different process at a different time; needs an out-of-band pending store. |
| **Mock mode** | Outbound sends are logged, not sent — exercise the full flow with no provider account. |

## Interview Q&A

**Q: What is a channel adapter and why isolate it?**
A thin layer that converts a specific transport (WhatsApp, Slack, SMS) into the
application's neutral message shape and back. Isolating it means the core logic (graph,
agents, tools) is transport-agnostic: adding a channel is a new adapter, not edits across the
system — the dependency points one way, channel → core.

**Q: Why does WhatsApp change the human-in-the-loop design?**
HTTP `/chat` is synchronous — the caller holds the connection and reads the pending approval
off the response. WhatsApp is asynchronous: the webhook returns immediately and the reply goes
out later, and the approver (an admin) is a different process than the requester (the
customer). So the proposed action can't live on a request/response cycle — it needs an
out-of-band pending store that the approver polls, while the paused graph waits in the
checkpointer.

**Q: The checkpointer already persists the paused graph — why add a pending store?**
The checkpointer can *resume* a known thread_id, but it gives you no *queryable list* of which
threads are currently waiting for a human. The pending store is that index, so a separate
process (the dashboard) can discover pending approvals without already knowing the thread_id.

**Q: Why must the webhook never return a 500 on a bad body?**
Meta retries webhook deliveries on non-2xx. A 500 on a malformed or duplicate callback would
make Meta resend it, re-running the graph (and potentially re-triggering side effects). So the
adapter returns `None` for anything it can't handle and the webhook answers 200 "ignored".

**Q: How does the verification handshake authenticate the webhook?**
You invent a secret verify token and configure it on both sides. Meta's GET includes that
token plus a random challenge; you echo the challenge back only when the token matches. An
attacker who doesn't know the token can't complete the handshake, so they can't register their
endpoint as yours.

## Gotchas

- **Return 200, not 500.** Status receipts, non-text messages, and malformed bodies must be
  answered 200/ignored — a 500 triggers Meta retries and re-runs the graph.
- **The customer is their own approver?** No. Per design, the *customer* only gets "under
  review"; an *admin* approves on the dashboard. Letting a `yes` from the customer drive
  `/resume` would collapse the HITL security model — the whole point is an independent human.
- **In-process pending store, single worker.** Fine for a learning build; multiple uvicorn
  workers each get their own dict. Production would back it with Redis/a table. The
  checkpointer stays the source of truth for graph state regardless.
- **Tokens expire.** Meta's temporary access tokens are short-lived; a real deployment uses a
  System User token. Mock mode sidesteps this entirely for local work.
- **Streaming path doesn't apply.** WhatsApp has no token streaming — `send_text` sends a whole
  message — so the webhook uses blocking `invoke`, not the SSE `stream_answer` path.

## Related

- [05 — Human-in-the-loop](05-human-in-the-loop.md) (the gate this makes asynchronous)
- [04 — State & memory](04-state-and-memory.md) (thread_id → checkpoint; phone maps onto it)
- [02 — Multi-agent orchestration](02-multi-agent-orchestration.md) (the channel-agnostic graph behind the adapter)
