"""M6 phase 6b — RAG retrieval hit-rate eval.

RAG has two halves that fail independently:
  retrieval  -> did the right chunk come back from the vector store?
  generation -> given those chunks, did the model write a faithful answer? (6c)

This file measures ONLY retrieval. For each question we know which KB section
should answer it; "hit" means that section appears somewhere in the top-k chunks
the retriever returns. The aggregate is hit-rate@k — a recall-style number,
independent of how any answer reads.

Questions are deliberately paraphrased (not copied from the docs) so we test
semantic vector matching, not keyword overlap.

These call the REAL retriever, which embeds the query via Gemini and hits the
persisted Chroma collection. Requires `python -m app.rag.ingest` to have been run.
"""
import json
from pathlib import Path

import pytest

from app.rag.retriever import get_retriever

DATASET_PATH = Path(__file__).parent / "datasets" / "retrieval.json"
CASES = json.loads(DATASET_PATH.read_text())

TOP_K = 3
# One retriever for the whole module: building it opens the Chroma collection, so
# we reuse it across cases instead of reopening per query.
_retriever = get_retriever(k=TOP_K)


def _retrieved_sections(question: str) -> list[str]:
    """Return the section labels of the top-k chunks for a question, in rank order."""
    docs = _retriever.invoke(question)
    return [d.metadata.get("section") for d in docs]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_retrieval_hit(case):
    """The expected section is retrieved within the top-k chunks."""
    sections = _retrieved_sections(case["question"])
    assert case["expected_section"] in sections, (
        f"{case['id']}: {case['question']!r}\n"
        f"  expected section {case['expected_section']!r} in top-{TOP_K}, "
        f"got {sections}"
    )


def test_retrieval_hit_rate():
    """Report overall hit-rate@k and the rank of each gold chunk."""
    hits = 0
    misses = []
    rank_notes = []
    for case in CASES:
        sections = _retrieved_sections(case["question"])
        expected = case["expected_section"]
        if expected in sections:
            hits += 1
            rank_notes.append(f"  {case['id']}: rank {sections.index(expected) + 1}")
        else:
            misses.append(f"  {case['id']}: expected {expected!r}, got {sections}")

    hit_rate = hits / len(CASES)
    report = [f"\nRetrieval hit-rate@{TOP_K}: {hits}/{len(CASES)} = {hit_rate:.0%}"]
    report.append("Gold-chunk ranks (hits):")
    report.extend(rank_notes)
    if misses:
        report.append("Misses:")
        report.extend(misses)
    print("\n".join(report))

    # Floor for the vector-only baseline. M8 (hybrid search + rerank) should push
    # this up; if a change drops it below, retrieval regressed.
    assert hit_rate >= 0.8
