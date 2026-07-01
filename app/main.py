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
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from groq import BadRequestError
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel
import json

from app.channels import pending, whatsapp
from app.graph import support_graph
from app.observability.collector import TraceCollector
from app.observability.format import format_trace
from app.streaming import stream_answer

# Sent to a WhatsApp customer when their refund hits the approval gate. They get
# this immediately (the webhook can't hold the line); an admin approves later on
# the dashboard and the outcome is pushed back as a separate message.
REVIEW_MESSAGE = (
    "Thanks — your refund request has been received and is under review by our "
    "team. We'll message you here as soon as it's been processed."
)

app = FastAPI(title="AI Customer Support Platform")


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    # Meta requires a reachable Privacy Policy URL before an app can go Live. This
    # is a learning project with no real users or data collection, so this page
    # just states that plainly. Served by our own app over the ngrok tunnel, so no
    # external host is needed: the URL is https://<ngrok-domain>/privacy.
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Privacy Policy</title></head>
<body style="font-family: system-ui; max-width: 640px; margin: 40px auto; line-height: 1.6">
<h1>Privacy Policy</h1>
<p>This application is a personal, educational project used to learn how to build
AI customer-support agents. It is not a commercial product.</p>
<p>It does not collect, store, sell, or share personal data for any purpose beyond
processing a message during a live test conversation. Messages sent to the test
WhatsApp number are used only to generate an immediate automated reply and are not
retained for marketing or shared with third parties.</p>
<p>For any question about this test project, contact the developer who shared this
number with you.</p>
</body></html>"""


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


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    # Streaming counterpart to /chat (M9). Instead of blocking on invoke() and
    # returning the whole reply, we stream the answer token-by-token as Server-Sent
    # Events: the HTTP response stays open and we write one "data:" line per event.
    #
    # Wire format (one event per line, blank line terminates each):
    #   data: {"delta": "Items"}      <- a piece of answer text
    #   data: {"delta": " purchased"}
    #   ...
    #   data: {"done": true}          <- stream finished
    # JSON-encoding each payload keeps newlines/quotes in the text from breaking
    # the SSE framing.
    #
    # SCOPE: this path streams the normal completion only. HITL refunds still go
    # through /chat (which surfaces pending_approval) + /resume — an interrupt()
    # mid-stream needs its own event type, deliberately left out of M9.
    def event_stream():
        try:
            for delta in stream_answer(req.thread_id, req.message):
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except BadRequestError:
            # Same intermittent Groq tool_use_failed hiccup /chat guards against.
            yield f"data: {json.dumps({'error': 'hiccup, please retry'})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    # If this thread came in over WhatsApp, the human just decided here on the
    # dashboard — but the customer is on WhatsApp, not watching this response. Push
    # the outcome back out as an outbound message, and clear the pending entry so
    # it leaves the dashboard's approval queue.
    if req.thread_id.startswith(whatsapp.THREAD_PREFIX):
        pending.remove(req.thread_id)
        if result.get("messages"):
            phone = req.thread_id[len(whatsapp.THREAD_PREFIX):]
            whatsapp.send_text(phone, result["messages"][-1].content)
    return _format_result(req.thread_id, result, tracer)


@app.get("/pending")
def pending_approvals():
    # The dashboard polls this to discover threads paused at the HITL gate. With
    # synchronous /chat the caller already holds the pending_action; async channels
    # have no such caller, so the pending store (app/channels/pending.py) is the
    # out-of-band place the proposal waits to be picked up.
    return {"pending": pending.list_all()}


@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    # Meta's one-time verification handshake. It GETs with hub.* query params; we
    # echo hub.challenge back as PLAIN TEXT only if the verify token matches the
    # secret we configured. The adapter owns the token check; we just translate the
    # result into HTTP (200 + challenge, or 403).
    params = request.query_params
    challenge = whatsapp.verify_webhook(
        params.get("hub.mode"),
        params.get("hub.verify_token"),
        params.get("hub.challenge"),
    )
    if challenge is None:
        return Response(status_code=403)
    return Response(content=challenge, media_type="text/plain")


@app.post("/webhook/whatsapp")
async def whatsapp_inbound(request: Request):
    # Inbound message callback. Meta expects a FAST 200 and closes the connection,
    # so the reply goes back out-of-band via the adapter's send_text — this is the
    # async nature that reshapes the HITL flow below.
    body = await request.json()
    parsed = whatsapp.parse_inbound(body)
    if parsed is None:
        # Status/read receipt or a non-text message — nothing to answer, but we
        # MUST still 200 or Meta will retry the delivery.
        return {"status": "ignored"}

    phone, text = parsed
    thread_id = whatsapp.thread_id_for(phone)
    config = {"configurable": {"thread_id": thread_id}}

    # M14 admin takeover. If a human admin has muted this thread, the agent must
    # stay silent — but we still record the customer's message into the thread
    # state so (a) the admin sees it in the console and (b) the agent has full
    # context if the thread is later released. update_state appends via the
    # add_messages reducer, exactly like a normal turn, minus the agent run.
    snapshot = support_graph.get_state(config)
    if snapshot.values.get("muted"):
        support_graph.update_state(config, {"messages": [HumanMessage(text)]})
        return {"status": "muted"}

    try:
        result = support_graph.invoke({"messages": [HumanMessage(text)]}, config)
    except BadRequestError:
        whatsapp.send_text(phone, "Sorry, I hit a hiccup processing that. Please try again.")
        return {"status": "error"}

    interrupts = result.get("__interrupt__")
    if interrupts:
        # The refund gate fired. There's no caller to show the proposal to, so:
        # park it in the pending store for an admin, and tell the customer it's
        # under review. The graph stays checkpointed at the interrupt until /resume.
        pending.add(thread_id, interrupts[0].value)
        whatsapp.send_text(phone, REVIEW_MESSAGE)
        return {"status": "pending_approval"}

    whatsapp.send_text(phone, result["messages"][-1].content)
    return {"status": "completed"}


# --- Admin console (M14) -----------------------------------------------------
# A small read/write surface over the WhatsApp conversation threads, consumed by
# the Streamlit admin dashboard. The dashboard never touches the checkpointer
# directly — it goes through these endpoints, keeping the graph the single owner
# of conversation state.


def _role_of(message) -> str:
    # Map a LangGraph message object to a role the dashboard can render.
    # HumanMessage = the WhatsApp customer. AIMessage = agent OR admin — we tag
    # admin messages with name="admin" when recording them, so we can tell the two
    # apart in the transcript.
    if isinstance(message, HumanMessage):
        return "customer"
    if isinstance(message, AIMessage):
        return "admin" if getattr(message, "name", None) == "admin" else "agent"
    return "system"


def _thread_messages(thread_id: str) -> list[dict]:
    state = support_graph.get_state({"configurable": {"thread_id": thread_id}})
    msgs = state.values.get("messages", []) if state.values else []
    out = []
    for m in msgs:
        # Only show the human-facing conversation. Tool results (ToolMessage) and
        # the agent's intermediate tool-CALL turns (AIMessage carrying tool_calls,
        # empty content) are internal plumbing, not part of the chat an admin
        # monitors — skip them.
        if not isinstance(m, (HumanMessage, AIMessage)):
            continue
        if getattr(m, "tool_calls", None):
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        if content.strip():
            out.append({"role": _role_of(m), "content": content})
    return out


@app.get("/admin/threads")
def admin_threads():
    # List every WhatsApp conversation (wa: threads) with a last-message preview
    # and its takeover state, for the console's conversation list. We enumerate
    # distinct thread_ids from the checkpointer, then read each one's tip state.
    seen = set()
    for tup in support_graph.checkpointer.list(None):
        tid = tup.config["configurable"]["thread_id"]
        if tid.startswith(whatsapp.THREAD_PREFIX):
            seen.add(tid)

    threads = []
    for tid in seen:
        msgs = _thread_messages(tid)
        if not msgs:
            continue
        state = support_graph.get_state({"configurable": {"thread_id": tid}})
        threads.append(
            {
                "thread_id": tid,
                "phone": tid[len(whatsapp.THREAD_PREFIX):],
                "muted": bool(state.values.get("muted")),
                "last": msgs[-1]["content"][:80],
                "count": len(msgs),
            }
        )
    # Most recently active-looking first isn't reliable without timestamps; sort by
    # phone for a stable order the admin can scan.
    threads.sort(key=lambda t: t["phone"])
    return {"threads": threads}


@app.get("/admin/threads/{thread_id}")
def admin_thread_detail(thread_id: str):
    state = support_graph.get_state({"configurable": {"thread_id": thread_id}})
    return {
        "thread_id": thread_id,
        "phone": thread_id[len(whatsapp.THREAD_PREFIX):] if thread_id.startswith(whatsapp.THREAD_PREFIX) else thread_id,
        "muted": bool(state.values.get("muted")) if state.values else False,
        "messages": _thread_messages(thread_id),
    }


class MuteRequest(BaseModel):
    thread_id: str
    muted: bool


@app.post("/admin/mute")
def admin_mute(req: MuteRequest):
    # Toggle takeover for a thread. Writing muted via update_state persists it in
    # the checkpointer, so the webhook sees it on the customer's next message.
    config = {"configurable": {"thread_id": req.thread_id}}
    support_graph.update_state(config, {"muted": req.muted})
    return {"thread_id": req.thread_id, "muted": req.muted}


class AdminSendRequest(BaseModel):
    thread_id: str
    message: str


@app.post("/admin/send")
def admin_send(req: AdminSendRequest):
    # Admin intervention: send a message to the customer over WhatsApp AND record
    # it in the thread state. Recording it (tagged name="admin") keeps the console
    # transcript complete and gives the agent full context if the thread is later
    # released back to it. Sending is real (or mock) via the same adapter.
    if not req.thread_id.startswith(whatsapp.THREAD_PREFIX):
        return {"status": "error", "detail": "not a WhatsApp thread"}
    phone = req.thread_id[len(whatsapp.THREAD_PREFIX):]
    whatsapp.send_text(phone, req.message)
    support_graph.update_state(
        {"configurable": {"thread_id": req.thread_id}},
        {"messages": [AIMessage(req.message, name="admin")]},
    )
    return {"status": "sent"}
