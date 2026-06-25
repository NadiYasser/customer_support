"""M7 — the trace callback handler.

LangChain broadcasts events as a run executes (a node started, an LLM call
finished with token counts, a tool returned). A callback handler subscribes to
those events. We hand ONE instance to .invoke(config={"callbacks": [handler]}) and
the framework calls these methods at the right moments — so we capture the whole
run from one place, with zero changes to the supervisor or any agent.

The recurring trick: *_start and *_end are separate calls. To time an event we
stash its start time under the run_id LangChain assigns (same id for the pair) and
compute the delta on _end.
"""
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from app.observability.trace import TraceEvent


class TraceCollector(BaseCallbackHandler):
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._starts: dict[UUID, float] = {}      # run_id -> start timestamp
        self._nodes: dict[UUID, str] = {}         # run_id -> node name (real nodes only)

    def _begin(self, run_id: UUID) -> None:
        self._starts[run_id] = time.perf_counter()

    def _elapsed(self, run_id: UUID) -> float:
        start = self._starts.pop(run_id, None)
        return time.perf_counter() - start if start is not None else 0.0

    # --- nodes (supervisor, each agent, and the agents' model/tools steps) -
    # LangGraph fires many inner chain events per node (RunnableSequence,
    # parsers, _pick_route, ...). The node's identity (name + langgraph_node
    # metadata) is only present on _start, so we decide there whether this run is
    # a real node and remember it by run_id; _end just emits what _start kept.
    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs) -> None:
        self._begin(run_id)
        name = kwargs.get("name")
        node = (kwargs.get("metadata") or {}).get("langgraph_node")
        if name and name == node:
            self._nodes[run_id] = name

    def on_chain_end(self, outputs, *, run_id, **kwargs) -> None:
        name = self._nodes.pop(run_id, None)
        if name is None:
            self._starts.pop(run_id, None)
            return
        self.events.append(TraceEvent("node", name, self._elapsed(run_id)))

    # --- LLM calls --------------------------------------------------------
    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._begin(run_id)

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        usage = {}
        # Token counts live in different spots depending on the provider; Groq
        # surfaces them in llm_output["token_usage"].
        llm_output = getattr(response, "llm_output", None) or {}
        token_usage = llm_output.get("token_usage") or {}
        if token_usage:
            usage = {
                "prompt_tokens": token_usage.get("prompt_tokens"),
                "completion_tokens": token_usage.get("completion_tokens"),
                "total_tokens": token_usage.get("total_tokens"),
            }
        model = llm_output.get("model_name", "llm")
        self.events.append(TraceEvent("llm", model, self._elapsed(run_id), usage))

    # --- tools (search_kb, get_order_status, refund, ...) -----------------
    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs) -> None:
        self._begin(run_id)
        name = (serialized or {}).get("name", "tool")
        self._starts[("name", run_id)] = name  # remember the name for _end

    def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        name = self._starts.pop(("name", run_id), "tool")
        text = output.content if hasattr(output, "content") else str(output)
        self.events.append(
            TraceEvent("tool", name, self._elapsed(run_id), {"output": text})
        )

    def total_tokens(self) -> int:
        return sum(e.data.get("total_tokens") or 0 for e in self.events if e.kind == "llm")
