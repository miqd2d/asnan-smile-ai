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


_PHRASE = {"BOOKED": "booked a new appointment", "RESCHEDULED": "rescheduled an appointment",
           "CANCELLED": "cancelled an appointment"}
_FIRST_PERSON = re.compile(r"\b(I|I'm|I've|you|your)\b|\?", re.I)


def _template(session, outcome: str) -> str:
    """A summary written by code from recorded facts. Used whenever the model's text is unusable."""
    if outcome == "TRANSFERRED":
        return f"The call was transferred to a team member (reason: {session.transfer_reason})."
    done = [_PHRASE[e["type"]] for e in session.events if e["type"] in _PHRASE]
    if done:
        return "The patient " + " and ".join(done) + "."
    return "The caller asked for information; no appointment changes were made."


def _clean(text: str, session) -> str | None:
    text = mask(text).strip()
    if session.first_name:
        text = re.sub(re.escape(session.first_name), "the patient", text, flags=re.I)
    if not text or _FIRST_PERSON.search(text):      # chatty, first-person or a question = not a summary
        return None
    return text


def build(session, reason: str) -> dict:
    outcome = outcome_of(session, reason)
    caller_lines = [f"- {mask(t)}" for r, t in session.transcript if r == "user"]    # caller words only
    actions = ", ".join(e["type"] for e in session.events if e["type"] != "VERIFIED") or "none"
    summary = None
    try:
        out = llm.chat([
            {"role": "system", "content": "You write short internal call summaries for a dental clinic. "
             "Write 2 sentences in the third person, in English, starting with 'The caller' or 'The patient'. "
             "Never include names, phone numbers, ID numbers or reference numbers. Do not address anyone."},
            {"role": "user", "content": "What the caller said:\n" + "\n".join(caller_lines)[-2500:] +
             f"\n\nActions recorded by the system: {actions}\nOutcome: {outcome}"}], [])
        summary = _clean(out["content"], session)
    except Exception:
        pass
    return {"summary": (summary or _template(session, outcome))[:600], "outcome": outcome,
            "follow_up": follow_up_of(session, outcome)}
