"""FastAPI entrypoint.

M5: human-in-the-loop. /chat runs the full graph with memory (checkpointer keyed
by thread_id). A refund at/above the approval threshold makes the refund tool
call interrupt(), which PAUSES the graph mid-run: invoke() returns early with an
"__interrupt__" field instead of a final answer. /chat surfaces that as a
"pending approval" reply carrying the proposed action. A human then calls /resume
{thread_id, approved} which continues the SAME paused graph from its checkpoint
via Command(resume=...). Below-threshold refunds and all other turns finish in
one shot, exactly as before.
"""
from fastapi import FastAPI
from groq import BadRequestError
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel

from app.graph import support_graph
from app.observability.collector import TraceCollector
from app.observability.format import format_trace

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


def _format_result(thread_id: str, result: dict, tracer: TraceCollector) -> dict:
    # One place to turn a graph invoke() result into an HTTP response, shared by
    # /chat and /resume. When the graph paused, the result has an "__interrupt__"
    # key: a tuple of Interrupt objects whose .value is the payload our refund
    # tool passed to interrupt(). In that case there is no final answer yet — we
    # return the proposal and tell the caller approval is pending. Otherwise the
    # last message is the agent's reply.
    #
    # The trace (M7) is printed server-side for the operator and echoed in the
    # response so a client can show what the run did.
    trace_text = format_trace(tracer)
    print(trace_text)

    interrupts = result.get("__interrupt__")
    if interrupts:
        return {
            "thread_id": thread_id,
            "status": "pending_approval",
            "pending_action": interrupts[0].value,
            "trace": trace_text,
        }
    return {
        "thread_id": thread_id,
        "status": "completed",
        "reply": result["messages"][-1].content,
        "trace": trace_text,
    }


@app.post("/chat")
def chat(req: ChatRequest):
    # The config's thread_id tells the checkpointer which conversation snapshot to
    # load before this turn and save after it. Same thread_id = history
    # accumulates; new thread_id = fresh conversation.
    config = {"configurable": {"thread_id": req.thread_id}}
    # A fresh collector per request: it subscribes to this run's events via the
    # callbacks list, so the trace covers exactly this /chat call.
    tracer = TraceCollector()
    config["callbacks"] = [tracer]
    try:
        result = support_graph.invoke(
            {"messages": [HumanMessage(req.message)]}, config
        )
    except BadRequestError:
        # The Groq Llama model occasionally emits a malformed tool call
        # (tool_use_failed): it picks the right tool but serializes the call as
        # text instead of JSON, so Groq rejects it. It's intermittent — a retry
        # usually works — so we surface a friendly retry message instead of a 500.
        return {
            "thread_id": req.thread_id,
            "status": "error",
            "reply": "Sorry, I hit a hiccup processing that. Please try again.",
        }
    return _format_result(req.thread_id, result, tracer)


@app.post("/resume")
def resume(req: ResumeRequest):
    # Continue a graph that paused at interrupt(). Command(resume=value) makes the
    # paused interrupt() call RETURN `value` and execution picks up from there —
    # all on the SAME thread_id, so the checkpoint with the pending refund is the
    # one we resume. The dict we pass becomes the `decision` the refund tool reads.
    config = {"configurable": {"thread_id": req.thread_id}}
    tracer = TraceCollector()
    config["callbacks"] = [tracer]
    result = support_graph.invoke(
        Command(resume={"approved": req.approved}), config
    )
    return _format_result(req.thread_id, result, tracer)
