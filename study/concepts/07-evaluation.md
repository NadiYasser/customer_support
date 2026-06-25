# 07 — Evaluation

> Roadmap: **M6** · Code: [app/eval/test_routing.py](../../app/eval/test_routing.py), [app/eval/test_retrieval.py](../../app/eval/test_retrieval.py), [app/eval/test_faithfulness.py](../../app/eval/test_faithfulness.py)

## TL;DR

You can't improve what you don't measure, and LLM systems drift with every prompt/model
change. Evaluation here measures **each layer independently** with the right method for each:
exact-match where there's a ground truth (routing, retrieval), and an **LLM-as-judge** where
there isn't (faithfulness of free-text answers).

## The three evals and why they're separate

```
message ─▶ [supervisor] ─▶ [retriever] ─▶ [generator] ─▶ answer
              │                │               │
           routing          retrieval      faithfulness
           accuracy         hit-rate@k      (LLM judge)
           (6a)             (6b)            (6c)
```

Each layer fails for different reasons, so each gets its own metric. A bad answer could be a
misroute, a missing chunk, or a hallucination — separate evals tell you **which**.

## 6a — Routing accuracy (exact match)

[test_routing.py](../../app/eval/test_routing.py). The supervisor is a **classifier**: each
dataset case is `message → expected_route`. "Hit" = predicted route equals expected.

- **Parametrized test** (one per case) → a failure names the exact misrouted message
  (`test_routing_case[refund-02]`).
- **Summary test** → overall accuracy, the single number you track across prompt changes.
- Asserts `accuracy >= 0.8` — **a floor, not a target.** Raise it as the router improves; if it
  drops below, a change regressed routing.

## 6b — Retrieval hit-rate@k (exact match on the gold chunk)

[test_retrieval.py](../../app/eval/test_retrieval.py). Measures **only retrieval**: for each
question you know the gold KB section; "hit" = that section is somewhere in the top-k chunks.
This is a **recall-style** number, independent of how any answer reads.

- Questions are **deliberately paraphrased** (not copied from docs) so you test **semantic
  vector matching**, not keyword overlap.
- Reports hit-rate@k *and the rank* of each gold chunk — rank tells you if a re-ranker would
  help.

## 6c — Faithfulness (LLM-as-judge)

[test_faithfulness.py](../../app/eval/test_faithfulness.py). Here there's **no string to
match** — "is this free-text answer supported by the retrieved chunks?" So a **second model
judges**, given (question, retrieved context, answer) + a narrow rubric, returning a
[structured verdict](06-structured-output.md) (`supported` / `score 1–5` / `reasoning`).

Critical distinctions that make the judge reliable:
- **Faithfulness ≠ helpfulness.** "I don't have that information" is **faithful** (invents
  nothing) even though unhelpful. The rubric judges grounding *only* — that narrowness is what
  makes an LLM judge trustworthy.
- **Structured verdict** makes the decision inspectable, not a vibe.
- Calls the **real** agent (retrieval + generation) + a judge model → slow, costs tokens,
  non-deterministic. That's deliberate: measuring the real system, not a mock.

## Interview Q&A

**Q: How do you evaluate an LLM/agent system?**
Decompose it and measure each stage with the right method: exact-match/accuracy where ground
truth exists (classification, retrieval), and LLM-as-judge or human review for open-ended
generation. Track aggregate metrics over time to catch regressions from prompt/model changes.

**Q: What is LLM-as-judge and when is it appropriate?**
Using a model to score another model's output against a rubric. Appropriate when outputs are
free-form (no exact answer) — faithfulness, helpfulness, tone. Make it reliable with a *narrow*
rubric and *structured* output so verdicts are consistent and inspectable.

**Q: RAG has two failure modes — how do you measure each?**
Retrieval: hit-rate@k — did the gold chunk appear in the top-k? Generation: faithfulness — given
the retrieved chunks, is every claim supported? Separating them localizes the fault.

**Q: Why paraphrase eval questions instead of copying doc text?**
Copied text tests keyword overlap, which even bad embeddings pass. Paraphrases test true
semantic matching — the thing vector search is supposed to provide.

**Q: Why assert a threshold like accuracy ≥ 0.8 in tests?**
It's a regression floor: CI fails if a change drops quality below the known-good baseline. You
raise the floor as the system improves; you don't treat it as the ceiling.

**Q: Why are these evals slow and non-deterministic, and is that OK?**
They call the real model(s), so yes. It's intentional — you're measuring the production path,
not a mock. You manage it by keeping eval datasets small and running them deliberately, not on
every commit.

## Gotchas

- **Judge bias**: an LLM judge can be lenient/inconsistent; a tight rubric + structured output
  + the faithfulness≠helpfulness split mitigate this.
- **Tiny datasets** give noisy rates — treat 0.8 on a handful of cases as directional.
- **Non-determinism**: `temperature=0` helps but doesn't fully remove variance.
- **Eval drift**: as the KB/prompts change, datasets need maintenance or they measure the wrong
  thing.

## Related

- [06 — Structured output](06-structured-output.md) (the judge's verdict schema)
- [03 — RAG](03-rag.md) (retrieval vs generation, the two halves measured here)
- [02 — Orchestration](02-multi-agent-orchestration.md) (routing = the classifier evaluated in 6a)
