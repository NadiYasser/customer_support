# 11 — Semantic Caching

> Roadmap: **M11** · Code: [app/cache/semantic_cache.py](../../app/cache/semantic_cache.py), [app/agents/faq_rag.py](../../app/agents/faq_rag.py), [app/config.py](../../app/config.py), [app/streaming.py](../../app/streaming.py) · Eval: [app/eval/test_semantic_cache.py](../../app/eval/test_semantic_cache.py)

## TL;DR

A normal cache keys on the **exact string**, so `"what is your return policy?"` and
`"what's the return policy?"` are different keys and never share an answer. A **semantic
cache** keys on **meaning**: embed the question into a vector and compare it (cosine
similarity) against questions we've already answered. If the closest stored question clears a
threshold, **reuse its answer** — skipping retrieval *and* the LLM call. It's embedding reuse
for latency and cost.

## Why a semantic cache (and not a plain dict)

Support traffic is full of near-duplicate questions worded differently. An exact-match cache
hits ~never on natural language — one extra word or contraction and you miss. Keying on the
*embedding* turns "same meaning, different words" into "nearby vectors," which is exactly what
embeddings are for. The same Gemini embeddings we already use for RAG ([03](03-rag.md)) do
double duty here.

```
plain cache:    hash("what's the return policy?")  != hash("what is your return policy?")  → MISS
semantic cache: cos( emb("what's the return policy?"), emb("what is your return policy?") ) = 0.79 ≥ 0.70 → HIT
```

## The mechanism — cosine similarity over stored questions

[SemanticCache](../../app/cache/semantic_cache.py) keeps three parallel lists: question
embeddings, the questions, and their answers. Lookup is one embed + a max over cosine
similarities:

```python
query_vec = embed(question)
sims = [cosine(query_vec, v) for v in self._vectors]
best = argmax(sims)
return self._answers[best] if sims[best] >= threshold else None   # None = "go run the agent"
```

We compute cosine **by hand** (numpy) so the matching math is on the page, not hidden in a
vector-DB call. Cosine = `dot(a,b) / (‖a‖·‖b‖)`. The normalization matters: **Gemini embeddings
are not unit length**, so a raw dot product would conflate "similar direction" with "long
vector." Dividing by both norms isolates direction = meaning.

## Where the check lives — *before* the expensive work

The whole point of a cache is to skip the costly path, so the check has to run **before**
retrieval and the LLM. [faq_rag_node](../../app/agents/faq_rag.py) wraps the agent:

```
question → cache.get(question)
              hit  → return cached answer            (no retrieval, no LLM)
              miss → faq_rag_agent.invoke(...) → cache.put(question, answer) → return it
```

On a hit we never enter the agent loop. On a miss the normal loop runs untouched and we *learn*
its answer for next time. The graph node is swapped from the bare agent to this wrapper in
[graph.py](../../app/graph.py).

## Scope: FAQ/RAG only (and why that's not arbitrary)

Caching is safe **only** where the same question deserves the same answer and reuse has no side
effects. That's the FAQ/RAG path: answers are grounded in **static policy text**.

The other agents are deliberately *not* cached:
- **Tracking / refund / modify** answers depend on **live, per-customer state** (`order_id`,
  balances, current status) — a cached "your order shipped" would go stale.
- **Refund / modify** also **mutate** the store. A cache hit would skip a real refund or
  address change — serving a stale confirmation for an action that never happened.

So the cache sits on the one read-only, state-independent path. This is the same
"know what's safe to reuse" judgment behind idempotency keys and HTTP cache-control.

## Tuning the threshold — measure, don't guess

Same discipline as the M8 relevance floor ([08](08-retrieval-precision.md)): measure two
populations and put the threshold in the gap.
[test_semantic_cache.py](../../app/eval/test_semantic_cache.py) scores paraphrases that
*should* reuse a seed answer against different-topic questions that should *not*:

```
min should-hit  = 0.726   (lowest paraphrase similarity)
max should-miss = 0.674   (highest different-topic similarity)
→ any threshold in (0.674, 0.726] splits them;  SEMANTIC_CACHE_THRESHOLD = 0.70
```

The gotcha worth remembering: a naive **"0.9 means very similar"** guess would make the cache
**never fire** — Gemini embeddings sit in a narrow band where even unrelated questions score
~0.6 and true paraphrases only ~0.73. The usable gap is small, and you only find it by
measuring. The eval fails loudly if embeddings drift and the gap closes, instead of silently
serving wrong answers.

