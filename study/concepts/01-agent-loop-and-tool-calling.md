# 01 — Agent Loop & Tool Calling

> Roadmap: **M1** · Code: [app/agents/tracking.py](../../app/agents/tracking.py), [app/tools/orders.py](../../app/tools/orders.py)

## TL;DR

An **agent** is an LLM in a loop with tools. The model doesn't just answer — it decides
whether to call a tool, you execute that tool, feed the result back, and the model loops
until it has enough to write a final answer.

## Mental model

```
            ┌─────────────────────────────────────────┐
            ▼                                          │
   ┌──────────────┐   wants tool?   ┌──────────────┐   │ tool result
   │  call model  │ ───── yes ────▶ │  run tool    │ ──┘ appended to messages
   └──────────────┘                 └──────────────┘
            │ no (final answer)
            ▼
          DONE
```

The loop is just: **call model → if it requested a tool, run it and append the output →
call model again → ... → stop when the model returns plain text instead of a tool call.**

## How tool calling actually works

1. You describe each tool to the model (name, description, parameter schema). In LangChain
   the `@tool` decorator turns a Python function into that schema — **the docstring is what
   the model reads** to decide when/how to call it.
2. The model, instead of replying with text, emits a structured **tool call**: tool name +
   JSON arguments.
3. Your runtime parses that, runs the actual function, and appends the return value as a
   `ToolMessage`.
4. The model sees the tool result on the next turn and either calls another tool or writes
   the final answer.

The key insight: **the LLM never runs code**. It only *requests* calls; your harness
executes them. That boundary is where safety/validation lives.

## Where it lives in this codebase

`tracking.py` is the simplest agent — read-only, one tool:

```python
tracking_agent = create_agent(
    model=get_model(),
    tools=[get_order_status],
    system_prompt=SYSTEM_PROMPT,
)
```

`create_agent` (LangGraph's prebuilt ReAct agent) **builds the loop for you** — model +
tools + prompt becomes a runnable graph that loops call→tool→call until done. The tool
itself ([tools/orders.py](../../app/tools/orders.py)) is a thin `@tool` wrapper over the
repository; its docstring tells the model when to use it.

## Interview Q&A

**Q: What is an "agent" versus a plain LLM call?**
A plain call is one prompt → one completion. An agent wraps the LLM in a control loop with
tools, so it can take actions (look something up, call an API) and incorporate the results
before answering. The agent decides the steps at runtime; you don't script them.

**Q: What's the ReAct pattern?**
Reason + Act. The model alternates between reasoning about what to do and acting (calling a
tool), using each observation to inform the next step. `create_agent` implements this.

**Q: How does the model "call" a function it can't execute?**
It emits a structured tool-call (name + JSON args) instead of text. The framework matches
the name to a registered function, runs it, and feeds the result back. The model only
*requests*; the runtime *executes*.

**Q: Why does the tool docstring matter so much?**
It's the only thing the model sees about the tool. A vague docstring → the model calls the
wrong tool or with bad args. Treat docstrings as prompt engineering.

**Q: How does the loop know when to stop?**
When the model responds with a normal message (no tool call), the loop exits and that
message is the answer.

## Gotchas / things that bite

- **Malformed tool calls.** Some models intermittently serialize a tool call as text rather
  than JSON → the provider rejects it (here: Groq `400 tool_use_failed`). This project moved
  from `llama-3.3-70b` to `openai/gpt-oss-120b` for reliable tool serialization, and
  `/chat` catches the error to surface a friendly retry. **Model choice affects tool-call
  reliability**, not just answer quality.
- **`temperature=0`** for tool/routing decisions — you want predictable behavior, not
  creativity.
- **Infinite loops** are possible if a tool keeps failing and the model keeps retrying;
  production agents cap iterations.

## Related

- [02 — Multi-agent orchestration](02-multi-agent-orchestration.md) (many of these loops behind a router)
- [06 — Structured output](06-structured-output.md) (same tool/JSON mechanism, pointed at classification)
