"""M7 — what a single recorded event looks like.

A trace is just an ordered list of these. We keep them as a plain dataclass so the
shape is obvious: a kind ("llm" / "tool" / "node"), a label, how long it took, and
a free-form `data` dict for kind-specific extras (token counts, tool args, etc.).

No cleverness here on purpose — the trace is meant to be inspected, so its storage
is a flat, readable log rather than a nested tree.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TraceEvent:
    kind: str                     # "node" | "llm" | "tool"
    label: str                    # node name, model name, or tool name
    duration_s: float             # wall-clock seconds for this event
    data: dict[str, Any] = field(default_factory=dict)
