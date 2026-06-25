# 08 — Retrieval Precision & Out-of-Scope Rejection

> Roadmap: **M8** · Code: [app/rag/retriever.py](../../app/rag/retriever.py), [app/tools/kb.py](../../app/tools/kb.py), [app/config.py](../../app/config.py), [app/agents/faq_rag.py](../../app/agents/faq_rag.py) · Eval: [app/eval/test_retrieval_precision.py](../../app/eval/test_retrieval_precision.py)

## TL;DR

Naive top-k retrieval **always returns k chunks**, even for a question the KB can't answer —
so the model grounds a confident reply on the least-irrelevant junk it could find. A
**relevance-score threshold** fixes this: keep a chunk only if its similarity score clears a
floor; if nothing clears it, return *nothing* so the agent **declines** instead of inventing.
This is retrieval **precision** (is what came back actually relevant?) as opposed to **recall**
(did the right chunk come back at all?).

## Why this matters — recall isn't the whole story

[07 — Evaluation](07-evaluation.md) measured **recall**: for an in-scope question, is the gold
chunk in the top-k? On this KB that scored 100% even @1. But recall says nothing about what
happens when the question is *out of scope*. "What's the weather in Paris?" has no gold chunk —
yet a top-k retriever still returns the 3 nearest policy chunks, and a naive agent will dutifully
answer from them. That's a **precision** failure, and it's the classic way RAG systems produce
confident nonsense.

```
RECALL question:    in-scope query → did the right chunk come back?   (M6, 07)
PRECISION question: out-of-scope query → did we correctly return NOTHING?  (M8, here)
```

## The mechanism — a score floor

Chroma exposes `similarity_search_with_relevance_scores(query, k)` → `(Document, score)` pairs,
score in 0..1 (higher = closer). The gate is one comparison:

```python
scored = store.similarity_search_with_relevance_scores(query, k=k)
return [(doc, s) for doc, s in scored if s >= threshold]   # empty list = "no answer"
```

[retrieve_relevant()](../../app/rag/retriever.py) does exactly this. An empty result is the
signal the tool turns into a decline.

## Tuning the threshold — measure first, then cut

You don't guess the floor — you **measure the two populations** and put the threshold in the gap.
[test_retrieval_precision.py](../../app/eval/test_retrieval_precision.py) scores every in-scope
question (`retrieval.json`) and every off-topic one (`retrieval_negative.json`) and prints them:

```
lowest in-scope   = 0.564
highest off-topic = 0.507   → any threshold in (0.507, 0.564) splits them cleanly
avg in-scope = 0.654   avg off-topic = 0.434
```

The chosen floor (`RAG_RELEVANCE_THRESHOLD = 0.53` in [config.py](../../app/config.py)) sits
inside that gap — env-tunable, like the refund threshold. The test asserts the **averages** are
well separated (not a perfect cut), so it won't go flaky when a future doc narrows the gap.

## The precision/recall tradeoff (the whole point)

The threshold is a knob, not a magic line:
- **Too high** → real-but-weak questions get wrongly rejected (false negatives). `code-warranty`
  ("What is WRTY-2YR?") scores only 0.564 — a floor of 0.58 would reject a legitimate question.
- **Too low** → off-topic questions sneak through (false positives). `gift wrapping` scores 0.507;
  a floor of 0.50 would let it ground an answer on irrelevant chunks.

0.53 is chosen to catch the borderline `gift wrapping` case while still admitting `code-warranty`.
That deliberate placement *is* the engineering.

## Two decline paths (a subtle but important detail)

The "I can't help, but here's what I can do" behavior had to be wired in **two** places, because
the agent can refuse at two different moments:

1. **Tool-level** — the question triggers `search_kb`, the gate returns empty, and the
   [NO_MATCH](../../app/tools/kb.py) message instructs the agent to decline + redirect. (Plausible
   but uncovered questions, e.g. "gift wrapping".)
2. **Agent-level** — for blatantly off-topic input ("weather", "math") the model declines straight
   from its [system prompt](../../app/agents/faq_rag.py) and **never calls the tool**, so NO_MATCH
   never runs. The redirect instruction must also live in the system prompt.

Both now give the same warm response: decline politely, then invite the customer to ask about
orders, shipping, returns/refunds, or product/policy questions. Good support UX beats a dead-end
"I don't have that information."

## Key terms

| Term | Meaning |
|---|---|
| **Recall** | Of the chunks that *should* come back, how many did? (Did we find it?) |
| **Precision** | Of the chunks that *came back*, how many are actually relevant? (Is it junk?) |
| **Relevance score** | Chroma's 0..1 similarity for a chunk vs the query; higher = closer. |
| **Threshold / floor** | Minimum score to count a chunk as relevant; below it → treat KB as empty. |
| **Out-of-scope rejection** | Returning "no answer" for a question the KB doesn't cover. |
| **False positive / negative** | Off-topic let through / in-scope wrongly rejected — the threshold trades one for the other. |

## Interview Q&A

**Q: Your RAG retriever has 100% hit-rate. Is retrieval solved?**
No — hit-rate is *recall*, measured only on in-scope questions. It says nothing about precision:
what the retriever does with a question the KB can't answer. Top-k always returns k chunks, so an
out-of-scope question still gets grounded on irrelevant text. You need a relevance threshold to
return "no answer."

**Q: How do you stop a RAG system from answering questions outside its knowledge base?**
Score-threshold the retrieval: keep a chunk only if its similarity clears a floor; if none do,
return nothing and have the agent decline. Tune the floor by measuring score distributions of
in-scope vs out-of-scope questions and placing it in the gap.

**Q: How do you pick the threshold value?**
Empirically. Score a labeled in-scope set and an off-topic set, look at the separation. Put the
floor between the lowest in-scope and highest off-topic score. If they overlap, you're choosing a
precision/recall tradeoff, not a clean cut.

**Q: What's the cost of setting it too high vs too low?**
Too high → false negatives: legitimate but weakly-matching questions get rejected. Too low → false
positives: off-topic questions slip through and get answered from irrelevant chunks. It's the
classic precision/recall dial.

**Q: Recall vs precision in retrieval, concretely?**
Recall = did the gold chunk come back for an in-scope query (hit-rate@k). Precision = is what came
back actually relevant, including correctly returning *nothing* for out-of-scope queries.

## Gotchas

- **Score semantics vary.** `similarity_search_with_relevance_scores` normalizes to 0..1 (higher =
  better); raw `similarity_search_with_score` often returns a **distance** (lower = better). Don't
  threshold the wrong direction.
- **Thresholds aren't portable.** A floor tuned for `gemini-embedding-001` won't transfer to a
  different embedding model — re-measure after any embedding change.
- **Keep the recall eval unthresholded.** [get_retriever()](../../app/rag/retriever.py) stays
  gate-free so the M6 recall test measures pure retrieval; only the production `search_kb` path
  gates. Don't let the precision knob contaminate the recall measurement.
- **Two decline paths** (tool-level + agent-level) — fixing only one leaves the other giving a
  dead-end refusal.

## Related

- [03 — RAG](03-rag.md) (the base retrieve-and-ground pipeline this hardens)
- [07 — Evaluation](07-evaluation.md) (recall hit-rate; this adds the precision dimension)
- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (`search_kb` is the tool being gated)
