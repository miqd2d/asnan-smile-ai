"""
tools.py - What the model may DO: 8 tools. Everything else is done by code.

The model only chooses a tool and its arguments. For anything the caller must hear (times, lists,
read-backs, results) the tool returns a ready-made "say" text, and the loop speaks THAT.
Identity is not a model tool: when a tool needs a verified caller, code collects the details itself.
"""
import logging
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import config
import pms
import rules
from db import connect
from rules import RuleError
from slots import get_available_slots

from . import ai_config, calls, speech
from .dates import normalize_time, resolve_date, weekday_name

log = logging.getLogger("uvicorn.error")
ANY_WORDS = {"any", "anyone", "anybody", "no preference", "whoever", "أي", "اي", "اي واحد", "أي طبيب"}


class ToolArgError(Exception):
    pass


def _fn(name, description, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


_INT, _STR = {"type": "integer"}, {"type": "string"}

SCHEMAS = {s["function"]["name"]: s for s in [
    _fn("check_availability",
        "Look up free appointment times. Use for ANY question about availability, times, or booking a visit, "
        "and also to find new times when rescheduling. Returns a numbered list of options that the system "
        "reads to the caller. Pass the visit type, plus the doctor, specialty and day if the caller said them.",
        {"visit_type_id": {**_INT, "description": "Id from the VISIT TYPES list. Required for a new booking."},
         "doctor_name": {**_STR, "description": "Doctor's name as the caller said it. Use 'any' if they have no preference."},
         "specialty_id": {**_INT, "description": "Id from the SPECIALTIES list, when no doctor is named."},
         "date": {**_STR, "description": "YYYY-MM-DD, or a word: today, tomorrow, wednesday, next sunday, الأربعاء. Leave out for the earliest times."},
         "after": {**_STR, "description": "HH:MM. Only times later than this (e.g. 'in the evening' = 16:00)."},
         "before": {**_STR, "description": "HH:MM. Only times earlier than this."},
         "appointment": {**_INT, "description": "ONLY when rescheduling: the number of the appointment from get_my_appointments."}}),
    _fn("get_my_appointments",
        "Show the caller's upcoming appointments as a numbered list. Always use this first when the caller "
        "wants to see, cancel or change an appointment."),
    _fn("book_appointment",
        "Book one of the times that check_availability offered. Pass the option number the caller chose. "
        "The system then reads the details back and asks the caller to confirm; you do not.",
        {"option": {**_INT, "description": "Number of the chosen option (1, 2, 3...)."},
         "notes": {**_STR, "description": "The caller's own words about the problem, if any."}}, ["option"]),
    _fn("reschedule_appointment",
        "Move an existing appointment to a new time. First use get_my_appointments, then check_availability "
        "with appointment=N, then call this with that appointment number and the chosen option number.",
        {"appointment": {**_INT, "description": "Number of the appointment in the caller's list."},
         "option": {**_INT, "description": "Number of the new time from check_availability."}},
        ["appointment", "option"]),
    _fn("cancel_appointment",
        "Cancel an existing appointment. First use get_my_appointments, then pass the number of the appointment. "
        "The system asks the caller to confirm.",
        {"appointment": {**_INT, "description": "Number of the appointment in the caller's list."}}, ["appointment"]),
    _fn("transfer_to_agent",
        "Transfer the call to a human. Use for complaints, prices, insurance, medical questions, anything you "
        "cannot do, or when the caller asks for a person.", {"reason": _STR}, ["reason"]),
    _fn("end_call", "End the call. Use when the caller says goodbye or has nothing else to do."),
]}
GATED = {"get_my_appointments", "book_appointment", "reschedule_appointment", "cancel_appointment"}


def tools_for(session) -> list[dict]:
    return list(SCHEMAS.values())             # the same 7 tools every turn: stable for a small model


def forget_identity(session) -> None:
    session.token, session.first_name = None, None
    session.id_scan_from = len(session.transcript)       # after an expiry, ask again: do not reuse old statements
    session.events.append({"type": "VERIFY_EXPIRED"})


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
    try:
        return int(v)
    except (TypeError, ValueError):
        digits = "".join(c for c in str(v) if c.isdigit())
        if digits:
            return int(digits)
        raise ToolArgError(f"'{key}' must be a number.")


def _str(args, key):
    v = args.get(key)
    return None if v in (None, "") else str(v).strip()


def _event(session, kind, **data):
    session.events.append({"type": kind, **data})


def do_transfer(session, reason: str) -> int:
    hid = calls.create_handoff(session.id, reason, session.patient_id)
    session.transferred, session.transfer_reason = True, reason
    session.pending, session.awaiting_identity, session.resume = None, False, None
    _event(session, "TRANSFERRED", reason=reason)
    return hid


def _compact(a: dict) -> dict:
    keys = ("reference_number", "doctor_id", "doctor", "unit", "visit_type", "date", "weekday",
            "time", "duration_min", "status")
    return {k: a[k] for k in keys}


def _spread(items: list, n: int) -> list:
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def _resolve_doctor(name: str, unit_id):
    """-> ('one', doctor) | ('ask', [names]) | ('none', None). Ranks by how many spoken words match."""
    docs = pms.list_doctors(unit_id, name)
    wanted = rules._tokens(name)

    def score(d):
        parts = rules._tokens(d["name"])
        return sum(any(SequenceMatcher(None, w, p).ratio() >= 0.8 for p in parts) for w in wanted)
    if not docs:
        return "none", None
    best = max(score(d) for d in docs)
    cands = [d for d in docs if score(d) == best]
    return ("one", cands[0]) if len(cands) == 1 else ("ask", [d["name"] for d in cands])


def _resolve_appt(s, value: int) -> dict:
    if 1 <= value <= len(s.appts):
        return s.appts[value - 1]
    for a in s.appts:
        if a["reference_number"] == value:
            return a
    raise RuleError("APPOINTMENT_NOT_LISTED", "Call get_my_appointments first, then use the number "
                    "of the appointment from that list.")


def _gather(docs, days, duration, after, before, earliest, exclude, con):
    found = []
    for day in days:
        for d in docs:
            for t in get_available_slots(d["doctor_id"], day, duration, earliest=earliest,
                                         exclude_appointment_id=exclude, con=con):
                if (after and t <= after) or (before and t >= before):
                    continue
                found.append((day, t, d))
    found.sort(key=lambda x: (x[0], x[1], x[2]["doctor_id"]))
    return found


def _choose(found, single, limit):
    if single:
        return _spread(found, limit)
    first_per_group = {}
    for f in found:                                    # earliest time for each (day, doctor)
        first_per_group.setdefault((f[0], f[2]["doctor_id"]), f)
    return sorted(first_per_group.values(), key=lambda x: (x[0], x[1]))[:limit]


# ----------------------------------------------------------------- handlers
def _check_availability(s, a):
    lang, ctx = s.lang, s.ctx
    vts = {v["rov_id"]: v for v in pms.list_visit_types()}
    appointment_value = a.get("appointment")
    appt = (
        _resolve_appt(s, _int(a, "appointment"))
        if appointment_value not in (None, "")
        else None
    )

    if appt:
        # Remember which existing appointment is being rescheduled.
        s.ctx["reschedule_appointment"] = appt["n"]
    else:
        # A normal availability lookup is for a new booking.
        s.ctx.pop("reschedule_appointment", None)
    if appt:
        duration, rov, vname = appt["duration_min"], None, appt["visit_type"]
    else:
        rov = _int(a, "visit_type_id", False) or ctx.get("visit_type_id")
        if not rov:
            raise ToolArgError("'visit_type_id' is required: pick it from the VISIT TYPES list.")
        if rov not in vts:
            raise RuleError("VISIT_TYPE_NOT_BOOKABLE", "That visit type is not bookable. "
                            "Choose an id from the VISIT TYPES list.")
        duration, vname = vts[rov]["duration_min"], vts[rov]["name"]

    unit = _int(a, "specialty_id", False) or ctx.get("specialty_id")
    name = _str(a, "doctor_name")
    doctor = None
    if name and name.lower() in ANY_WORDS:
        ctx.pop("doctor_id", None); ctx.pop("doctor", None)
    elif name:
        status, found = _resolve_doctor(name, unit)
        if status == "none":
            return {"say": speech.no_such_doctor(lang)}
        if status == "ask":
            return {"say": speech.ask_which_doctor(found, lang)}
        doctor = found
    elif appt:
        doctor = {"doctor_id": appt["doctor_id"], "name": appt["doctor"], "unit": appt.get("unit")}
    elif ctx.get("doctor_id"):
        doctor = {"doctor_id": ctx["doctor_id"], "name": ctx["doctor"]}
    docs = [doctor] if doctor else pms.list_doctors(unit_id=unit)

    now = config.get_now()
    earliest = now + timedelta(minutes=config.BOOKING_MIN_LEAD_MINUTES)
    date = None
    if _str(a, "date"):
        date = resolve_date(_str(a, "date"), now.date())
        if not date:
            raise ToolArgError("'date' is not a valid date. Use YYYY-MM-DD or a word like tomorrow.")
    after = normalize_time(_str(a, "after")) if _str(a, "after") else None
    before = normalize_time(_str(a, "before")) if _str(a, "before") else None
    exclude = appt["reference_number"] if appt else None
    limit = ai_config.MAX_OPTIONS

    def days_from(d0):
        return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(14)]
    today = datetime(now.year, now.month, now.day)

    con = connect()
    try:
        if date:
            found = _gather(docs, [date], duration, after, before, earliest, exclude, con)
            picks = _choose(found, len(docs) == 1, limit)
            header_none = not picks
            if header_none:
                start = datetime.strptime(date, "%Y-%m-%d")
                picks = _choose(_gather(docs, days_from(max(start, today)), duration, after, before,
                                        earliest, exclude, con), len(docs) == 1, limit)
        else:
            picks = _choose(_gather(docs, days_from(today), duration, after, before, earliest, exclude, con),
                            False, limit)
            header_none = False
    finally:
        con.close()

    ctx.update({"visit_type_id": rov or ctx.get("visit_type_id"), "visit_type": vname if rov else ctx.get("visit_type"),
                "specialty_id": unit, "last_day": date})
    if doctor:
        ctx["doctor_id"], ctx["doctor"] = doctor["doctor_id"], doctor["name"]
    s.options = [{"n": i, "doctor_id": d["doctor_id"], "doctor": d["name"], "date": day, "time": t,
                  "weekday": weekday_name(day), "rov_id": rov, "visit_type": vname}
                 for i, (day, t, d) in enumerate(picks, 1)]
    if not s.options:
        s.ctx.pop("reschedule_appointment", None)
        return {
            "say": speech.nothing_free(lang),
            "options": [],
        }
    if header_none:
        shown = speech.day_str(weekday_name(date), date, lang)
        return {"say": speech.none_that_day(s.options, shown, lang), "options": s.options}
    return {"say": speech.options_say(s.options, lang), "options": s.options}


