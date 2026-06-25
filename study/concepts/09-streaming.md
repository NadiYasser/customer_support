# 09 — Streaming Responses (SSE)

> Roadmap: **M9** · Code: [app/streaming.py](../../app/streaming.py), [app/main.py](../../app/main.py) (`/chat/stream`), [streamlit_app.py](../../streamlit_app.py)

## TL;DR

Streaming sends the answer **token-by-token as the model generates it**, instead of blocking
until the whole reply is done and returning it in one lump. The tokens travel to the browser over
**Server-Sent Events (SSE)** — a long-lived HTTP response where the server writes one `data: ...`
line per event — and the UI appends each token to a placeholder so the answer types itself out.

## Mental model

```
BLOCKING (/chat)                      STREAMING (/chat/stream)
─────────────────                     ─────────────────────────
invoke() the graph                    route once, then .stream() the agent
  ▼ (wait for the WHOLE reply)          ▼ (per token)
return one JSON {"reply": "..."}      yield  data: {"delta": "Items"}\n\n
  ▼                                     yield  data: {"delta": " purchased"}\n\n
client shows it all at once             ... yield data: {"done": true}\n\n
                                        ▼
                                      client appends each delta to a placeholder
```

## The gotcha that shaped the design — stream the agent, not the graph

This system's graph is `supervisor → agent`. The obvious move is
`support_graph.stream(stream_mode="messages")`. **It doesn't stream tokens.** Measured during
build: streaming the *compiled graph* yielded the agent's whole answer as **1 chunk**; streaming
the *agent node directly* yielded **46 token-chunks**. The prebuilt `create_agent` node surfaces a
*completed* message at the sub-graph boundary, flattening the per-token deltas.

So [streaming.py](../../app/streaming.py) splits the run:

1. **invoke the supervisor once** to get the route. Its output is routing JSON — it *shouldn't*
   stream to the user anyway, so buffering it is correct, not a workaround.
2. **stream the chosen agent** with `stream_mode="messages"`, forwarding only the final-answer
   tokens.

> Lesson: token streaming only works where the model's own `.stream()` is reachable. Nesting a
> streaming runnable inside another runnable can flatten its deltas at the boundary. Stream at the
> level that actually emits tokens.

## Filtering the stream

`stream_mode="messages"` yields `(chunk, metadata)` pairs. Not every chunk is answer text — we
forward a chunk **only if** all hold:
- it's an `AIMessageChunk` (not a `ToolMessage` carrying a tool result),
- it is **not** a tool-call chunk (`tool_calls` / `tool_call_chunks` empty — those are the model
  *asking* to call `search_kb`, not answering),
- its `content` is non-empty (models emit empty keep-alive chunks).

What's left is the text the user should see, token by token.

## SSE wire format

```
data: {"delta": "Items"}\n\n
data: {"delta": " purchased"}\n\n
...
data: {"done": true}\n\n
```

Each event is a `data: ` line followed by a blank line. We **JSON-encode** each payload so
newlines/quotes in the text can't break the SSE framing. FastAPI's `StreamingResponse(gen,
media_type="text/event-stream")` wraps a generator; the client reads it with
`requests.post(stream=True)` + `iter_lines()`, parses each `data:` frame, and stops on `done`.

## Memory without the graph's checkpointer

Streaming bypasses the compiled graph, so the checkpointer never sees the turn automatically.
[streaming.py](../../app/streaming.py) restores it by hand: `get_state(config)` loads prior
history before the agent runs, and `update_state(config, {...})` writes the human message + final
answer back afterward — so the streamed path keeps the same multi-turn memory as `/chat`.

## HITL + streaming don't compose (scope call)

An `interrupt()` (a paused refund) can't be expressed as a token in a text stream — the client
needs the structured `pending_approval` payload to render the approval card. So M9 streams the
**normal completion path only**; refund-style messages still go through blocking `/chat` +
`/resume`. The Streamlit client routes by a coarse keyword hint (`refund`, `money back`, ...) to
the blocking path, everything else to the stream.

## Key terms

| Term | Meaning |
|---|---|
| **SSE** | Server-Sent Events: one-way server→client stream over a long-lived HTTP response, `text/event-stream`. |
| **Token / delta** | A small piece of generated text (often a sub-word); streaming emits these as they're produced. |
| **`stream_mode="messages"`** | LangGraph mode that yields `(message-chunk, metadata)` as the LLM generates. |
| **`AIMessageChunk`** | A partial assistant message — the streaming counterpart of `AIMessage`. |
| **`StreamingResponse`** | FastAPI response that streams a generator's output instead of buffering it. |

## Interview Q&A

**Q: Why stream LLM responses?**
Perceived latency. First token shows in ~hundreds of ms instead of waiting seconds for the whole
answer; the user sees progress immediately. Same total time, far better UX.

**Q: SSE vs WebSockets for this?**
LLM output is one-way server→client, which is exactly SSE's shape — simpler, plain HTTP, auto
-reconnect. WebSockets are bidirectional and heavier; overkill unless the client streams up too.

**Q: You stream a multi-node graph but get one chunk, not tokens. Why?**
A nested runnable (here a prebuilt agent node) surfaced its result as a completed message at the
sub-graph boundary, flattening the deltas. Fix: stream the node that actually emits tokens (the
agent) directly, not the outer graph.

**Q: How do you avoid streaming tool-call JSON / routing noise to the user?**
Filter the stream: forward only non-empty `AIMessageChunk`s that aren't tool-call chunks, and run
the structured-output router with a blocking invoke rather than streaming it.

**Q: How does memory survive if streaming bypasses the checkpointer?**
Load history with `get_state` before the run and persist the turn with `update_state` after — or
re-enter the graph. Don't silently drop the turn, or the next message loses context.

## Gotchas

- **Buffering kills streaming.** A proxy, or a generator that accumulates before yielding, makes
  the whole thing arrive at once. Yield each delta immediately; `media_type` must be
  `text/event-stream`.
- **JSON-encode payloads.** Raw text with newlines breaks SSE's line framing.
- **Always send a terminal event** (`done`) so the client knows when to stop reading.
- **Empty chunks.** Models emit content-less chunks; skip them or the UI flickers.
- **HITL can't ride the token stream** — keep interrupt()-able actions on the blocking path.

## Related

- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (the tool-call chunks we filter out)
- [02 — Orchestration](02-multi-agent-orchestration.md) (why the supervisor route is fetched before streaming)
- [04 — State & memory](04-state-and-memory.md) (get_state/update_state to keep memory off-graph)
- [05 — Human-in-the-loop](05-human-in-the-loop.md) (why HITL stays on the blocking path)
