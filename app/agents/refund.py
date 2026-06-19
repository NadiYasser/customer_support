"""Refund agent (M3) with human-in-the-loop gate (M4).

Tool: process_refund(order_id, amount). If amount >= REFUND_APPROVAL_THRESHOLD,
the graph calls interrupt() to pause and wait for human approval before the
refund is actually executed.
"""
# TODO(M3): implement the refund agent + tool.
# TODO(M4): add the interrupt() approval gate for large refunds.
