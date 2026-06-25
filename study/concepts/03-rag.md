# 03 — RAG (Retrieval-Augmented Generation)

> Roadmap: **M2** · Code: [app/rag/ingest.py](../../app/rag/ingest.py), [app/rag/retriever.py](../../app/rag/retriever.py), [app/tools/kb.py](../../app/tools/kb.py), [app/agents/faq_rag.py](../../app/agents/faq_rag.py)

## TL;DR

RAG = let the model answer from **your documents** instead of its memory. You embed your docs
into vectors once (ingest), then at query time embed the question, find the most similar
chunks, and put them in the prompt so the model answers **grounded** in retrieved text.

## Mental model — two halves that fail independently

```
INGEST (write, run once)                 QUERY (read, every question)
─────────────────────────                ─────────────────────────────
load  kb/*.md                            embed the question (same model!)
  ▼                                         ▼
split into chunks (per ## section)       similarity search in Chroma → top-k chunks
  ▼                                         ▼
embed each chunk (Gemini)                feed chunks to the LLM
  ▼                                         ▼
store vectors in Chroma                  LLM writes answer FROM those chunks only
```

The two halves:
- **Retrieval** — did the right chunk come back? (vector search quality)
- **Generation** — given the chunks, did the model answer faithfully without inventing?

They break for different reasons, so you [evaluate them separately](07-evaluation.md).

## The ingest pipeline (write half)

[ingest.py](../../app/rag/ingest.py) keeps four stages deliberately visible:

1. **load** — read `kb/*.md` files to raw text.
2. **split** — chunk the text. Here, `MarkdownHeaderTextSplitter` makes **one chunk per `##`
   section**, and stores the header in metadata → each retrieved chunk knows which doc/section
   it came from (**provenance**).
3. **embed** — turn each chunk into a vector with Gemini embeddings.
4. **store** — persist vectors in a local **Chroma** collection.

> For clean markdown, header-splitting works. For PDF/HTML/docx you'd first run a *loader* to
> extract text, then a `RecursiveCharacterTextSplitter`, since header structure rarely
> survives extraction.

## The retriever (read half)

[retriever.py](../../app/rag/retriever.py) opens the same Chroma collection and returns the
top-k similar chunks. Crucially, **the query is embedded with the same embedding model used at
ingest** — vectors are only comparable in the same vector space. The Chroma object carries
that embedding function, so you don't embed the query by hand.

## Making it an agent tool

[tools/kb.py](../../app/tools/kb.py) wraps the retriever as `search_kb`. The vital detail:
the tool **returns the raw retrieved chunks, not a finished answer**. The
[faq_rag agent](../../app/agents/faq_rag.py) must compose its reply *from* those chunks. Its
system prompt enforces the grounding discipline: *answer ONLY from retrieved text; if the KB
doesn't cover it, say so rather than inventing policy.*

## Key terms

| Term | Meaning |
|---|---|
| **Embedding** | A vector (list of floats) representing text's meaning; similar meaning → nearby vectors. |
| **Vector store** | DB that indexes embeddings for fast nearest-neighbor search (here: Chroma). |
| **Chunk** | A bite-sized doc piece you embed and retrieve (here: one per `##` section). |
| **top-k** | Retrieve the k most similar chunks (here k=3). |
| **Grounding** | Forcing the answer to come from retrieved text, not the model's parametric memory. |
| **Provenance** | Tracking which source/section a chunk came from (stored in metadata). |

## Interview Q&A

**Q: What problem does RAG solve?**
LLMs don't know your private/current data and hallucinate when they don't know. RAG injects
relevant source text into the prompt so answers are grounded, current, and citable — without
retraining the model.

**Q: Walk me through a RAG pipeline.**
Ingest: load → split into chunks → embed → store in a vector DB. Query: embed the question →
similarity search for top-k chunks → put them in the prompt → model answers from them.

**Q: Why must ingest and query use the same embedding model?**
Vectors are only comparable within the same model's vector space. Mismatched models → garbage
similarity → wrong chunks.

**Q: Retrieval vs generation failures — how do you tell them apart?**
Measure retrieval hit-rate (did the gold chunk appear in top-k?) separately from faithfulness
(given the chunks, was the answer grounded?). A bad answer with good chunks = generation
problem; a bad answer with missing chunks = retrieval problem.

**Q: How do you reduce hallucination in RAG?**
Return raw chunks (not pre-summarized), prompt the model to answer only from them and to admit
when info is missing, keep provenance, and evaluate faithfulness with an LLM judge.

**Q: How would you improve retrieval beyond plain vector search?**
Hybrid search (vector + keyword/BM25), re-ranking the top-k with a cross-encoder, better
chunking, query rewriting/expansion, metadata filtering.

## Gotchas

- **Chunking strategy dominates quality.** Too big = noisy/diluted; too small = lost context.
- **Stale index**: re-run ingest when the KB changes, or retrieval serves old policy.
- **Embedding model quirks**: this project uses `models/gemini-embedding-001`
  (`text-embedding-004` 404s for the key); Chroma collection names need 3+ chars.
- Re-running ingest here **adds** to the collection rather than replacing — fine for learning,
  but a real system needs upsert/dedup.

## Related

- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (`search_kb` is just a tool)
- [07 — Evaluation](07-evaluation.md) (retrieval hit-rate + faithfulness judge)
