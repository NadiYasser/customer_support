# Software Overview — AI-Agent Customer Support Platform

> A learning project. The goal is to **understand agentic orchestration and RAG**, using
> e-commerce customer support as a concrete, motivating domain. Code stays simple and
> technically honest: we make the mechanics visible rather than hiding them behind
> framework magic.

---

## 1. Problem

E-commerce stores get the same support load over and over: "where's my order?", "what's
your return policy?", "refund this", "cancel that", and occasionally "your checkout page is
broken." A good support agent has to do two distinct things:

1. **Answer questions** grounded in the store's actual policies and product info — this is a
   **retrieval (RAG)** problem.
2. **Take actions** on the store's systems — look up orders, issue refunds, modify orders,
   open IT tickets — this is an **agentic tool-use** problem, and some actions are sensitive
   enough to need a **human in the loop**.

This project builds a small platform that does both, so we can learn how each piece works.

## 2. Learning goals (what this project is really for)

| Goal | The mechanism we'll build to learn it |
|---|---|
| **Agent loop / tool calling** | An LLM that decides which tool to call; we execute it and feed the result back until the answer is ready. |
| **Multi-agent orchestration** | A **supervisor** that routes each message to the right specialized agent. |
| **RAG** | Embed docs → store vectors → retrieve top-k → ground the answer in retrieved text. |
| **State & memory** | A graph state object + checkpointer so a conversation remembers earlier turns. |
| **Human-in-the-loop (HITL)** | Pause the graph before a risky action (large refund) and wait for human approval. |

Everything below serves these goals. If a design choice would make a mechanism *less*
visible, we don't make it.

## 3. Tech choices (and why)

| Area | Choice | Why (for learning) |
|---|---|---|
| Orchestration | **LangGraph** | Models agents as an explicit graph of nodes + state. You *see* the control flow. |
| LLM | **Groq** (`langchain-groq`) | Fast, free-ish open models. Must be a **tool-calling** model — `llama-3.3-70b-versatile` or `moonshotai/kimi-k2`. The whole design depends on tool use. |
| API | **FastAPI** | Minimal HTTP surface (`/chat`, `/resume`); easy to curl. |
| Order/ticket data | **Mocked**, behind repository interfaces | Keeps focus on agent logic, not integrations. Real Shopify/Jira can be swapped in later. |
| Vector store | **Chroma** (local) | Runs in-process, easy to inspect what was stored/retrieved. |
| Embeddings | **Gemini** | Good quality, key already available. |
| Memory | LangGraph **checkpointer** + `thread_id` | Standard way to get multi-turn memory; teaches state persistence. |
| Approval gate | LangGraph **`interrupt()`** | The idiomatic HITL primitive — pause, surface to human, resume. |

## 4. Capabilities → Agents

A **supervisor** node reads the customer message and routes it to exactly one specialized
agent. Five capabilities, five agents (the supervisor pattern makes adding a sixth a
localized change):

| # | Agent | Type | Tools | Notes |
|---|---|---|---|---|
| 1 | **FAQ / Policy (RAG)** | retrieval | `search_kb(query)` | Answers shipping/return/sizing/product questions grounded in retrieved docs. |
| 2 | **Order tracking** | read action | `get_order_status(order_id)` | Returns status, ETA, tracking number. |
| 3 | **Refund** | write action | `process_refund(order_id, amount)` | **Approval-gated** above `REFUND_APPROVAL_THRESHOLD`. |
| 4 | **Order modification** | write action | `cancel_order`, `change_address`, `initiate_return` | Same tool pattern as refund, no gate (configurable later). |
| 5 | **IT support** | write action | `create_ticket(...)` | For merchants reporting website trouble. Mocked `TicketRepository`, swappable for real Jira/Zendesk. |

## 5. Architecture

```
   POST /chat   ┌─────────────────────────┐
   POST /resume │  FastAPI app            │   thread_id identifies a conversation
   ────────────▶│  (/chat, /resume)       │
                └───────────┬─────────────┘
                            ▼
                ┌─────────────────────────┐
                │  LangGraph graph        │   state = messages + routing + pending action
                │  + checkpointer (memory)│   keyed by thread_id
                └───────────┬─────────────┘
                            ▼
                 ┌────────  Supervisor  ────────┐   routes by intent
                 ▼          ▼         ▼          ▼          ▼
              FAQ/RAG   Tracking   Refund    Modify     IT support
                 │         │         │          │          │
                 ▼         ▼         ▼          ▼          ▼
            Chroma     OrderRepo  OrderRepo   OrderRepo  TicketRepo
         (Gemini emb)            + interrupt()
                                  (HITL gate)
```

### Repo structure

