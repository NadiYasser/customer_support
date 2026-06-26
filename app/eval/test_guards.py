"""M10 — guardrails eval.

Two deterministic guards, two datasets:

  injection.json — messages labeled (expect_blocked). The input guard must flag the
    attacks AND let benign customer messages through, including ones that contain a
    trigger word like "ignore" or "refund" in legitimate context ("cancel order 1002
    and ignore the shipping fee"). That second half is the real test: a guard that
    blocks every message is useless, so we measure false positives too.

  pii.json — (raw -> expected) redaction pairs. We assert EXACT output: PII shapes
    become typed placeholders, and non-PII that merely looks numeric (ISO dates,
    prices, order ids) is preserved. The kept-* cases guard against over-redaction.

Unlike the routing/faithfulness evals, these call no LLM — the guards are pure
regex. So this file is fast, free, and fully deterministic: exact assertions, no
accuracy floor needed.
"""
import json
from pathlib import Path

import pytest

from app.guards.injection import detect_injection
from app.guards.pii import redact_pii

_DATA = Path(__file__).parent / "datasets"
INJECTION_CASES = json.loads((_DATA / "injection.json").read_text())
PII_CASES = json.loads((_DATA / "pii.json").read_text())


@pytest.mark.parametrize("case", INJECTION_CASES, ids=[c["id"] for c in INJECTION_CASES])
def test_injection_detection(case):
    """Attacks are flagged; benign messages (even with trigger words) pass."""
    blocked = detect_injection(case["message"]) is not None
    assert blocked == case["expect_blocked"], (
        f"{case['id']}: {case['message']!r}\n"
        f"  expected blocked={case['expect_blocked']}, got {blocked}"
    )


def test_injection_no_false_positives():
    """Report the false-positive rate on benign messages — the failure mode that
    makes a guard unusable. A guard that blocks real customers is worse than none."""
    benign = [c for c in INJECTION_CASES if not c["expect_blocked"]]
    false_positives = [c["id"] for c in benign if detect_injection(c["message"])]
    print(f"\nInjection false positives: {len(false_positives)}/{len(benign)} {false_positives}")
    assert not false_positives


@pytest.mark.parametrize("case", PII_CASES, ids=[c["id"] for c in PII_CASES])
def test_pii_redaction(case):
    """Structured PII is replaced with placeholders; non-PII numerics survive."""
    assert redact_pii(case["raw"]) == case["expected"], (
        f"{case['id']}: {case['raw']!r}\n"
        f"  expected {case['expected']!r}\n"
        f"  got      {redact_pii(case['raw'])!r}"
    )
