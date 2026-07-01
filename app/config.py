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

# M8 RAG precision: a retrieved chunk counts as "relevant" only if its relevance
# score (0..1, higher = closer) clears this floor. Below it we treat the KB as
# having NO answer, so the agent declines instead of grounding on irrelevant
# text. The value sits inside the measured in-scope/off-topic gap — see
# app/eval/test_retrieval_precision.py (in-scope >= 0.564, off-topic <= 0.507).
RAG_RELEVANCE_THRESHOLD = float(os.getenv("RAG_RELEVANCE_THRESHOLD", "0.53"))

# M11 semantic cache: a new question reuses a cached answer only if its cosine
# similarity to a stored question clears this floor (0..1, higher = more alike).
# Too low serves the wrong cached answer (e.g. the return-policy answer to a
# shipping question); too high never matches paraphrases and the cache is dead
# weight. Gemini embeddings sit in a NARROW band — measured paraphrases score
# >= 0.726 while different topics top out at 0.674 — so the usable gap is small and
# 0.70 sits inside it. (A naive "0.9 = very similar" guess would never fire here;
# we tuned from measurement — see app/eval/test_semantic_cache.py.)
SEMANTIC_CACHE_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.70"))


# M13 WhatsApp channel (Meta Cloud API). The adapter reads these at call time.
#   - VERIFY_TOKEN: a secret string WE invent; Meta echoes it during the webhook
#     verification handshake so we can confirm the GET came from our configured app.
#   - ACCESS_TOKEN + PHONE_NUMBER_ID: identify and authorize OUR WhatsApp business
#     number when we POST a reply to the Graph API.
# When ACCESS_TOKEN or PHONE_NUMBER_ID is unset we run in MOCK mode: inbound still
# works, but outbound messages are logged instead of sent — so the whole flow is
# exercisable locally with no Meta account.
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "dev-verify-token")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")


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
