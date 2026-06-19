"""Model + environment config (M1, extended in M2).

Loads secrets from .env.dev and builds the shared models. Centralized here so
every agent/pipeline uses the same configured model + embeddings instead of
constructing its own.
"""
import os

from dotenv import load_dotenv
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_groq import ChatGroq

# Load .env.dev into environment variables (GROQ_API_KEY, GOOGLE_API_KEY).
load_dotenv(".env.dev")

# Must be a tool-calling model. We use openai/gpt-oss-120b on Groq: it serializes
# tool calls reliably. (llama-3.3-70b-versatile works too but intermittently emits
# malformed tool calls -> Groq 400 tool_use_failed, which is why we switched.)
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Gemini embedding model used to turn KB text + queries into vectors (M2 RAG).
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")

# Where the local Chroma vector store lives, and the collection name inside it.
# ingest.py writes here; retriever.py reads here — they must agree on both.
CHROMA_DIR = "chroma_db"
KB_COLLECTION = "knowledge_base"

# M5 HITL: refunds at/above this amount pause for human approval (interrupt()).
# Below it, the refund tool writes immediately. Read from env so the gate is
# tunable without code changes.
REFUND_APPROVAL_THRESHOLD = float(os.getenv("REFUND_APPROVAL_THRESHOLD", "100.0"))


def get_model() -> ChatGroq:
    """Return the shared Groq chat model.

    temperature=0 makes routing/tool decisions as deterministic as possible —
    we want the model to behave predictably, not creatively.
    """
    return ChatGroq(model=GROQ_MODEL, temperature=0)


def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Return the shared Gemini embeddings client (reads GOOGLE_API_KEY).

    The SAME embedding model must be used at ingest time and query time —
    vectors are only comparable if produced by the same model.
    """
    return GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL)
