"""
pms.py - The mock "Asnan Tower" PMS: the functions the AI agent may call.

Layering (who knows what):
    slots.py  -> time arithmetic only
    rules.py  -> what is allowed
    pms.py    -> combines both into actions (this file)
    main.py   -> HTTP only; each endpoint calls ONE function from here

Identity: verify_patient() hands back a short-lived token. Every function that
touches a patient's appointments needs that token, so the AI cannot act on a
record it has not verified - even if the model makes a mistake.
"""
import secrets
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import config
import rules
from db import connect, transaction
from rules import RuleError
from slots import FMT, get_available_slots

# in-memory state (fine for a single-process prototype; production would use Redis/DB)
_tokens: dict[str, tuple[int, datetime]] = {}          # token -> (patient_id, expires)
_failed: dict[int, tuple[int, datetime | None]] = {}   # patient_id -> (attempts, locked_until)


def reset_security_state() -> None:
    """Clear tokens and lock-outs (used by tests)."""
    _tokens.clear()
    _failed.clear()


# =========================================================== identity
def verify_patient(patient_id: int, name: str | None = None, phone: str | None = None) -> dict:
    """
    Patient ID (required) + enough of the optional extras (name, phone) to reach
    config.VERIFY_FACTORS_REQUIRED. Names and phones are matched loosely (see rules.py).
    Returns a short-lived token on success.
    """
    now = config.get_now()
    name, phone = (name or "").strip() or None, (phone or "").strip() or None
    attempts, locked_until = _failed.get(patient_id, (0, None))
    if locked_until and now < locked_until:
        raise RuleError("LOCKED_OUT", "Too many failed attempts. I will transfer you "
                        "to a team member.", 429)
    if (name is not None) + (phone is not None) < config.VERIFY_FACTORS_REQUIRED:
        # not a failed attempt: the caller simply has not been asked for enough yet
        raise RuleError("MORE_INFO_NEEDED", "Please also tell me the phone number "
                        "or the name on the file.", 400)

    con = connect()
    try:
        row = con.execute("SELECT patient_id, name, phone FROM patients WHERE patient_id = ?",
                          (patient_id,)).fetchone()
    finally:
        con.close()

    matched = []
    if row and name and rules.name_matches(name, row["name"]):
        matched.append("name")
    if row and phone and rules.phone_matches(phone, row["phone"]):
        matched.append("phone")

    if not row or len(matched) < config.VERIFY_FACTORS_REQUIRED:
        attempts += 1
        locked = now + timedelta(minutes=config.VERIFY_LOCKOUT_MIN) \
            if attempts >= config.MAX_VERIFY_ATTEMPTS else None
        _failed[patient_id] = (attempts, locked)
        # one generic message: never reveal which detail was wrong
        raise RuleError("VERIFICATION_FAILED", "I could not verify those details.", 403)

    _failed.pop(patient_id, None)
    token = secrets.token_urlsafe(16)
    _tokens[token] = (patient_id, now + timedelta(minutes=config.TOKEN_TTL_MIN))
    first = (rules._tokens(row["name"]) or ["there"])[0].capitalize()
    return {"verified": True, "token": token, "patient_id": patient_id,
            "first_name": first, "matched_on": matched}


def _require_patient(token: str) -> int:
    entry = _tokens.get(token or "")
    if not entry or config.get_now() > entry[1]:
        _tokens.pop(token or "", None)
        raise RuleError("NOT_VERIFIED", "Identity must be verified first.", 401)
    return entry[0]


