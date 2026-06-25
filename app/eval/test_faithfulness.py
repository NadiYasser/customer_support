"""M6 phase 6c — RAG faithfulness via LLM-as-judge.

6a and 6b had exact answers (== a route, == a section). Faithfulness does not:
"is this free-text answer supported by the chunks the agent retrieved, or did it
invent something?" There is no string to match, so we use a SECOND model as a
judge.

The judge is given three things from one real agent run — the question, the
retrieved context, and the answer — plus a narrow rubric, and returns a STRUCTURED
verdict (supported / score / reasoning). Structured output makes the judge's
decision inspectable instead of a vibe.

Faithfulness != helpfulness. "I don't have that information" is FAITHFUL (it
invents nothing) even if unhelpful. The rubric judges grounding only — that
narrowness is what makes an LLM judge reliable.

Calls the REAL faq_rag_agent (retrieval + generation) and a judge model. Slow,
costs tokens, non-deterministic — measuring the real system on purpose.
"""
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from app.agents.faq_rag import faq_rag_agent
from app.config import get_model

DATASET_PATH = Path(__file__).parent / "datasets" / "faithfulness.json"
CASES = json.loads(DATASET_PATH.read_text())


def _run_agent(question: str) -> tuple[str, str]:
    """Run the real FAQ agent; return (retrieved_context, final_answer).

    The agent's message list looks like:
        Human(question) -> AI(tool_call) -> Tool(retrieved chunks) -> AI(answer)
    We collect every ToolMessage as the context the answer was supposed to use,
    and the last AIMessage with text as the answer.
    """
    result = faq_rag_agent.invoke({"messages": [HumanMessage(content=question)]})
    messages = result["messages"]

    context_blocks = [m.content for m in messages if isinstance(m, ToolMessage)]
    context = "\n\n".join(context_blocks) if context_blocks else "(no context retrieved)"

    answers = [m.content for m in messages if isinstance(m, AIMessage) and m.content]
    answer = answers[-1] if answers else "(no answer produced)"
    return context, answer


class FaithfulnessVerdict(BaseModel):
    """The judge's grounded comparison of an answer against its retrieved context."""

    supported: bool = Field(
        description="True if EVERY factual claim in the answer is supported by the "
        "context. An answer that declines ('I don't have that information') is "
        "supported=True because it invents nothing."
    )
    score: int = Field(
        ge=1, le=5,
        description="1 = fully hallucinated; 5 = fully grounded in the context.",
    )
    reasoning: str = Field(
        description="One or two sentences: which claims are/aren't supported."
    )


JUDGE_PROMPT = (
    "You are a strict evaluator of FAITHFULNESS for a retrieval-augmented answer. "
    "You are NOT answering the question yourself and NOT judging helpfulness. "
    "Judge ONLY this: is every factual claim in the ANSWER supported by the "
    "CONTEXT below? Any policy detail (numbers, timeframes, conditions) not present "
    "in the context is a hallucination, even if it sounds plausible. "
    "An answer that says it lacks the information is faithful (supported=True), "
    "because declining invents nothing."
)

_judge = get_model().with_structured_output(FaithfulnessVerdict, method="json_schema")


def _judge_answer(question: str, context: str, answer: str) -> FaithfulnessVerdict:
    return _judge.invoke(
        [
            ("system", JUDGE_PROMPT),
            ("human", f"QUESTION:\n{question}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}"),
        ]
    )


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_faithfulness_case(case):
    """The agent's answer is grounded in its retrieved context."""
    context, answer = _run_agent(case["question"])
    verdict = _judge_answer(case["question"], context, answer)
    assert verdict.supported, (
        f"{case['id']}: {case['question']!r}\n"
        f"  judge score {verdict.score}/5 — {verdict.reasoning}\n"
        f"  answer: {answer!r}"
    )


def test_faithfulness_rate():
    """Report the share of answers judged grounded, plus mean score."""
    supported = 0
    total_score = 0
    notes = []
    for case in CASES:
        context, answer = _run_agent(case["question"])
        verdict = _judge_answer(case["question"], context, answer)
        supported += int(verdict.supported)
        total_score += verdict.score
        flag = "ok " if verdict.supported else "BAD"
        notes.append(f"  [{flag}] {case['id']}: {verdict.score}/5 — {verdict.reasoning}")

    rate = supported / len(CASES)
    mean_score = total_score / len(CASES)
    print(
        f"\nFaithfulness: {supported}/{len(CASES)} grounded = {rate:.0%}, "
        f"mean score {mean_score:.1f}/5\n" + "\n".join(notes)
    )

    assert rate >= 0.8
