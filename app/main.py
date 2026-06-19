"""FastAPI entrypoint.

M2: /chat invokes the FAQ/RAG agent (single-turn, no memory yet). This is
TEMPORARY — until M3 adds the supervisor that routes between agents, we point
/chat directly at the agent we're currently exercising.
/resume is still a stub until M4 (human-in-the-loop).
"""
from fastapi import FastAPI
from groq import BadRequestError
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.agents.faq_rag import faq_rag_agent

app = FastAPI(title="AI Customer Support Platform")


@app.get("/health")
def health():
    return {"status": "ok"}


class ChatRequest(BaseModel):
    thread_id: str
    message: str


class ResumeRequest(BaseModel):
    thread_id: str
    approved: bool


@app.post("/chat")
def chat(req: ChatRequest):
    # M2 (temporary): run the FAQ/RAG agent loop on the single incoming message.
    # M3 will replace this with the supervisor, which routes to the right agent.
    # thread_id is accepted now but unused until M5 adds memory.
    try:
        result = faq_rag_agent.invoke({"messages": [HumanMessage(req.message)]})
    except BadRequestError:
        # The Groq Llama model occasionally emits a malformed tool call
        # (tool_use_failed): it picks the right tool but serializes the call as
        # text instead of JSON, so Groq rejects it. It's intermittent — a retry
        # usually works — so we surface a friendly retry message instead of a 500.
        return {
            "thread_id": req.thread_id,
            "reply": "Sorry, I hit a hiccup processing that. Please try again.",
        }
    answer = result["messages"][-1].content
    return {"thread_id": req.thread_id, "reply": answer}


@app.post("/resume")
def resume(req: ResumeRequest):
    # TODO(M4): resume the paused graph from its checkpoint with the approval decision.
    return {"status": "not_implemented", "detail": "resume is wired up in milestone M4"}
