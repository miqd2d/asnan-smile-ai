"""
rules.py - The rulebook. The AI proposes; these checks decide.

Every check raises RuleError when something is not allowed. RuleError carries:
  code         machine-readable ("SLOT_TAKEN") - tests and the AI can branch on it
  message      plain English the AI can safely read to the caller
  http_status  suggested HTTP code for main.py
"""
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher

import config
from slots import FMT, get_available_slots


class RuleError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status

    def to_dict(self):
        return {"error": self.code, "message": self.message}


# --------------------------------------------------------------- parsing
def parse_date(date: str) -> datetime:
    try:
        return datetime.strptime(date, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise RuleError("BAD_DATE", "The date must look like 2026-11-03.")


def parse_start(date: str, time: str) -> datetime:
    try:
        return datetime.strptime(f"{date} {time}", FMT)
    except (TypeError, ValueError):
        raise RuleError("BAD_TIME", "The date/time must look like 2026-11-03 and 14:30.")


# --------------------------------------------------------------- time rules
def check_bookable_time(start: datetime, now: datetime) -> None:
    if start <= now + timedelta(minutes=config.BOOKING_MIN_LEAD_MINUTES):
        raise RuleError("TOO_SOON", "That time is in the past or too close to now to book. "
                        "Please choose a later slot.")
    if start > now + timedelta(days=config.MAX_DAYS_AHEAD):
        raise RuleError("TOO_FAR", f"Appointments can only be booked up to "
                        f"{config.MAX_DAYS_AHEAD} days ahead.")


def check_enough_notice(start: datetime, now: datetime) -> None:
    if start - now < timedelta(hours=config.CHANGE_MIN_NOTICE_HOURS):
        raise RuleError("TOO_LATE_TO_CHANGE",
                        f"Changes need at least {config.CHANGE_MIN_NOTICE_HOURS} hours' notice. "
                        "I can transfer you to a team member who can help.", 409)


# --------------------------------------------------------------- catalogue rules
def check_doctor(con, doctor_id: int):
    row = con.execute("""SELECT d.doctor_id, d.name, d.is_bookable, d.unit_id, u.name AS unit
                         FROM doctors d LEFT JOIN units u USING(unit_id)
                         WHERE d.doctor_id = ?""", (doctor_id,)).fetchone()
    if not row:
        raise RuleError("DOCTOR_NOT_FOUND", "I could not find that doctor.", 404)
    if not row["is_bookable"]:
        raise RuleError("DOCTOR_NOT_BOOKABLE", "That staff member cannot be booked directly.")
    return row


def check_visit_type(con, rov_id: int):
    row = con.execute("SELECT * FROM visit_types WHERE rov_id = ?", (rov_id,)).fetchone()
    if not row:
        raise RuleError("VISIT_TYPE_NOT_FOUND", "I could not find that type of visit.", 404)
    if not row["active"] or not row["patient_bookable"]:
        raise RuleError("VISIT_TYPE_NOT_BOOKABLE",
                        "That type of visit cannot be booked by phone. "
                        "I can book a consultation or transfer you to a team member.")
    return row


def check_slot_available(con, doctor_id: int, start: datetime, duration_min: int,
                         exclude_appointment_id: int | None = None) -> None:
    """The final guard against double booking. Uses the same engine that offered the slot."""
    date = start.strftime("%Y-%m-%d")
    works = con.execute("SELECT 1 FROM schedules WHERE doctor_id=? AND work_date=?",
                        (doctor_id, date)).fetchone()
    if not works:
        raise RuleError("DOCTOR_NOT_WORKING", "The doctor is not working on that day.", 409)
    free = get_available_slots(doctor_id, date, duration_min,
                               exclude_appointment_id=exclude_appointment_id, con=con)
    if start.strftime("%H:%M") not in free:
        raise RuleError("SLOT_TAKEN", "That time is no longer available. "
                        "Please choose another slot.", 409)


def check_patient_free(con, patient_id: int, start: datetime, duration_min: int,
                       exclude_appointment_id: int | None = None) -> None:
    """A patient cannot be in two places at once."""
    end = start + timedelta(minutes=duration_min)
    rows = con.execute("""
        SELECT a.start_datetime, a.duration_min FROM appointments a
        JOIN statuses s ON s.status_id = a.status_id
        WHERE a.patient_id = ? AND s.occupies_slot = 1 AND a.is_block = 0
          AND date(a.start_datetime) = ? AND a.appointment_id != ?
    """, (patient_id, start.strftime("%Y-%m-%d"), exclude_appointment_id or -1)).fetchall()
    for r in rows:
        s = datetime.strptime(r["start_datetime"], FMT)
        if s < end and s + timedelta(minutes=r["duration_min"]) > start:
            raise RuleError("PATIENT_CONFLICT",
                            "You already have another appointment at that time.", 409)


# --------------------------------------------------------------- appointment rules
def check_owner_and_changeable(row, patient_id: int) -> None:
    """row = the appointment; it must belong to this patient and still be open."""
    if row is None or row["patient_id"] != patient_id or row["is_block"]:
        # same message for "does not exist" and "belongs to someone else":
        # never reveal other patients' data
        raise RuleError("APPOINTMENT_NOT_FOUND",
                        "I could not find that appointment on your record.", 404)
    if row["status_name"] not in config.CHANGEABLE_STATUSES:
        raise RuleError("NOT_CHANGEABLE",
                        f"That appointment is {row['status_name']} and cannot be changed.", 409)


# --------------------------------------------------------------- identity
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "sheikh", "mstr", "baby"}


def _tokens(name: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (name or "").lower())
    return [t for t in cleaned.split() if t not in _TITLES]


def name_matches(spoken: str, stored: str) -> bool:
    """
    Forgiving but safe name comparison (speech-to-text mangles spellings).
    Accepts if the whole names are very similar, OR every spoken word fuzzy-matches
    a stored word and the caller gave at least two words (if the record has two or more).
    A single first name alone is never enough.
    """
    a, b = _tokens(spoken), _tokens(stored)
    if not a or not b:
        return False
    t = config.NAME_MATCH_THRESHOLD
    compact = SequenceMatcher(None, "".join(sorted(a)), "".join(sorted(b))).ratio()
    if compact >= t:
        return True
    covered = all(any(SequenceMatcher(None, x, y).ratio() >= t for y in b) for x in a)
    return covered and len(a) >= min(2, len(b))