## The cost/correctness tradeoff (the dial)

- **Too low** → **false hit**: serve the return-policy answer to a shipping question. This is
  the *dangerous* direction — a wrong answer, confidently cached.
- **Too high** → **false miss**: paraphrases don't match, every question pays full
  retrieval + LLM cost, the cache is dead weight.

A cache trades a small risk of a wrong reuse for latency/cost. Measured payoff here: a cached
paraphrase returns in **~0.7s vs ~3.3s** for a live run (~5×), with zero LLM tokens spent.

## Two cache surfaces (mirror the guard pattern)

Like the M10 input guard ([10](10-guardrails.md)), the cache must be applied on **both**
answer surfaces, because the streaming path bypasses the compiled graph:
1. **Graph path** — [faq_rag_node](../../app/agents/faq_rag.py) for `/chat`.
2. **Streaming path** — [stream_answer](../../app/streaming.py) checks the same `faq_cache`
   before streaming; on a hit it yields the stored answer in **one piece** (it's already known —
   there are no real tokens to stream).

Both share the one process-wide `faq_cache` instance, so a question answered on `/chat` is
served from cache on `/chat/stream` and vice-versa.

## Key terms

| Term | Meaning |
|---|---|
| **Semantic cache** | Cache keyed on embedding similarity, not exact string match. |
| **Cosine similarity** | `dot(a,b)/(‖a‖·‖b‖)`; 1 = same direction/meaning, 0 = unrelated. |
| **Threshold** | Minimum similarity to reuse a cached answer; below it → run the agent. |
| **False hit / miss** | Reuse a wrong answer / fail to reuse a valid one — the threshold trades them. |
| **Cache-safe** | A response that's deterministic for the input and side-effect-free (FAQ, not refund). |

## Interview Q&A

**Q: What is a semantic cache and how does it differ from a normal cache?**
A normal cache keys on an exact key (string/hash), so paraphrases miss. A semantic cache embeds
the input and matches by vector similarity, so "same meaning, different words" hits. You reuse a
stored answer when the nearest cached question clears a similarity threshold.

**Q: How do you decide what's safe to cache?**
Only cache responses that are deterministic for the input and have no side effects. FAQ/policy
answers (grounded in static text) qualify. Anything depending on live state (order status) or
that mutates the system (refunds) does not — a cache hit there serves stale data or skips a real
action.

**Q: How do you pick the similarity threshold?**
Empirically. Score paraphrases (should-hit) and different-topic questions (should-miss), and put
the threshold in the gap between the lowest hit and highest miss. Don't assume "0.9 = similar" —
the usable band depends entirely on the embedding model. For Gemini here the gap was
(0.674, 0.726], so 0.70.

**Q: What's the failure mode of setting it too low?**
A false hit: serving a cached answer to a genuinely different question. That's worse than a miss
because it's a *wrong* answer delivered confidently. The conservative bias is toward a slightly
higher threshold (more misses, fewer wrong reuses).

**Q: Why compute cosine instead of a plain dot product?**
Gemini embeddings aren't unit-normalized, so a dot product mixes vector *length* into the score.
Cosine divides by both norms, comparing pure direction — which is what encodes meaning.

## Gotchas

- **Thresholds aren't portable.** 0.70 is tuned for `gemini-embedding-001`. A different
  embedding model has a different band — re-measure after any embedding change (same caveat as
  the M8 floor).
- **Don't assume "0.9 = similar."** Many embedding models (Gemini included) compress everything
  into a narrow high range; a 0.9 floor can make the cache never fire. Always measure.
- **Cache only side-effect-free paths.** Caching the refund agent would skip real refunds. The
  scope restriction is correctness, not laziness.
- **Two surfaces.** The streaming path bypasses the graph, so the cache (like the guard) must be
  mirrored there or streamed FAQ answers silently skip it.
- **In-memory, lost on restart.** Fine for a learning build; production would persist (e.g. in
  Chroma) and evict by age/size. There's also no invalidation — if KB policy changes, stale
  cached answers survive until restart. A real system ties cache lifetime to KB version.

## Related

- [03 — RAG](03-rag.md) (same embeddings; the path being cached)
- [08 — Retrieval precision](08-retrieval-precision.md) (same measure-the-gap threshold discipline)
- [10 — Guardrails](10-guardrails.md) (same "mirror it on the streaming surface" pattern)
