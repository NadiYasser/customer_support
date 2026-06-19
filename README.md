# AI Customer Support Platform

An AI-agent-powered customer support platform for e-commerce. A **supervisor** agent reads
each customer message and routes it to a specialized agent that either answers from the
store's knowledge base (RAG) or takes an action (track an order, issue a refund, modify an
order, open an IT ticket). Sensitive actions like large refunds pause for human approval.

> Built as a hands-on learning project for **agentic orchestration** and **RAG**. See
> [OVERVIEW.md](OVERVIEW.md) for the full design.

## Features

- **Supervisor routing** — one node classifies intent and dispatches to the right agent.
- **FAQ / policy answers (RAG)** — retrieves relevant docs from a vector store and grounds
  the answer in them.
- **Order tracking** — looks up status, ETA, and tracking number.
- **Refunds with human-in-the-loop** — large refunds pause for approval, then resume.
- **Order modification** — cancel, change address, initiate a return.
- **IT support ticketing** — opens tickets for merchants reporting site issues.
- **Multi-turn memory** — conversations persist across turns via a checkpointer.

## Architecture

```
   POST /chat        ┌──────────────────┐
   POST /resume      │  FastAPI          │
   ─────────────────▶│  /chat /resume    │
                     └────────┬──────────┘
                              ▼
                     ┌──────────────────┐
                     │  LangGraph        │  state + memory (checkpointer)
                     └────────┬──────────┘
                              ▼
                          Supervisor          routes by intent
            ┌──────────┬──────────┬──────────┬──────────┐
            ▼          ▼          ▼          ▼          ▼
         FAQ/RAG    Tracking    Refund     Modify    IT support
            │          │          │ (HITL)    │          │
            ▼          ▼          ▼          ▼          ▼
         Chroma     OrderRepo  OrderRepo  OrderRepo  TicketRepo
```

## Tech stack

| Area | Choice |
|---|---|
| Language | Python |
| Orchestration | LangGraph (supervisor + specialized agents) |
| LLM | Groq (tool-calling model via `langchain-groq`) |
| API | FastAPI |
| Vector store | Chroma (local) |
| Embeddings | Gemini (`langchain-google-genai`) |
| Memory / HITL | LangGraph checkpointer + `interrupt()` |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in GROQ_API_KEY and GOOGLE_API_KEY
uvicorn app.main:app --reload
curl localhost:8000/health   # {"status":"ok"}
```
