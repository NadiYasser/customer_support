"""Retriever (M2, extended M8).

The "read" half of RAG. Opens the Chroma collection that ingest.py built and
returns the chunks most similar to a query.

We do NOT embed the query by hand: the Chroma object carries the same embedding
function used at ingest time, so calling the retriever embeds the query and runs
the vector similarity search for us — query and stored chunks are guaranteed to be
in the same vector space.

Two read paths, on purpose:
  get_retriever()      -> bare top-k, NO score gate. Used by the M6 recall eval,
                          whose question is "does the right chunk come back at all?"
  retrieve_relevant()  -> top-k filtered by a relevance-score floor (M8). Used by
                          the production search_kb tool, whose question is "is any
                          of this actually relevant enough to answer from?"
Keeping them separate stops the precision gate from contaminating the recall
measurement.
"""
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import (
    CHROMA_DIR,
    KB_COLLECTION,
    RAG_RELEVANCE_THRESHOLD,
    get_embeddings,
)


def _get_store() -> Chroma:
    """Open the persisted KB collection (same dir/collection ingest.py wrote)."""
    return Chroma(
        collection_name=KB_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_DIR,
    )


def get_retriever(k: int = 3):
    """Return a retriever over the persisted KB collection (top-k similarity)."""
    return _get_store().as_retriever(search_kwargs={"k": k})


def retrieve_relevant(
    query: str, k: int = 3, threshold: float = RAG_RELEVANCE_THRESHOLD
) -> list[tuple[Document, float]]:
    """Top-k chunks whose relevance score clears `threshold`.

    Returns (Document, score) pairs, highest score first, dropping anything below
    the floor. An empty list means "the KB has no relevant answer" — the signal
    the agent uses to decline instead of grounding on irrelevant text (M8).

    Scores come from similarity_search_with_relevance_scores (0..1, higher =
    closer), the same metric measured in app/eval/test_retrieval_precision.py.
    """
    scored = _get_store().similarity_search_with_relevance_scores(query, k=k)
    return [(doc, score) for doc, score in scored if score >= threshold]