```
customer_support/
├── OVERVIEW.md              # this document
├── CLAUDE.md                # persisted project intent for future AI sessions
├── pyproject.toml           # langgraph, langchain-groq, langchain-google-genai,
│                            #   chromadb, fastapi, uvicorn, pydantic, python-dotenv
├── .env.example             # GROQ_API_KEY, GOOGLE_API_KEY, REFUND_APPROVAL_THRESHOLD
├── app/
│   ├── main.py              # FastAPI: /chat, /resume, /health
│   ├── graph.py             # builds the LangGraph graph + checkpointer
│   ├── supervisor.py        # routing node (intent → which agent)
│   ├── state.py             # the graph state schema
│   ├── agents/              # one module per specialized agent
│   │   ├── faq_rag.py
│   │   ├── tracking.py
│   │   ├── refund.py        # contains the interrupt() approval gate
│   │   ├── modify.py
│   │   └── it_support.py
│   ├── tools/               # tool functions (thin wrappers over repositories)
│   ├── rag/
│   │   ├── ingest.py        # load docs → Gemini embeddings → Chroma
│   │   └── retriever.py     # top-k retrieval
│   ├── repositories/        # mocked, swappable
│   │   ├── orders.py        # OrderRepository (loads orders.json)
│   │   └── tickets.py       # TicketRepository (in-memory; real client later)
│   └── data/
│       ├── orders.json      # fake orders/customers
│       └── kb/              # FAQ/policy markdown for RAG
└── README.md
```

## 6. Data flows (the two paths worth tracing)

### A) A RAG question — "What's your return policy for sale items?"

```
/chat → supervisor routes to FAQ/RAG agent
      → agent calls search_kb("return policy sale items")
      → retriever embeds query (Gemini) → Chroma top-k → returns matching policy chunks
      → LLM writes an answer grounded ONLY in those chunks
      → response saved to conversation state (thread_id) → returned over HTTP
```

### B) A gated refund — "Refund my order #1003, it arrived damaged" (amount > threshold)

```
/chat → supervisor routes to Refund agent
      → LLM decides to call process_refund(order_id=1003, amount=120.00)
      → amount > REFUND_APPROVAL_THRESHOLD  →  graph hits interrupt()
      → graph PAUSES; /chat response says "pending human approval" + the proposed action
      → human reviews, then POST /resume {thread_id, approved: true}
      → graph RESUMES from the checkpoint, executes process_refund via OrderRepo
      → confirmation returned; conversation memory intact
```

This flow is the heart of the HITL learning goal: the graph state is checkpointed at the
interrupt, so resuming continues exactly where it paused.

## 7. Build roadmap (milestone by milestone)

We build one mechanism at a time so each is understood before the next is added.

| Milestone | What we build | What you learn | Done when |
|---|---|---|---|
| **M0 — Skeleton** | Repo structure, deps, FastAPI `/health`, stub modules, sample data | Project layout | `uvicorn app.main:app` boots, `/health` returns ok |
| **M1 — One agent + tool loop** | Order tracking agent with `get_order_status` over a LangGraph ReAct loop | The **agent loop & tool calling** | "Where's order 1001?" returns real status from `orders.json` |
| **M2 — RAG** | KB ingest → Chroma; FAQ/RAG agent with `search_kb` | **Retrieval & grounding** | A policy question returns a grounded answer citing KB text |
| **M3 — Supervisor + multi-agent** | Supervisor routing node wiring M1 + M2 + refund/modify/IT agents | **Orchestration / routing** | Mixed questions get routed to the correct agent |
| **M4 — Memory** | Checkpointer + `thread_id` end to end | **State & multi-turn memory** | "Where's my order?" → "ok refund it" works across turns |
| **M5 — HITL approval** | `interrupt()` gate on large refunds; `/resume` endpoint | **Human-in-the-loop** | Small refund auto-completes; large refund pauses then resumes via `/resume` |

> **Why memory before HITL:** LangGraph's `interrupt()` works by checkpointing the
> graph state at the pause point and resuming from it — which requires the same
> checkpointer that multi-turn memory needs. Building memory first means the HITL
> milestone lands on infrastructure that already exists, instead of introducing the
> checkpointer as a side effect of the approval gate.

> **Beyond M5.** A second roadmap in `IMPROVEMENTS.md` (M6–M12) turns this working demo
> into an AI-engineering practice vehicle: evaluation, observability, retrieval precision,
> streaming, guardrails, semantic caching, and **MCP** (M12 — moving the IT-support agent's
> tool out of process into a mock ticketing **MCP server** the agent connects to as a client).

## 8. Out of scope (for now)

- Real e-commerce / ticketing integrations (interfaces are swappable so this is additive).
- Auth/users, rate limiting, observability — not relevant to the learning goals.
- Production deployment. This runs locally.

> **Security note for later:** the FastAPI endpoints are unauthenticated in this learning
> build. If this ever moves beyond local experimentation, add authentication before
> exposing `/chat` or `/resume` — they can trigger refunds.
