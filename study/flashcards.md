# Flashcards — Rapid Interview Drill

Cover the answer, say yours out loud, reveal. One-liners; deep dives live in
[concepts/](concepts/). Grouped by topic.

---

## Agent loop & tool calling → [01](concepts/01-agent-loop-and-tool-calling.md)

**Q: What is an agent vs a plain LLM call?**
> An LLM in a loop with tools: it decides to call a tool, you run it, feed the result back,
> and it loops until it writes a final answer. A plain call is one prompt → one completion.

**Q: What's the ReAct pattern?**
> Reason + Act: the model alternates reasoning and tool-calling, using each observation to
> decide the next step.

**Q: How does an LLM "call" a function it can't run?**
> It emits a structured tool call (name + JSON args). The runtime matches the name, executes
> the function, appends the result. The model only requests; the harness executes.

**Q: Why does the tool docstring matter?**
> It's the only thing the model sees about the tool — it's prompt engineering. Vague docstring
> → wrong tool or bad args.

**Q: When does the loop stop?**
> When the model returns a normal message with no tool call — that message is the answer.

---

## Multi-agent orchestration → [02](concepts/02-multi-agent-orchestration.md)

**Q: What's the supervisor pattern?**
> A router node classifies each message and delegates to one specialized sub-agent. Supervisor
> owns routing; agents own doing.

**Q: Why not one agent with all the tools?**
> More tools → more wrong picks, longer prompts, harder to evaluate/extend. Specialization
> keeps each agent reliable and the system modular.

**Q: How does a routing decision become control flow?**
> Decision → written to graph state → conditional edge reads that field → dispatches to the
> matching node.

**Q: How do agents share history without clobbering it?**
> One shared state object whose `messages` field uses an append reducer (`add_messages`).

**Q: Alternatives to supervisor?**
> Swarm/network (direct hand-offs), hierarchical (supervisors of supervisors), single ReAct
> agent.

**Q: How do you stop the bot answering off-topic questions?**
> Add an `out_of_scope` label to the router's `Literal` so "none fit" is a real choice, and
> route it to a non-LLM node that returns a fixed refusal. Scope at the routing layer = one
> chokepoint, not N drifting agent prompts.

**Q: Why is the out_of_scope node not an LLM agent?**
> The model already made the only judgment (in vs out of scope); the refusal text is canned, so
> zero tokens and zero chance it answers the off-topic question anyway. A node is just
> `state -> update` — it needn't call a model. Mirror the refusal on bypass paths (streaming).

---

## RAG → [03](concepts/03-rag.md)

**Q: What problem does RAG solve?**
> LLMs don't know your private/current data and hallucinate. RAG injects relevant source text
> into the prompt → grounded, current, citable answers, no retraining.

**Q: The pipeline in one breath?**
> Ingest: load → split → embed → store. Query: embed question → top-k similarity search →
> stuff chunks in prompt → answer from them.

**Q: Why same embedding model at ingest and query?**
> Vectors are only comparable within one model's vector space. Mismatch → wrong chunks.

**Q: RAG's two independent failure modes?**
> Retrieval (wrong/missing chunks) and generation (hallucinated answer despite good chunks).
> Measure separately.

**Q: How to reduce hallucination in RAG?**
> Return raw chunks, prompt to answer only from them + admit gaps, keep provenance, eval
> faithfulness with an LLM judge.

**Q: Improve retrieval beyond plain vector search?**
> Hybrid (vector + keyword/BM25), re-ranking, better chunking, query rewriting, metadata
> filters.

**Q: How does the agent cite its source?**
> Provenance (file + section) is stored in chunk metadata at ingest and returned prefixed to
> each chunk; the agent echoes the section it used on a `Source:` line. Citation = exposing
> provenance the pipeline already tracked.

---

## State & memory → [04](concepts/04-state-and-memory.md)

**Q: LLMs are stateless — how do chatbots remember?**
> Persist the conversation outside the model and replay it: state object + checkpointer keyed
> by `thread_id`; each turn restores then appends.

**Q: What's a reducer?**
> A merge function for a state field. `add_messages` appends instead of overwriting → history
> accumulates.

**Q: MemorySaver vs SqliteSaver?**
> In-process dict (lost on restart) vs file-backed (survives restart, needs a managed
> connection). Same interface.

**Q: What does thread_id do?**
> Conversation key the checkpointer uses to load/save the right snapshot. Same id = continue;
> new id = fresh.

**Q: persistence + reducer = ?**
> Multi-turn memory. Neither alone is enough.

---

## Human-in-the-loop → [05](concepts/05-human-in-the-loop.md)

**Q: What is HITL, when do you use it?**
> A pause where a human approves before a consequential action (refunds, irreversible writes).
> Use it where an agent mistake is expensive/hard to undo.

**Q: How is the pause implemented?**
> `interrupt()` checkpoints state and returns control to the caller. `Command(resume=value)`
> replays from the checkpoint, making interrupt() return that value.

**Q: Why must resume use the same thread_id?**
> The pending state lives in the checkpoint keyed by thread_id; resuming elsewhere loads the
> wrong snapshot.

**Q: Node mutates a DB, gets interrupted, resumes — double-write risk?**
> Only if the write is *before* the interrupt (the node replays from its start on resume). Put
> side effects *after* the interrupt → exactly once.

**Q: Why build memory before HITL?**
> Both use the same checkpointer; the interrupt is just "pause at a saved state and resume."

---

## Structured output → [06](concepts/06-structured-output.md)

