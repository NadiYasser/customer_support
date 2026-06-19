"""Retriever (M2).

The "read" half of RAG. Opens the Chroma collection that ingest.py built and
returns the top-k chunks most similar to a query.

We do NOT embed the query by hand: the Chroma object carries the same embedding
function used at ingest time, so calling the retriever embeds the query and runs
the vector similarity search for us — query and stored chunks are guaranteed to be
in the same vector space.
"""
from langchain_chroma import Chroma

from app.config import CHROMA_DIR, KB_COLLECTION, get_embeddings


def get_retriever(k: int = 3):
    """Return a retriever over the persisted KB collection (top-k similarity)."""
    store = Chroma(
        collection_name=KB_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_DIR,
    )
    return store.as_retriever(search_kwargs={"k": k})
