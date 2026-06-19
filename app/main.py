"""FastAPI entrypoint.

M3: /chat invokes the full graph — the supervisor routes each message to the
right specialized agent (faq_rag, tracking, refund, modify, it_support), then
that agent answers. Still single-turn: thread_id is accepted but unused until
M5 adds memory via a checkpointer.
/resume is still a stub until M4 (human-in-the-loop).
"""
from fastapi import FastAPI
from groq import BadRequestError
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app.graph import support_graph

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
    # M3: run the full graph. The supervisor classifies the message and routes to
    # one specialized agent, which produces the reply.
    # thread_id is accepted now but unused until M5 adds memory.
    try:
        result = support_graph.invoke({"messages": [HumanMessage(req.message)]})
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