def _my_appointments(s, a):
    s.options = []
    s.ctx.pop("reschedule_appointment", None)

    appts = pms.get_patient_appointments(
        s.token,
        upcoming_only=True,
    )

    s.appts = [
        {"n": i, **_compact(x)}
        for i, x in enumerate(appts, 1)
    ]

    return {
        "say": speech.appointments_say(s.appts, s.lang),
        "appointments": s.appts,
    }


def _need_options(s, n):
    if not s.options:
        raise RuleError("NO_OPTIONS", "No times have been offered yet. Call check_availability first.")
    if not 1 <= n <= len(s.options):
        raise RuleError("BAD_OPTION", f"Option {n} does not exist. Choose between 1 and {len(s.options)}.")
    return s.options[n - 1]


def _book(s, a):
    opt = _need_options(s, _int(a, "option"))
    notes = (_str(a, "notes") or "")[:200] or None
    s.pending = {"type": "book", "option": opt, "visit_type": opt["visit_type"], "notes": notes}
    return {"say": speech.readback(s.pending, s.lang), "pending": True}


def _reschedule(s, a):
    old = _resolve_appt(s, _int(a, "appointment"))
    opt = _need_options(s, _int(a, "option"))

    rules.check_enough_notice(
        datetime.strptime(
            f"{old['date']} {old['time']}",
            "%Y-%m-%d %H:%M",
        ),
        config.get_now(),
    )

    s.pending = {
        "type": "reschedule",
        "old": old,
        "option": opt,
    }

    return {
        "say": speech.readback(s.pending, s.lang),
        "pending": True,
    }


