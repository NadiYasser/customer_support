# 06 — Structured Output

> Roadmap: **M3** (routing) · Code: [app/supervisor.py](../../app/supervisor.py), [app/eval/test_faithfulness.py](../../app/eval/test_faithfulness.py)

## TL;DR

When you need the model's output to be **machine-usable** (a route name, a verdict, a record)
rather than prose, you bind a **schema** and force the model to return data matching it.
No regex, no "parse the model's paragraph" — you get a typed object back.

## Mental model

```
free text:        "Hmm, this sounds like a refund request to me..."  → you must parse it 😖
structured output: RoutingDecision(route="refund")                   → already a typed value 🎯
```

You define a schema (here a Pydantic model), call `model.with_structured_output(Schema)`, and
`invoke` returns a validated instance of that schema instead of a chat message.

## Two ways the model is constrained

`with_structured_output` can extract fields two ways — and which one you pick matters:

| method | How it works | When |
|---|---|---|
| **tool calling** (default) | Model emits a tool call whose args = your schema | Default; works on most models |
| **`json_schema`** | Provider constrains the *raw response* to the schema directly | When tool-call serialization is unreliable |

This project uses **`method="json_schema"`** for routing ([supervisor.py](../../app/supervisor.py)):

```python
_router = get_model().with_structured_output(RoutingDecision, method="json_schema")
```

Why: the Groq model intermittently emits a **malformed tool call** (right route, wrong
serialized tool name) → Groq rejects with `400 tool_use_failed`. `json_schema` skips tool
serialization entirely and constrains the response directly, so routing is reliable.

## Two uses in this codebase

**1. Routing** — constrain to a fixed label set so control flow is safe:

```python
Route = Literal["faq_rag", "tracking", "refund", "modify", "it_support"]

class RoutingDecision(BaseModel):
    route: Route = Field(description="Which specialized agent should handle this message: ...")
```

The `Literal` guarantees the supervisor returns one of exactly five values — always something
the conditional edge knows how to dispatch (see [02](02-multi-agent-orchestration.md)).

**2. LLM-as-judge verdict** — make an evaluation inspectable, not a vibe
([test_faithfulness.py](../../app/eval/test_faithfulness.py)):

```python
class FaithfulnessVerdict(BaseModel):
    supported: bool
    score: int = Field(ge=1, le=5)
    reasoning: str
```

The judge must return a boolean + 1–5 score + reasoning → you can assert on it and read *why*.

## Why the `description`/`Field` text matters

The field descriptions are **part of the prompt** — the model reads them to decide what to put
in each field. A vague description gives sloppy structured output. Treat schema docs as prompt
engineering, same as tool docstrings ([01](01-agent-loop-and-tool-calling.md)).

## Interview Q&A

**Q: What is structured output and why use it?**
Forcing the model to return data conforming to a schema (JSON/Pydantic) instead of free text.
Use it whenever a downstream system consumes the output — routing, extraction, classification,
evals — so you skip brittle text parsing and get validation for free.

**Q: How is it enforced under the hood?**
Either via tool/function calling (the schema becomes a function signature the model "calls") or
provider-native constrained decoding (`json_schema` / JSON mode) that restricts tokens to valid
schema-conforming output. The framework validates and retries on mismatch.

**Q: tool-calling vs json_schema mode — when would you switch?**
Default to tool calling. Switch to json_schema (or JSON mode) when the model's tool-call
serialization is flaky or you only need data extraction, not an actual tool invocation — as
this project does to dodge Groq `tool_use_failed`.

**Q: How does structured output make routing reliable?**
Constraining to a `Literal` set means the model can only return a valid route, so the router's
output is always dispatchable — no "I think this is maybe a refund?" to parse.

**Q: How does it relate to tool calling?**
Same underlying mechanism — a schema the model fills with JSON. Tool calling points it at
*actions*; structured output points it at *data you want back*.

## Gotchas

- **Field descriptions are prompt text** — write them carefully.
- **Tool-call serialization can fail** on some models; `json_schema`/JSON mode is the escape
  hatch.
- **Validation can still fail** if the model returns junk; frameworks retry, but handle the
  error path.
- A too-rigid schema can make the model omit nuance it actually had — match schema granularity
  to the task.

## Related

- [02 — Orchestration](02-multi-agent-orchestration.md) (routing uses this)
- [07 — Evaluation](07-evaluation.md) (LLM-judge verdict uses this)
- [01 — Agent loop](01-agent-loop-and-tool-calling.md) (tool calling = same mechanism)