def get_patient_phone(patient_id: int) -> str | None:
    """INTERNAL (for the notifier). Never expose this through an API route."""
    con = connect()
    try:
        r = con.execute("SELECT phone FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
        return r["phone"] if r else None
    finally:
        con.close()


# =========================================================== catalogue (no login needed)
def list_units() -> list[dict]:
    con = connect()
    try:
        rows = con.execute("""
            SELECT u.unit_id, u.name, COUNT(d.doctor_id) AS doctors
            FROM units u JOIN doctors d ON d.unit_id = u.unit_id AND d.is_bookable = 1
            GROUP BY u.unit_id ORDER BY u.name""").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_visit_types() -> list[dict]:
    con = connect()
    try:
        rows = con.execute("""SELECT rov_id, name, duration_min FROM visit_types
                              WHERE active = 1 AND patient_bookable = 1 ORDER BY name""").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def list_doctors(unit_id: int | None = None, name: str | None = None) -> list[dict]:
    """Bookable doctors. `name` does a forgiving match ('doctor tarek' finds 'Tareq')."""
    con = connect()
    try:
        sql = """SELECT d.doctor_id, d.name, d.unit_id, u.name AS unit
                 FROM doctors d JOIN units u USING(unit_id) WHERE d.is_bookable = 1"""
        params: list = []
        if unit_id is not None:
            sql += " AND d.unit_id = ?"
            params.append(unit_id)
        docs = [dict(r) for r in con.execute(sql + " ORDER BY d.name", params)]
    finally:
        con.close()
    if name:
        wanted = rules._tokens(name)
        def hit(doc):
            parts = rules._tokens(doc["name"])
            return any(SequenceMatcher(None, w, p).ratio() >= 0.8 for w in wanted for p in parts)
        docs = [d for d in docs if hit(d)]
    return docs


# =========================================================== availability
def get_slots(doctor_id: int, date: str, rov_id: int) -> dict:
    """Free start times for one doctor, one date, one visit type."""
    now = config.get_now()
    rules.parse_date(date)
    con = connect()
    try:
        doc = rules.check_doctor(con, doctor_id)
        vt = rules.check_visit_type(con, rov_id)
        earliest = now + timedelta(minutes=config.BOOKING_MIN_LEAD_MINUTES)
        slots = get_available_slots(doctor_id, date, vt["duration_min"],
                                    earliest=earliest, con=con)
    finally:
        con.close()
    return {"doctor_id": doctor_id, "doctor": doc["name"], "date": date,
            "weekday": datetime.strptime(date, "%Y-%m-%d").strftime("%A"),
            "visit_type": vt["name"], "duration_min": vt["duration_min"], "slots": slots}


def get_next_available(rov_id: int, doctor_id: int | None = None, unit_id: int | None = None,
                       from_date: str | None = None, days_ahead: int = 14,
                       limit: int = config.MAX_SLOTS_OFFERED) -> list[dict]:
    """The earliest open slots across a doctor, a unit, or all doctors - for 'next week'/'soonest'."""
    now = config.get_now()
    con = connect()
    try:
        vt = rules.check_visit_type(con, rov_id)
        if doctor_id is not None:
            doctors = [rules.check_doctor(con, doctor_id)]
        else:
            q = "SELECT doctor_id FROM doctors WHERE is_bookable=1"
            p: list = []
            if unit_id is not None:
                q += " AND unit_id=?"
                p.append(unit_id)
            doctors = [rules.check_doctor(con, r["doctor_id"]) for r in con.execute(q, p)]
        start_day = rules.parse_date(from_date) if from_date else datetime(now.year, now.month, now.day)
        earliest = now + timedelta(minutes=config.BOOKING_MIN_LEAD_MINUTES)
        found = []
        for i in range(days_ahead):
            day = (start_day + timedelta(days=i)).strftime("%Y-%m-%d")
            for d in doctors:
                for t in get_available_slots(d["doctor_id"], day, vt["duration_min"],
                                             earliest=earliest, con=con):
                    found.append({"doctor_id": d["doctor_id"], "doctor": d["name"],
                                  "unit": d["unit"], "date": day, "time": t,
                                  "weekday": datetime.strptime(day, "%Y-%m-%d").strftime("%A")})
        found.sort(key=lambda x: (x["date"], x["time"]))
        return found[:limit]
    finally:
        con.close()


# =========================================================== appointments
def _status(con, name: str):
    r = con.execute("SELECT status_id, active_flag FROM statuses WHERE name = ?", (name,)).fetchone()
    if not r:
        raise RuleError("CONFIG_ERROR", f"Status '{name}' is missing from the database.", 500)
    return r["status_id"], r["active_flag"]


def _history(con, a, status_name: str, status_id: int, active_flag: int, original_start=None):
    con.execute("""INSERT INTO appointment_history
        (appointment_id, patient_id, doctor_id, rov_id, status_id, status_name, active_flag,
         start_datetime, original_start) VALUES (?,?,?,?,?,?,?,?,?)""",
        (a["appointment_id"], a["patient_id"], a["doctor_id"], a["rov_id"], status_id,
         status_name, active_flag, a["start_datetime"], original_start or a["start_datetime"]))


def _appointment_dict(con, appointment_id: int) -> dict:
    r = con.execute("""
        SELECT a.*, d.name AS doctor, u.name AS unit, v.name AS visit_type
        FROM appointments a
        LEFT JOIN doctors d ON d.doctor_id = a.doctor_id
        LEFT JOIN units u ON u.unit_id = a.unit_id
        LEFT JOIN visit_types v ON v.rov_id = a.rov_id
        WHERE a.appointment_id = ?""", (appointment_id,)).fetchone()
    start = datetime.strptime(r["start_datetime"], FMT)
    return {"reference_number": r["appointment_id"], "appointment_id": r["appointment_id"],
            "doctor_id": r["doctor_id"], "doctor": r["doctor"], "unit": r["unit"],
            "visit_type": r["visit_type"], "date": start.strftime("%Y-%m-%d"),
            "time": start.strftime("%H:%M"), "weekday": start.strftime("%A"),
            "duration_min": r["duration_min"], "status": r["status_name"], "notes": r["notes"]}


def _load_own(con, appointment_id: int, patient_id: int):
    row = con.execute("SELECT * FROM appointments WHERE appointment_id = ?",
                      (appointment_id,)).fetchone()
    rules.check_owner_and_changeable(row, patient_id)
    return row


def get_patient_appointments(token: str, upcoming_only: bool = True) -> list[dict]:
    patient_id = _require_patient(token)
    now = config.get_now()
    con = connect()
    try:
        rows = con.execute("""SELECT appointment_id, start_datetime FROM appointments
                              WHERE patient_id = ? AND is_block = 0 AND active_flag = 1
                              ORDER BY start_datetime""", (patient_id,)).fetchall()
        out = []
        for r in rows:
            if upcoming_only and datetime.strptime(r["start_datetime"], FMT) < now:
                continue
            out.append(_appointment_dict(con, r["appointment_id"]))
        return out
    finally:
        con.close()


def create_appointment(token: str, doctor_id: int, rov_id: int, date: str, time: str,
                       notes: str | None = None) -> dict:
    patient_id = _require_patient(token)
    now = config.get_now()
    start = rules.parse_start(date, time)
    rules.check_bookable_time(start, now)
    with transaction() as con:
        doc = rules.check_doctor(con, doctor_id)
        vt = rules.check_visit_type(con, rov_id)
        rules.check_slot_available(con, doctor_id, start, vt["duration_min"])
        rules.check_patient_free(con, patient_id, start, vt["duration_min"])
        new_id = con.execute("SELECT COALESCE(MAX(appointment_id), 0) + 1 FROM appointments").fetchone()[0]
        sid, active = _status(con, config.STATUS_BOOK)
        con.execute("""INSERT INTO appointments
            (appointment_id, patient_id, doctor_id, unit_id, location_id, rov_id, start_datetime,
             duration_min, status_id, status_name, active_flag, is_block, source, notes)
            VALUES (?,?,?,?,NULL,?,?,?,?,?,?,0,'ai_agent',?)""",
            (new_id, patient_id, doctor_id, doc["unit_id"], rov_id, start.strftime(FMT),
             vt["duration_min"], sid, config.STATUS_BOOK, active, (notes or "")[:500] or None))
        _history(con, {"appointment_id": new_id, "patient_id": patient_id, "doctor_id": doctor_id,
                       "rov_id": rov_id, "start_datetime": start.strftime(FMT)},
                 config.STATUS_BOOK, sid, active)
        return _appointment_dict(con, new_id)


def cancel_appointment(token: str, appointment_id: int) -> dict:
    patient_id = _require_patient(token)
    now = config.get_now()
    with transaction() as con:
        row = _load_own(con, appointment_id, patient_id)
        rules.check_enough_notice(datetime.strptime(row["start_datetime"], FMT), now)
        sid, active = _status(con, config.STATUS_CANCEL)
        con.execute("UPDATE appointments SET status_id=?, status_name=?, active_flag=? "
                    "WHERE appointment_id=?", (sid, config.STATUS_CANCEL, active, appointment_id))
        _history(con, row, config.STATUS_CANCEL, sid, active)
        return _appointment_dict(con, appointment_id)


def reschedule_appointment(token: str, appointment_id: int, new_date: str, new_time: str,
                           new_doctor_id: int | None = None) -> dict:
    """Moves the appointment. The reference number stays the same; the old time goes to history."""
    patient_id = _require_patient(token)
    now = config.get_now()
    new_start = rules.parse_start(new_date, new_time)
    with transaction() as con:
        row = _load_own(con, appointment_id, patient_id)
        old_start = datetime.strptime(row["start_datetime"], FMT)
        rules.check_enough_notice(old_start, now)
        rules.check_bookable_time(new_start, now)
        doctor_id = new_doctor_id or row["doctor_id"]
        doc = rules.check_doctor(con, doctor_id)
        if doctor_id == row["doctor_id"] and new_start == old_start:
            raise RuleError("SAME_SLOT", "That is the time you already have.", 409)
        rules.check_slot_available(con, doctor_id, new_start, row["duration_min"],
                                   exclude_appointment_id=appointment_id)
        rules.check_patient_free(con, patient_id, new_start, row["duration_min"],
                                 exclude_appointment_id=appointment_id)
        old_sid, old_active = _status(con, config.STATUS_RESCHEDULE)
        _history(con, row, config.STATUS_RESCHEDULE, old_sid, old_active)   # the closed old version
        new_sid, new_active = _status(con, "Rescheduled")
        con.execute("""UPDATE appointments SET doctor_id=?, unit_id=?, start_datetime=?,
                       status_id=?, status_name='Rescheduled', active_flag=? WHERE appointment_id=?""",
                    (doctor_id, doc["unit_id"], new_start.strftime(FMT), new_sid, new_active,
                     appointment_id))
        _history(con, {**dict(row), "doctor_id": doctor_id, "start_datetime": new_start.strftime(FMT)},
                 "Rescheduled", new_sid, new_active, original_start=row["start_datetime"])
        return _appointment_dict(con, appointment_id)


def confirm_appointment(token: str, appointment_id: int) -> dict:
    """Book -> Confirm (used when the patient replies 'yes' to a reminder)."""
    patient_id = _require_patient(token)
    with transaction() as con:
        row = _load_own(con, appointment_id, patient_id)
        if row["status_name"] != config.STATUS_CONFIRM:
            sid, active = _status(con, config.STATUS_CONFIRM)
            con.execute("UPDATE appointments SET status_id=?, status_name=?, active_flag=? "
                        "WHERE appointment_id=?", (sid, config.STATUS_CONFIRM, active, appointment_id))
            _history(con, row, config.STATUS_CONFIRM, sid, active)
        return _appointment_dict(con, appointment_id)