def _cancel(s, a):
    old = _resolve_appt(s, _int(a, "appointment"))
    rules.check_enough_notice(datetime.strptime(f"{old['date']} {old['time']}", "%Y-%m-%d %H:%M"), config.get_now())
    s.pending = {"type": "cancel", "old": old}
    return {"say": speech.readback(s.pending, s.lang), "pending": True}


def _transfer(s, a):
    do_transfer(s, (_str(a, "reason") or "requested_by_model")[:100])
    return {"say": speech.REPLIES_TRANSFER[s.lang], "transferred": True}


def _end(s, a):
    s.end_requested = True
    return {"say": speech.goodbye(s.lang)}


HANDLERS = {"check_availability": _check_availability, "get_my_appointments": _my_appointments,
            "book_appointment": _book, "reschedule_appointment": _reschedule,
            "cancel_appointment": _cancel, "transfer_to_agent": _transfer, "end_call": _end}


def execute_pending(s) -> dict:
    """Runs the action the caller just said yes to. Returns the event (used for the receipt)."""
    p, s.pending = s.pending, None
    if p["type"] == "book":
        o = p["option"]
        appt = pms.create_appointment(s.token, o["doctor_id"], o["rov_id"], o["date"], o["time"], p["notes"])
        kind, ref = "BOOKED", appt["reference_number"]
    elif p["type"] == "reschedule":
        o, ref = p["option"], p["old"]["reference_number"]
        new_doc = o["doctor_id"] if o["doctor_id"] != p["old"]["doctor_id"] else None
        appt = pms.reschedule_appointment(s.token, ref, o["date"], o["time"], new_doc)
        kind = "RESCHEDULED"
    else:
        ref = p["old"]["reference_number"]
        appt = pms.cancel_appointment(s.token, ref)
        kind = "CANCELLED"
    s.options, s.appts = [], []
    s.ctx.pop("reschedule_appointment", None)
    e = {"type": kind, "ref": ref, "appt": _compact(appt)}
    s.events.append(e)
    return e


