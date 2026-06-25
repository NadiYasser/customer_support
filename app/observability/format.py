"""M7 — render a collected trace as readable text.

Turns the flat TraceEvent list into the one-call trace IMPROVEMENTS.md asks for:
each node / LLM call / tool, its latency, token usage, and a snippet of tool
output, plus a total-tokens + total-latency footer.
"""
from app.observability.collector import TraceCollector


def format_trace(collector: TraceCollector, max_output: int = 200) -> str:
    lines = ["── trace ──"]
    for e in collector.events:
        if e.kind == "node":
            lines.append(f"[node] {e.label}  ({e.duration_s:.2f}s)")
        elif e.kind == "llm":
            toks = e.data.get("total_tokens")
            tok_str = f"  {toks} tok" if toks else ""
            lines.append(f"  [llm] {e.label}  ({e.duration_s:.2f}s){tok_str}")
        elif e.kind == "tool":
            out = (e.data.get("output") or "").replace("\n", " ")
            if len(out) > max_output:
                out = out[:max_output] + "…"
            lines.append(f"  [tool] {e.label}  ({e.duration_s:.2f}s)  → {out}")

    total_latency = sum(e.duration_s for e in collector.events if e.kind == "node")
    lines.append(
        f"── total: {collector.total_tokens()} tokens, {total_latency:.2f}s in nodes ──"
    )
    return "\n".join(lines)
