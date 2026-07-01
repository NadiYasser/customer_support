# Study Notes — AI Engineering Concepts

Quick-reference notes distilled from this project. Built for **interview prep**: each
concept is a self-contained page you can read in 5 minutes, ending with likely interview
questions and answers.

## How to use this folder

- **Cramming before an interview?** Start with [flashcards.md](flashcards.md) — one-line
  Q&A across every concept. Then drill into any concept page you fumble.
- **Want to actually understand a mechanism?** Read the matching `concepts/` page. Each
  links to the real file in this repo (`Where it lives in this codebase`) so you can read
  the implementation right after the theory.
- **Reviewing the whole system?** Read the concept pages in order 01 → 11; they follow the
  build roadmap (M1 → M11) and each builds on the last.

## Concept index

| # | Concept | One-liner | Roadmap |
|---|---------|-----------|---------|
| 01 | [Agent loop & tool calling](concepts/01-agent-loop-and-tool-calling.md) | LLM decides → tool runs → result fed back → repeat until answer | M1 |
| 02 | [Multi-agent orchestration](concepts/02-multi-agent-orchestration.md) | A supervisor routes each message to one specialized agent | M3 |
| 03 | [RAG (retrieval-augmented generation)](concepts/03-rag.md) | Embed docs → store vectors → retrieve top-k → ground the answer | M2 |
| 04 | [State & memory](concepts/04-state-and-memory.md) | Graph state + checkpointer keyed by thread_id = multi-turn memory | M4 |
| 05 | [Human-in-the-loop (HITL)](concepts/05-human-in-the-loop.md) | Pause the graph at a risky action, resume after human approval | M5 |
| 06 | [Structured output](concepts/06-structured-output.md) | Force the model to return a schema, not free text | M3 (routing) |
| 07 | [Evaluation](concepts/07-evaluation.md) | Measure routing accuracy, retrieval hit-rate, faithfulness (LLM-judge) | M6 |
| 08 | [Retrieval precision & out-of-scope rejection](concepts/08-retrieval-precision.md) | Score-threshold retrieval → decline when nothing is relevant | M8 |
| 09 | [Streaming responses (SSE)](concepts/09-streaming.md) | Stream answer tokens over Server-Sent Events; render incrementally | M9 |
| 10 | [Guardrails (input safety & PII redaction)](concepts/10-guardrails.md) | Regex injection guard before the LLM + PII scrub on traces | M10 |
| 11 | [Semantic caching](concepts/11-semantic-caching.md) | Embed the question → reuse a cached answer when a near-duplicate is asked | M11 |
| 12 | _MCP (Model Context Protocol)_ — **upcoming** | Decouple tools from the agent: a server exposes tools, the agent is a client that discovers/calls them over a transport | M12 |
| 13 | [Channel adapters & async HITL](concepts/13-channel-adapters-async-hitl.md) | WhatsApp as a swappable transport; async approval via a pending store the dashboard polls | M13 |
| 14 | [Human-agent handoff (takeover)](concepts/14-human-agent-handoff.md) | Admin console monitors live threads and mutes the agent to reply by hand, then releases it | M14 |

## The system in one paragraph

A customer message hits `POST /chat`. An **input guard** runs first — a deterministic
regex check that blocks prompt-injection attempts before any LLM sees the message. A
**supervisor** then classifies it (structured output) and routes to one of five
**specialized agents**. Each agent runs an **agent loop** — calls
its tools, feeds results back, writes a grounded answer. The FAQ agent's tool does **RAG**
(retrieve KB chunks from Chroma, answer only from them). The refund agent's tool has a
**human-in-the-loop** gate: large refunds `interrupt()` the graph and wait for `/resume`.
All of this is **stateful** — a SQLite checkpointer keyed by `thread_id` gives multi-turn
memory and is also what makes resume-after-interrupt work. The FAQ agent gates retrieval on a
**relevance threshold**, so out-of-scope questions get a polite decline instead of an answer
grounded on irrelevant chunks. A **semantic cache** sits in front of the FAQ agent — a
near-duplicate question is served a stored answer by embedding similarity, skipping retrieval
and the LLM. **Evaluation** measures each layer independently, and **observability traces**
record every run — with **PII redacted** before they're logged.
