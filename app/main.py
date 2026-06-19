"""FastAPI entrypoint.

Milestone M0: only /health is wired up. /chat and /resume are stubs that we'll
implement once the LangGraph graph exists (M1+).
"""
from fastapi import FastAPI
from pydantic import BaseModel

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
    # TODO(M1+): invoke the LangGraph graph with req.message on thread req.thread_id.
    return {"status": "not_implemented", "detail": "chat is wired up in milestone M1+"}


@app.post("/resume")
def resume(req: ResumeRequest):
    # TODO(M4): resume the paused graph from its checkpoint with the approval decision.
    return {"status": "not_implemented", "detail": "resume is wired up in milestone M4"}
