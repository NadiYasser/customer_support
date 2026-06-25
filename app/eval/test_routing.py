"""M6 phase 6a — routing-accuracy eval.

We measure the supervisor as a classifier: given a customer message, does it pick
the correct specialized agent? Each dataset case is (message -> expected_route).

Two layers here:
  1. A parametrized test, one case per dataset row, so a failure names the exact
     message that misrouted (e.g. test_routing_case[refund-02]).
  2. A summary test that runs the whole dataset and prints overall accuracy — the
     single number you track across prompt changes.

These call the REAL supervisor(), which calls Groq. They are slow and cost tokens
on purpose: we're measuring the real system, not a mock of it.
"""
import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from app.supervisor import supervisor

DATASET_PATH = Path(__file__).parent / "datasets" / "routing.json"
CASES = json.loads(DATASET_PATH.read_text())


def _route_for(message: str) -> str:
    """Run the real supervisor on one message and return its chosen route."""
    state = {"messages": [HumanMessage(content=message)]}
    return supervisor(state)["route"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_routing_case(case):
    """Each dataset case routes to its expected agent."""
    actual = _route_for(case["message"])
    assert actual == case["expected_route"], (
        f"{case['id']}: {case['message']!r}\n"
        f"  expected {case['expected_route']!r}, got {actual!r}"
    )


def test_routing_accuracy():
    """Report overall routing accuracy across the whole dataset."""
    correct = 0
    misroutes = []
    for case in CASES:
        actual = _route_for(case["message"])
        if actual == case["expected_route"]:
            correct += 1
        else:
            misroutes.append(f"  {case['id']}: expected {case['expected_route']!r}, got {actual!r}")

    accuracy = correct / len(CASES)
    report = [f"\nRouting accuracy: {correct}/{len(CASES)} = {accuracy:.0%}"]
    if misroutes:
        report.append("Misroutes:")
        report.extend(misroutes)
    print("\n".join(report))

    # A floor, not a target. Raise it as the router improves; if it drops below,
    # a change regressed routing.
    assert accuracy >= 0.8
