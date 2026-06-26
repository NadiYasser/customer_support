"""M10 — PII redaction for traces and logs.

The M7 trace records tool outputs, and those outputs carry real customer data: an
order lookup returns a name and shipping address, a customer message can contain an
email, phone number, or card number. That trace is both print()ed server-side
(→ log files, log aggregators, retention) and echoed in the HTTP response. So it's
a genuine leak surface. This module scrubs structured PII out of any text before it
is logged or returned.

Scope — what we redact and why only this:
  We match STRUCTURED PII that has a reliable shape: email addresses, phone numbers,
  and long digit runs (card-like / account numbers). These have low false-positive
  rates with a regex. We deliberately do NOT regex personal NAMES: names have no
  fixed shape, so a regex either misses most of them or nukes ordinary words. Real
  name redaction needs an NER model (e.g. Presidio/spaCy) — that's the production
  upgrade path; we keep the visible, deterministic core here.

Each match is replaced with a typed placeholder ([EMAIL], [PHONE], [CARD]) rather
than blanked out, so a reader/operator can still see that a value WAS there and what
kind it was — useful for debugging without exposing the value itself.
"""
import re

# Order matters: redact emails BEFORE phones/cards, or the digit patterns could
# chew through the numeric parts of other strings. Emails are matched first and
# their span is already replaced by the time the phone/card patterns run.
_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

# Card-like: 13–16 digits, optionally split by single spaces/hyphens. Anchored on a
# digit at BOTH ends so it can't swallow a trailing separator or the space before
# the next word. Checked before the looser phone pattern so a full card number
# isn't partially eaten as a phone.
_CARD = re.compile(r"\b\d(?:[ -]?\d){12,15}\b")

# Phone candidate: an optional +country code then digits with common separators.
# This shape ALSO matches things like an ISO date (2026-06-22), so the replacement
# gates each candidate on digit count (see _sub_phone) to avoid redacting dates.
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def _sub_phone(match: re.Match) -> str:
    # Only treat a candidate as a phone if it has a leading + (explicit country
    # code) or at least 9 digits. An ISO date like 2026-06-22 has 8 digits and no
    # +, so it's left intact — redacting trace dates as [PHONE] would be both wrong
    # and unhelpful to an operator. Tradeoff: a bare 7–8 digit local number slips
    # through; over/under-redaction here is the classic precision/recall dial.
    span = match.group(0)
    digits = sum(c.isdigit() for c in span)
    if span.lstrip().startswith("+") or digits >= 9:
        return "[PHONE]"
    return span


def redact_pii(text: str) -> str:
    """Replace structured PII in `text` with typed placeholders.

    Idempotent and safe to call on any trace/log string. Email → [EMAIL],
    card-like digit runs → [CARD], phone-like runs → [PHONE].
    """
    if not text:
        return text
    text = _EMAIL.sub("[EMAIL]", text)
    text = _CARD.sub("[CARD]", text)
    text = _PHONE.sub(_sub_phone, text)
    return text