def run_tool(session, name: str, args: dict) -> dict:
    """Run one model-requested tool. Always returns a dict; never raises."""
    if name not in HANDLERS:
        return _err("UNKNOWN_TOOL", f"There is no tool called '{name}'.")
    args = args if isinstance(args, dict) else {}
    if name in GATED and not session.verified:           # code, not the model, will collect the details
        session.awaiting_identity, session.resume = True, {"tool": name, "args": args}
        return {"need_identity": True}
    try:
        result = HANDLERS[name](session, args)
        if session.pending is not None and "call" not in session.pending:
            session.pending["call"] = {"tool": name, "args": args}
        return result
    except RuleError as e:
        if e.code == "NOT_VERIFIED" and name in GATED:
            forget_identity(session)
            session.awaiting_identity, session.resume = True, {"tool": name, "args": args}
            return {"need_identity": True}
        if e.code in ("TOO_LATE_TO_CHANGE", "NOT_CHANGEABLE", "APPOINTMENT_NOT_FOUND"):
            return {"say": speech.error_text(e.code, e.message, session.lang), **e.to_dict()}
        return e.to_dict()
    except ToolArgError as e:
        return _err("BAD_ARGUMENTS", str(e))
    except Exception:
        log.exception("Tool %s failed", name)
        return _err("INTERNAL", "Something went wrong with that action.")
