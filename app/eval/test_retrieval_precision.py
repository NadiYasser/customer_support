"""M8 phase 1 — out-of-scope precision: measure before fixing.

M6's test_retrieval.py proved RECALL: in-scope questions retrieve the right
chunk (100% hit-rate, even @1). It says nothing about PRECISION — what the
retriever does with a question the KB CANNOT answer. Today `search_kb` always
returns its top-k chunks, so "what's the weather in Paris?" still gets grounded
on the 3 least-irrelevant policy chunks. That is the gap M8 closes.

This file does NOT assert a threshold yet (that lands in M8 step 2). It MEASURES
the signal a threshold would use: the top relevance score Chroma assigns to each
question. If in-scope questions score systematically higher than off-topic ones,
a score floor can separate them — and this test prints the numbers that tell us
where to put it.

Scores come from `similarity_search_with_relevance_scores` (0..1, higher = closer),
the same API step 2's thresholded retriever will use. Requires
`python -m app.rag.ingest` to have been run.
"""
import json
from pathlib import Path

from langchain_chroma import Chroma

from app.config import CHROMA_DIR, KB_COLLECTION, get_embeddings

DATASETS = Path(__file__).parent / "datasets"
POSITIVE = json.loads((DATASETS / "retrieval.json").read_text())
NEGATIVE = json.loads((DATASETS / "retrieval_negative.json").read_text())

# Open the collection directly: the M6 retriever returns bare Documents, but here
# we need the relevance SCORE, which only similarity_search_with_relevance_scores
# exposes. Same collection, same embeddings — just a score-carrying read path.
_store = Chroma(
    collection_name=KB_COLLECTION,
    embedding_function=get_embeddings(),
    persist_directory=CHROMA_DIR,
)


def _top_score(question: str) -> float:
    """Relevance score (0..1) of the single best chunk for a question."""
    results = _store.similarity_search_with_relevance_scores(question, k=1)
    return results[0][1] if results else 0.0


def test_out_of_scope_score_separation():
    """In-scope questions should score higher than off-topic ones — print the gap."""
    in_scores = [(c["id"], _top_score(c["question"])) for c in POSITIVE]
    off_scores = [(c["id"], _top_score(c["question"])) for c in NEGATIVE]

    min_in = min(s for _, s in in_scores)
    max_off = max(s for _, s in off_scores)

    report = ["\nTop relevance score per question (higher = more relevant):"]
    report.append("  IN-SCOPE (should be high):")
    for cid, s in sorted(in_scores, key=lambda x: x[1]):
        report.append(f"    {s:.3f}  {cid}")
    report.append("  OFF-TOPIC (should be low):")
    for cid, s in sorted(off_scores, key=lambda x: x[1], reverse=True):
        report.append(f"    {s:.3f}  {cid}")
    report.append(f"\n  lowest in-scope  = {min_in:.3f}")
    report.append(f"  highest off-topic = {max_off:.3f}")
    if max_off < min_in:
        report.append(f"  CLEAN SEPARATION — any threshold in ({max_off:.3f}, {min_in:.3f}) splits them.")
    else:
        report.append(f"  OVERLAP of {max_off - min_in:.3f} — no perfect cut; the threshold trades precision vs recall.")
    print("\n".join(report))

    # The mechanism only works if the populations are meaningfully separated. We
    # assert the AVERAGES are well apart rather than a perfect cut, because
    # borderline questions ("gift wrapping") realistically overlap the low end of
    # in-scope — and pretending otherwise would hide the real tradeoff step 2 tunes.
    avg_in = sum(s for _, s in in_scores) / len(in_scores)
    avg_off = sum(s for _, s in off_scores) / len(off_scores)
    print(f"  avg in-scope = {avg_in:.3f}   avg off-topic = {avg_off:.3f}")
    assert avg_in > avg_off + 0.1, (
        f"in-scope avg {avg_in:.3f} not clearly above off-topic avg {avg_off:.3f}; "
        "a score threshold won't reliably separate them"
    )
