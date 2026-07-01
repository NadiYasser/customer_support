"""M11 — semantic cache eval.

The cache's whole correctness rests on ONE number: the similarity threshold. Two
ways it can fail, and this eval measures both:

  - MISS a paraphrase (false miss): the cache is dead weight — every question pays
    full retrieval + LLM cost even when we've answered its twin.
  - HIT a different question (false hit): we serve the WRONG cached answer (the
    return-policy answer to a shipping question). This is the dangerous direction.

So we don't assert "threshold == 0.70". We measure the GAP: the lowest similarity
among questions that SHOULD reuse a seed answer, vs the highest among questions that
should NOT. A usable threshold exists only if should-hit stays above should-miss,
and the configured threshold must sit inside that gap. If embeddings drift and the
gap closes, this test fails loudly instead of silently serving wrong answers.

Calls the real Gemini embeddings (no LLM), so it needs GOOGLE_API_KEY but is far
cheaper than the routing/faithfulness evals.
"""
import json
from pathlib import Path

from app.cache.semantic_cache import SemanticCache, _cosine
from app.config import SEMANTIC_CACHE_THRESHOLD

_DATA = Path(__file__).parent / "datasets"
CASES = json.loads((_DATA / "semantic_cache.json").read_text())


def test_threshold_separates_hits_from_misses():
    """The configured threshold must sit inside the should-hit / should-miss gap."""
    cache = SemanticCache()
    embed = lambda s: cache._embeddings.embed_query(s)
    import numpy as np

    seeds = {c["id"]: np.asarray(embed(c["seed"])) for c in CASES}

    hit_sims, miss_sims = [], []
    for case in CASES:
        seed_vec = seeds[case["id"]]
        for q in case["should_hit"]:
            hit_sims.append(_cosine(seed_vec, np.asarray(embed(q))))
        for q in case["should_miss"]:
            miss_sims.append(_cosine(seed_vec, np.asarray(embed(q))))

    min_hit, max_miss = min(hit_sims), max(miss_sims)
    print(f"\nmin should-hit = {min_hit:.3f}   max should-miss = {max_miss:.3f}")
    print(f"configured threshold = {SEMANTIC_CACHE_THRESHOLD}")

    assert max_miss < min_hit, (
        f"No usable threshold: should-miss ({max_miss:.3f}) >= "
        f"should-hit ({min_hit:.3f}) — embeddings can't separate these."
    )
    assert max_miss < SEMANTIC_CACHE_THRESHOLD <= min_hit, (
        f"Threshold {SEMANTIC_CACHE_THRESHOLD} is outside the usable gap "
        f"({max_miss:.3f}, {min_hit:.3f}]."
    )


def test_cache_serves_paraphrase_and_skips_different_topic():
    """End-to-end on the SemanticCache itself: a stored seed answer is reused for a
    paraphrase but NOT for an unrelated question."""
    cache = SemanticCache()
    for case in CASES:
        cache.clear()
        sentinel = f"ANSWER::{case['id']}"
        cache.put(case["seed"], sentinel)

        for q in case["should_hit"]:
            assert cache.get(q) == sentinel, f"{case['id']}: should have hit on {q!r}"
        for q in case["should_miss"]:
            assert cache.get(q) is None, f"{case['id']}: should have MISSED on {q!r}"
