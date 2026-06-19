"""Knowledge-base ingestion (M2).

The "write" half of RAG. Four stages, kept deliberately separate so each is visible:

    load   :  kb/*.md files            -> raw markdown text
    split  :  text                     -> chunks (one per ## section)
    embed  :  chunks                   -> vectors (Gemini)
    store  :  vectors                  -> local Chroma collection

Run once (or whenever the KB changes) before the FAQ/RAG agent can retrieve:

    python -m app.rag.ingest
"""
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter

from app.config import CHROMA_DIR, KB_COLLECTION, get_embeddings

KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb"

# We split on markdown headers: each "# Title" / "## Section" becomes its own chunk,
# and the header text is captured into the chunk's metadata so a retrieved chunk
# knows which policy + section it came from (visible provenance).
#
# NOTE — this works because our KB is clean markdown. For PDFs/HTML/docx you would
# first run a document *loader* (e.g. PyPDFLoader) to extract text, then fall back to
# a RecursiveCharacterTextSplitter, since header structure rarely survives extraction.
_HEADERS = [("#", "doc"), ("##", "section")]


def load_and_split() -> list[Document]:
    """Load every kb/*.md file and split it into per-section chunks."""
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS)
    chunks: list[Document] = []
    for md_path in sorted(KB_DIR.glob("*.md")):
        text = md_path.read_text(encoding="utf-8")
        for chunk in splitter.split_text(text):
            # Record the source file too, alongside the header metadata.
            chunk.metadata["source"] = md_path.name
            chunks.append(chunk)
    return chunks


def ingest() -> int:
    """Run the full pipeline; return the number of chunks stored."""
    chunks = load_and_split()

    # embed + store: Chroma embeds each chunk via get_embeddings() and persists the
    # vectors under CHROMA_DIR. Reusing the same dir/collection means a re-run adds
    # to the existing collection — fine for this learning build.
    Chroma.from_documents(
        documents=chunks,
        embedding=get_embeddings(),
        collection_name=KB_COLLECTION,
        persist_directory=CHROMA_DIR,
    )
    return len(chunks)


if __name__ == "__main__":
    n = ingest()
    print(f"Ingested {n} chunks into Chroma collection '{KB_COLLECTION}' at '{CHROMA_DIR}/'.")
