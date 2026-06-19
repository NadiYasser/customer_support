"""Model + environment config (M1).

Loads secrets from .env.dev and builds the Groq chat model. Centralized here so
every agent uses the same configured model instead of constructing its own.
"""
import os

from dotenv import load_dotenv
from langchain_groq import ChatGroq

# Load .env.dev into environment variables (GROQ_API_KEY, GEMINI_API_KEY).
load_dotenv(".env.dev")

# Must be a tool-calling model. llama-3.3-70b-versatile supports tool use on Groq.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


def get_model() -> ChatGroq:
    """Return the shared Groq chat model.

    temperature=0 makes routing/tool decisions as deterministic as possible —
    we want the model to behave predictably, not creatively.
    """
    return ChatGroq(model=GROQ_MODEL, temperature=0)
