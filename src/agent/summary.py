"""
summary.py - The end-of-call record: summary, outcome, follow-up.

Outcome and follow-up come from CODE (what really happened), not from the model.
The model only writes the short free-text summary, from a masked transcript, and
the result is scrubbed again, so the stored summary holds no names or numbers.
"""
import re

from . import llm
from .safety import is_arabic

_NUM = re.compile(r"\d[\d\s\-+]{3,}\d")
_EMAIL = re.compile(r"\S+@\S+\.\S+")


def mask(text: str) -> str:
    return _EMAIL.sub("[email]", _NUM.sub("[number]", text or ""))


def language_of(session) -> str:
    users = [t for r, t in session.transcript if r == "user"]
    ar = sum(is_arabic(t) for t in users)
    return "ar" if users and ar > len(users) / 2 else "en"


def outcome_of(session, reason: str) -> str:
    kinds = [e["type"] for e in session.events]
    if "TRANSFERRED" in kinds:
        return "TRANSFERRED"
    actions = [k for k in kinds if k in ("BOOKED", "RESCHEDULED", "CANCELLED", "CONFIRMED")]
    if actions:
        return actions[-1]                  # the most recent action wins
    users = [t for r, t in session.transcript if r == "user"]
    return "ABANDONED" if reason == "timeout" and len(users) <= 1 else "INFO_ONLY"


def follow_up_of(session, outcome: str) -> str:
    if outcome == "TRANSFERRED":
        return f"Human follow-up needed: {session.transfer_reason}"
    if "VERIFY_FAILED" in [e["type"] for e in session.events]:
        return "Identity check failed at least once; review if the patient calls back"
    if outcome == "BOOKED":
        return "Send confirmation and schedule a reminder"
    return "None"


def refs_of(session) -> str:
    return ",".join(str(e["ref"]) for e in session.events if "ref" in e)


def _fallback(outcome: str, n_user: int) -> str:
    return f"Call with {n_user} caller message(s). Outcome: {outcome}."


def build(session, reason: str) -> dict:
    outcome = outcome_of(session, reason)
    lines = [f"{'Caller' if r == 'user' else 'Assistant'}: {mask(t)}" for r, t in session.transcript]
    actions = ", ".join(e["type"] for e in session.events if e["type"] not in ("VERIFIED",)) or "none"
    n_user = sum(1 for r, _ in session.transcript if r == "user")
    try:
        out = llm.chat([
            {"role": "system", "content": "You write short internal call summaries for a dental clinic. "
             "Write 2 or 3 sentences in English: what the caller wanted and what was done. "
             "Never include names, phone numbers, ID numbers or reference numbers."},
            {"role": "user", "content": "Transcript:\n" + "\n".join(lines)[-3500:] +
             f"\n\nSystem-recorded actions: {actions}\nOutcome: {outcome}"}], [])
        summary = mask(out["content"]).strip() or _fallback(outcome, n_user)
    except Exception:
        summary = _fallback(outcome, n_user)
    return {"summary": summary[:600], "outcome": outcome, "follow_up": follow_up_of(session, outcome)}
