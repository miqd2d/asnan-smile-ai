"""
tools.py - What the model may DO. Every action goes through here.

The model proposes a tool call; this file decides whether it is allowed, injects the
verification token (the model never sees it), runs the PMS function, and turns any
RuleError into a message the model can read.
"""
import logging
import re

import config
import pms
from . import ai_config, calls
from .dates import normalize_time, resolve_date, weekday_name
from rules import RuleError

log = logging.getLogger("uvicorn.error")


class ToolArgError(Exception):
    pass


def _fn(name, description, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


_INT, _STR, _BOOL = {"type": "integer"}, {"type": "string"}, {"type": "boolean"}

SCHEMAS = {s["function"]["name"]: s for s in [
    _fn("find_doctors", "Find bookable doctors, by specialty (unit_id) and/or by name.",
        {"unit_id": {**_INT, "description": "Specialty id"}, "name": {**_STR, "description": "Doctor name as spoken"}}),
    _fn("get_slots", "Free start times for ONE doctor on ONE day for a visit type.",
        {"doctor_id": _INT, "date": {**_STR, "description": "YYYY-MM-DD, or 'tomorrow', 'next sunday'..."},
         "rov_id": {**_INT, "description": "Visit type id"},
         "after": {**_STR, "description": "Optional HH:MM, only times after this"},
         "before": {**_STR, "description": "Optional HH:MM, only times before this"}},
        ["doctor_id", "date", "rov_id"]),
    _fn("find_next_available", "Earliest free times across a doctor, a specialty, or all doctors.",
        {"rov_id": _INT, "unit_id": _INT, "doctor_id": _INT,
         "from_date": {**_STR, "description": "Optional start day"}}, ["rov_id"]),
    _fn("verify_patient", "Verify the caller. Needs the patient file number plus phone or name.",
        {"patient_id": _INT, "phone": _STR, "name": {**_STR, "description": "Any part of the name"}}, ["patient_id"]),
    _fn("get_my_appointments", "List the verified patient's upcoming appointments."),
    _fn("book_appointment", "Book a slot that was offered. Only after the caller said yes.",
        {"doctor_id": _INT, "rov_id": _INT, "date": _STR, "time": {**_STR, "description": "HH:MM"},
         "notes": {**_STR, "description": "Caller's own words about the problem"},
         "patient_confirmed": {**_BOOL, "description": "true only after the caller clearly agreed"}},
        ["doctor_id", "rov_id", "date", "time", "patient_confirmed"]),
    _fn("reschedule_appointment", "Move an appointment to an offered slot. Only after the caller said yes.",
        {"appointment_id": {**_INT, "description": "Reference number"}, "new_date": _STR, "new_time": _STR,
         "new_doctor_id": {**_INT, "description": "Only if changing doctor"}, "patient_confirmed": _BOOL},
        ["appointment_id", "new_date", "new_time", "patient_confirmed"]),
    _fn("cancel_appointment", "Cancel an appointment. Only after the caller said yes.",
        {"appointment_id": {**_INT, "description": "Reference number"}, "patient_confirmed": _BOOL},
        ["appointment_id", "patient_confirmed"]),
    _fn("confirm_appointment", "Mark an appointment as confirmed by the patient.",
        {"appointment_id": {**_INT, "description": "Reference number"}}, ["appointment_id"]),
    _fn("transfer_to_agent", "Hand the call to a human: complaints, anything you cannot do, repeated confusion.",
        {"reason": _STR}, ["reason"]),
    _fn("end_call", "End the call after saying goodbye."),
]}
GATED = {"get_my_appointments", "book_appointment", "reschedule_appointment",
         "cancel_appointment", "confirm_appointment"}      # need a verified patient


def tools_for(session) -> list[dict]:
    """Stage-based tool list: appointment tools only exist AFTER verification."""
    return [s for n, s in SCHEMAS.items() if session.verified or n not in GATED]


# ----------------------------------------------------------------- helpers
def _err(code, message, **extra):
    return {"error": code, "message": message, **extra}


def _int(args, key, required=True):
    v = args.get(key)
    if v in (None, ""):
        if required:
            raise ToolArgError(f"'{key}' is required.")
        return None
    if isinstance(v, bool):
        raise ToolArgError(f"'{key}' must be a number.")
    if isinstance(v, str):
        v = re.sub(r"\D", "", v)               # '1 1 8 8' / '1188' from speech
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ToolArgError(f"'{key}' must be a number.")


def _str(args, key, required=True):
    v = args.get(key)
    if v in (None, ""):
        if required:
            raise ToolArgError(f"'{key}' is required.")
        return None
    return str(v).strip()


def _date(args, key, required=True):
    raw = _str(args, key, required)
    if raw is None:
        return None
    d = resolve_date(raw, config.get_now().date())
    if not d:
        raise ToolArgError(f"'{key}' is not a valid date. Use YYYY-MM-DD.")
    return d


def _time(args, key):
    t = normalize_time(_str(args, key))
    if not t:
        raise ToolArgError(f"'{key}' is not a valid time. Use HH:MM.")
    return t


def _spread(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def _compact(a: dict) -> dict:
    keys = ("reference_number", "doctor", "unit", "visit_type", "date", "weekday",
            "time", "duration_min", "status")
    return {k: a[k] for k in keys}


def _event(session, kind, **data):
    session.events.append({"type": kind, **data})


def do_transfer(session, reason: str) -> int:
    hid = calls.create_handoff(session.id, reason, session.patient_id)
    session.transferred, session.transfer_reason = True, reason
    _event(session, "TRANSFERRED", reason=reason)
    return hid


def _need_yes(args):
    if args.get("patient_confirmed") is not True:
        raise RuleError("CONFIRMATION_REQUIRED", "Read the details back to the caller and get a clear yes first, "
                        "then call again with patient_confirmed=true.")


def _must_be_offered(session, doctor_id, date, time):
    if (doctor_id, date, time) not in session.offered:
        raise RuleError("SLOT_NOT_OFFERED", "Only book a time that get_slots or find_next_available "
                        "returned in this call. Look up the slots first.")


def _doctor_of(session, ref: int) -> int:
    if ref not in session.seen_appointments:
        for a in pms.get_patient_appointments(session.token, upcoming_only=False):
            session.seen_appointments[a["reference_number"]] = a["doctor_id"]
    if ref not in session.seen_appointments:
        raise RuleError("APPOINTMENT_NOT_FOUND", "I could not find that appointment on your record.", 404)
    return session.seen_appointments[ref]


# ----------------------------------------------------------------- handlers
def _find_doctors(s, a):
    docs = pms.list_doctors(_int(a, "unit_id", False), _str(a, "name", False))[:10]
    if not docs:
        return {"doctors": [], "message": "No matching doctor."}
    return {"doctors": [{"doctor_id": d["doctor_id"], "name": d["name"], "specialty": d["unit"]} for d in docs]}


def _get_slots(s, a):
    doctor_id, rov_id, date = _int(a, "doctor_id"), _int(a, "rov_id"), _date(a, "date")
    res = pms.get_slots(doctor_id, date, rov_id)
    slots = res["slots"]
    after, before = _str(a, "after", False), _str(a, "before", False)
    if after:
        slots = [t for t in slots if t > (normalize_time(after) or "00:00")]
    if before:
        slots = [t for t in slots if t < (normalize_time(before) or "23:59")]
    for t in res["slots"]:
        s.offered.add((doctor_id, date, t))
    out = {"doctor_id": doctor_id, "doctor": res["doctor"], "date": date, "weekday": res["weekday"],
           "visit_type": res["visit_type"], "free_count": len(slots),
           "slots_shown": _spread(slots, ai_config.MAX_SLOTS_SHOWN)}
    if not slots:
        out["message"] = "No free times that day (doctor off, fully booked, or filter too narrow)."
    return out


def _find_next(s, a):
    opts = pms.get_next_available(_int(a, "rov_id"), doctor_id=_int(a, "doctor_id", False),
                                  unit_id=_int(a, "unit_id", False), from_date=_date(a, "from_date", False))
    for o in opts:
        s.offered.add((o["doctor_id"], o["date"], o["time"]))
    return {"options": opts} if opts else {"options": [], "message": "Nothing free in the next two weeks."}


def _verify(s, a):
    try:
        r = pms.verify_patient(_int(a, "patient_id"), _str(a, "name", False), _str(a, "phone", False))
    except RuleError as e:
        if e.code in ("VERIFICATION_FAILED", "LOCKED_OUT"):
            s.verify_failures += 1
            _event(s, "VERIFY_FAILED")
            if s.verify_failures >= 2 or e.code == "LOCKED_OUT":
                do_transfer(s, "identity_check_failed")
                return {**e.to_dict(), "transferred": True}
        raise
    s.token, s.patient_id, s.first_name = r["token"], r["patient_id"], r["first_name"]
    _event(s, "VERIFIED")
    return {"verified": True, "first_name": r["first_name"]}


def _my_appointments(s, a):
    appts = pms.get_patient_appointments(s.token, upcoming_only=True)
    for x in appts:
        s.seen_appointments[x["reference_number"]] = x["doctor_id"]
    return {"appointments": [_compact(x) for x in appts]} if appts else {"appointments": [], "message": "No upcoming appointments."}


def _book(s, a):
    _need_yes(a)
    doctor_id, rov_id, date, time = _int(a, "doctor_id"), _int(a, "rov_id"), _date(a, "date"), _time(a, "time")
    _must_be_offered(s, doctor_id, date, time)
    notes = (_str(a, "notes", False) or "")[:200] or None
    appt = pms.create_appointment(s.token, doctor_id, rov_id, date, time, notes)
    s.seen_appointments[appt["reference_number"]] = doctor_id
    _event(s, "BOOKED", ref=appt["reference_number"])
    return {"booked": True, **_compact(appt)}


def _reschedule(s, a):
    _need_yes(a)
    ref, date, time = _int(a, "appointment_id"), _date(a, "new_date"), _time(a, "new_time")
    new_doc = _int(a, "new_doctor_id", False)
    _must_be_offered(s, new_doc or _doctor_of(s, ref), date, time)
    appt = pms.reschedule_appointment(s.token, ref, date, time, new_doc)
    s.seen_appointments[ref] = appt["doctor_id"]
    _event(s, "RESCHEDULED", ref=ref)
    return {"rescheduled": True, **_compact(appt)}


def _cancel(s, a):
    _need_yes(a)
    ref = _int(a, "appointment_id")
    appt = pms.cancel_appointment(s.token, ref)
    _event(s, "CANCELLED", ref=ref)
    return {"cancelled": True, **_compact(appt)}


def _confirm(s, a):
    ref = _int(a, "appointment_id")
    appt = pms.confirm_appointment(s.token, ref)
    _event(s, "CONFIRMED", ref=ref)
    return {"confirmed": True, **_compact(appt)}


def _transfer(s, a):
    do_transfer(s, (_str(a, "reason", False) or "requested_by_model")[:100])
    return {"transferred": True}


def _end(s, a):
    s.end_requested = True
    return {"ok": True, "message": "Say a short goodbye."}


HANDLERS = {"find_doctors": _find_doctors, "get_slots": _get_slots, "find_next_available": _find_next,
            "verify_patient": _verify, "get_my_appointments": _my_appointments, "book_appointment": _book,
            "reschedule_appointment": _reschedule, "cancel_appointment": _cancel,
            "confirm_appointment": _confirm, "transfer_to_agent": _transfer, "end_call": _end}


def run_tool(session, name: str, args: dict) -> dict:
    """Run one model-requested tool. Always returns a dict; never raises."""
    if name not in HANDLERS:
        return _err("UNKNOWN_TOOL", f"There is no tool called '{name}'.")
    if name in GATED and not session.verified:
        return _err("NOT_VERIFIED_YET", "Verify the caller first with verify_patient "
                    "(patient file number plus phone or name).")
    try:
        return HANDLERS[name](session, args if isinstance(args, dict) else {})
    except RuleError as e:
        return e.to_dict()
    except ToolArgError as e:
        return _err("BAD_ARGUMENTS", str(e))
    except Exception:
        log.exception("Tool %s failed", name)
        return _err("INTERNAL", "Something went wrong with that action.")
