"""Semantic cache for FAQ/RAG answers (M11).

A plain cache keys on the EXACT question string, so "what is your return policy?"
and "what's the return policy?" are different keys and never share an answer. A
semantic cache keys on MEANING: we embed each question into a vector and compare a
new question against stored ones by cosine similarity. If the closest stored
question clears SEMANTIC_CACHE_THRESHOLD, we reuse its answer — skipping retrieval
and the LLM entirely.

Why this is safe ONLY for FAQ/RAG: those answers are grounded in static policy
text, so the same question deserves the same answer and reuse has no side effects.
Order tracking / refund / modify answers depend on live per-customer state and some
MUTATE the store — caching them would serve stale data or skip a real refund. So the
cache sits on the one path where answers are stable and read-only.

Design (kept deliberately simple/visible — the project's philosophy):
  - In-memory: a parallel list of (embedding, question, answer). Lost on restart;
    that's fine for a learning build. A production cache would persist (e.g. in the
    same Chroma we already run) and evict by age/size.
  - Cosine similarity by hand with numpy, so the matching math is on the page rather
    than hidden behind a vector-DB call. Gemini embeddings are not unit-normalized,
    so we divide by the norms instead of assuming a plain dot product.
  - One shared instance (`faq_cache`) imported by the FAQ agent path.
"""
import numpy as np

from app.config import SEMANTIC_CACHE_THRESHOLD, get_embeddings


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors: dot product normalized by both norms.

    1.0 = identical direction (same meaning), 0 = orthogonal. We normalize because
    Gemini embeddings aren't unit length, so a raw dot product would conflate
    "similar direction" with "long vector".
    """
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class SemanticCache:
    """A meaning-keyed answer cache backed by question embeddings."""

    def __init__(self, threshold: float = SEMANTIC_CACHE_THRESHOLD):
        self.threshold = threshold
        self._embeddings = get_embeddings()
        self._vectors: list[np.ndarray] = []
        self._questions: list[str] = []
        self._answers: list[str] = []

    def get(self, question: str) -> str | None:
        """Return a cached answer for a semantically-similar question, or None.

        Embeds `question`, finds the most similar stored question, and returns its
        answer only if the similarity clears the threshold. None means "no close
        enough match — go run the agent."
        """
        if not self._vectors:
            return None
        query_vec = np.asarray(self._embeddings.embed_query(question))
        sims = [_cosine(query_vec, v) for v in self._vectors]
        best = int(np.argmax(sims))
        if sims[best] >= self.threshold:
            return self._answers[best]
        return None

    def put(self, question: str, answer: str) -> None:
        """Store a question→answer pair, embedding the question for future matches."""
        self._vectors.append(np.asarray(self._embeddings.embed_query(question)))
        self._questions.append(question)
        self._answers.append(answer)

    def clear(self) -> None:
        """Drop everything — used by tests for a clean slate."""
        self._vectors.clear()
        self._questions.clear()
        self._answers.clear()


# One shared cache for the FAQ/RAG path. Lives as long as the process.
faq_cache = SemanticCache()
