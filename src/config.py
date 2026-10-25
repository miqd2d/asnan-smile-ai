"""
config.py - ALL tunable settings and business rules live here.

Why: the clinic has not confirmed several rules (capacity, notice period...).
Keeping them in one file means a rule change is a one-line edit, and the
README can list every assumption in one place.
"""
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---- Database -------------------------------------------------------------
# Override with an environment variable (the tests use this to work on a copy).
DB_PATH = Path(os.environ.get("DENTAL_DB", ROOT / "db" / "clinic.db"))

# ---- Slot generation ------------------------------------------------------
STEP_MIN = 15      # slots start on a 15-minute grid (09:00, 09:15, ...)
CAPACITY = 1       # appointments allowed at the same time per doctor.
                   # ASSUMPTION: real data shows some doctors with 2-3 overlapping;
                   # confirm with the clinic.

# ---- Booking rules --------------------------------------------------------
BOOKING_MIN_LEAD_MINUTES = 60     # cannot book a slot starting within the next hour
MAX_DAYS_AHEAD = 60               # cannot book further ahead than this
CHANGE_MIN_NOTICE_HOURS = 24      # cancel / reschedule needs this much notice
                                  # ASSUMPTION: confirm the real policy with the clinic.

# ---- Identity verification ------------------------------------------------
# Patient ID is always required. On top of it the caller must match this many of the
# optional extras (name, phone):  1 = recommended,  0 = patient ID only (demo-simple, but
# anyone who guesses an ID could view/cancel that patient's appointments).
VERIFY_FACTORS_REQUIRED = 1
NAME_MATCH_THRESHOLD = 0.85       # how close a spoken name part must be (0-1)
PHONE_DIGITS = 8                  # Kuwait numbers are 8 digits; +965 / 00965 prefixes are ignored
MAX_VERIFY_ATTEMPTS = 3           # failed attempts per patient ID before lock-out
VERIFY_LOCKOUT_MIN = 15
TOKEN_TTL_MIN = 15                # a verification token expires after this

# ---- Conversation helpers (used by the AI layer later) ---------------------
MAX_SLOTS_OFFERED = 4             # the AI reads at most this many options aloud

# ---- Status names as they appear in the PMS (statuses table) ---------------
STATUS_BOOK = "Book"
STATUS_CONFIRM = "Confirm"
STATUS_CANCEL = "Cancel"
STATUS_RESCHEDULE = "Reschedule"           # closed (old) version of a moved appointment
CHANGEABLE_STATUSES = (STATUS_BOOK, STATUS_CONFIRM, "Rescheduled")


def get_now() -> datetime:
    """Current time. Set DEMO_NOW=2026-10-26T09:00 to freeze the clock for demos/tests."""
    fixed = os.environ.get("DEMO_NOW")
    if fixed:
        return datetime.fromisoformat(fixed)
    return datetime.now().replace(second=0, microsecond=0)