**Q: What is it and why?**
> Force the model to return data matching a schema instead of prose. Use whenever a downstream
> system consumes the output — no brittle text parsing, validation for free.

**Q: How is it enforced?**
> Tool/function calling (schema = function signature) or provider-native constrained decoding
> (`json_schema`/JSON mode). Framework validates + retries.

**Q: tool-calling vs json_schema — when switch?**
> Default tool calling; switch to json_schema when tool-call serialization is flaky (e.g. Groq
> `tool_use_failed`) or you only need data, not an action.

**Q: How does it make routing reliable?**
> Constrain to a `Literal` label set → model can only return a dispatchable route, no free text
> to parse.

---

## Evaluation → [07](concepts/07-evaluation.md)

**Q: How do you evaluate an agent system?**
> Decompose and measure each stage: exact-match where ground truth exists (routing, retrieval),
> LLM-judge/human for open-ended generation. Track metrics to catch regressions.

**Q: What is LLM-as-judge, when appropriate?**
> A model scores another's output against a rubric. For free-form outputs (faithfulness, tone).
> Make reliable with a narrow rubric + structured verdict.

**Q: Measure RAG's two halves?**
> Retrieval = hit-rate@k (gold chunk in top-k?); generation = faithfulness (every claim
> supported by chunks?).

**Q: Why paraphrase eval questions?**
> Copied text tests keyword overlap; paraphrases test real semantic matching.

**Q: Why assert accuracy ≥ 0.8 in a test?**
> Regression floor — CI fails if a change drops below known-good. Raise it as the system
> improves; it's not the ceiling.

**Q: Faithfulness vs helpfulness?**
> "I don't have that info" is faithful (invents nothing) but unhelpful. Judging grounding only
> is what makes the judge reliable.

---

## Retrieval precision & out-of-scope rejection → [08](concepts/08-retrieval-precision.md)

**Q: 100% hit-rate — is retrieval solved?**
> No. Hit-rate is *recall*, measured only on in-scope questions. It ignores precision: top-k
> still returns k chunks for an out-of-scope question, so it gets answered from junk.

**Q: Recall vs precision in retrieval?**
> Recall = did the gold chunk come back for an in-scope query (hit-rate@k). Precision = is what
> came back relevant, including correctly returning *nothing* for out-of-scope queries.

**Q: How do you stop RAG answering out-of-scope questions?**
> Score-threshold retrieval: keep a chunk only if its relevance clears a floor; if none do,
> return nothing and have the agent decline.

**Q: How do you pick the threshold?**
> Empirically. Score an in-scope set and an off-topic set, place the floor in the gap between
> lowest in-scope and highest off-topic. Overlap → it's a precision/recall tradeoff, not a clean cut.

**Q: Cost of threshold too high vs too low?**
> Too high → false negatives (real-but-weak questions rejected). Too low → false positives
> (off-topic questions answered from irrelevant chunks).

**Q: Why two decline paths?**
> Tool-level (gate returns empty → NO_MATCH) for plausible-but-uncovered questions, AND
> agent-level (system prompt) for blatantly off-topic input the model refuses without ever
> calling the tool. Fix only one and the other dead-ends.

---

## Streaming (SSE) → [09](concepts/09-streaming.md)

**Q: Why stream LLM responses?**
> Perceived latency — first token in ~ms instead of waiting for the whole answer. Same total
> time, far better UX.

**Q: SSE vs WebSockets here?**
> LLM output is one-way server→client = SSE's exact shape (plain HTTP, auto-reconnect).
> WebSockets are bidirectional and heavier — overkill unless the client streams up too.

**Q: Streamed a multi-node graph but got one chunk, not tokens — why?**
> A nested runnable (prebuilt agent node) surfaced a completed message at the sub-graph
> boundary, flattening deltas. Fix: stream the agent that emits tokens, not the outer graph.

**Q: How do you keep routing JSON / tool-call chunks out of the stream?**
> Filter: forward only non-empty AIMessageChunks that aren't tool-call chunks; run the
> structured-output router with a blocking invoke, not a stream.

**Q: SSE wire format essentials?**
> One `data: {json}` line per event + blank line; JSON-encode payloads so newlines don't break
> framing; always send a terminal `done` event.

**Q: Memory when streaming bypasses the checkpointer?**
> Load history with get_state before the run, persist the turn with update_state after — or the
> next message loses context.

**Q: Why doesn't HITL compose with streaming?**
> An interrupt() (pending refund) is a structured payload, not a token — keep interrupt()-able
> actions on the blocking /chat path.

---

## Stack lightning round

**Q: Why LangGraph?**
> Models agents as an explicit graph of nodes + state — control flow is visible, not hidden
> behind framework magic.

**Q: Why a tool-calling model specifically (Groq `openai/gpt-oss-120b`)?**
> The whole design depends on tool use; this model serializes tool calls reliably.
> `llama-3.3-70b` intermittently emits malformed tool calls (`400 tool_use_failed`).

**Q: Why `temperature=0`?**
> Routing/tool decisions should be predictable, not creative.

**Q: Why Chroma?**
> Local, in-process vector store — easy to inspect what got stored/retrieved while learning.

**Q: One-sentence system description?**
> A supervisor routes each support message (structured output) to one of five specialized
> agents; each runs an agent loop over its tools; the FAQ agent does RAG; the refund agent has
> an interrupt() HITL gate; all stateful via a SQLite checkpointer keyed by thread_id; each
> layer independently evaluated.
