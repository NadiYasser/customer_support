"""Knowledge-base ingestion (M2).

Loads markdown docs from app/data/kb/, chunks them, embeds with Gemini, and
stores the vectors in a local Chroma collection. Run once (or when KB changes)
before the FAQ/RAG agent can retrieve.
"""
# TODO(M2): load kb/*.md -> chunk -> Gemini embeddings -> Chroma collection.
