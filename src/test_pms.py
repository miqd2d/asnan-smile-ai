"""
test_pms.py - Checkpoint tests for the PMS layer (no AI involved).

Run from the project root:   python tests/test_pms.py
It works on a COPY of clinic.db, so your real database is never changed.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# --- work on a temporary copy, with a frozen clock --------------------------
tmp = Path(tempfile.mkdtemp()) / "test.db"
shutil.copy(ROOT / "db" / "clinic.db", tmp)
os.environ["DENTAL_DB"] = str(tmp)
os.environ["DEMO_NOW"] = "2026-10-26T08:00"      # a Monday morning

con = sqlite3.connect(tmp)                       # apply the bookable visit-type list
con.executescript((ROOT / "src" / "curate.sql").read_text().split("-- Check")[0])
con.commit()
pa, pb = con.execute("SELECT patient_id, name FROM patients LIMIT 2").fetchall()
con.close()

import config, pms                                # noqa: E402  (after env is set)
from rules import RuleError                       # noqa: E402

DOCTOR, VISIT, DAY = 11, 39, "2026-10-28"         # Tareq, New Consultation (30 min), Wednesday
passed = failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


def raises(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except RuleError as e:
        return e.code == code
    return False


def spoken(stored):                               # "Ms. tibah mohammad alnomas" -> "tibah mohammad alnomas"
    return stored.split(". ", 1)[-1]


print("\n== Identity")
from rules import name_matches, phone_matches     # noqa: E402
con = sqlite3.connect(tmp)
phone_a = con.execute("SELECT phone FROM patients WHERE patient_id=?", (pa[0],)).fetchone()[0]
con.close()
ALS = "Mr. abdullah hadi Alsaffar"                 # patient 1188 from your data
check("one word is enough: 'Abdullah'", name_matches("Abdullah", ALS))
check("one word is enough: 'Saffar'", name_matches("Saffar", ALS))
check("'Al Saffar' (spoken apart) matches 'Alsaffar'", name_matches("Al Saffar", ALS))
check("title in speech ignored", name_matches("Mr Abdullah", ALS))
check("spelling variant: Abdulla", name_matches("Abdulla", ALS))
check("spelling variant: Ahmad vs AHMED", name_matches("Ahmad", "Mr. AHMED ALI GHALOOM"))
check("spelling variant: Mohamed vs Mohammad", name_matches("Mohamed", "Ms. tibah mohammad alnomas"))
check("different name refused", not name_matches("Khalid", ALS))
check("'Al' alone refused", not name_matches("Al", ALS))
check("title alone refused", not name_matches("Mr", ALS))
check("phone: +965 prefix ignored", phone_matches("+965 " + phone_a[-8:], phone_a))
check("phone: 00965 and dashes ignored", phone_matches("00965-" + phone_a[-8:-4] + "-" + phone_a[-4:], phone_a))
check("phone: too short refused", not phone_matches(phone_a[-4:], phone_a))

pms.reset_security_state()
check("ID + one name word accepted", pms.verify_patient(pa[0], spoken(pa[1]).split()[0])["matched_on"] == ["name"])
check("ID + last name word accepted", pms.verify_patient(pa[0], spoken(pa[1]).split()[-1])["verified"])
check("ID + phone accepted", pms.verify_patient(pa[0], phone=phone_a[-8:])["matched_on"] == ["phone"])
check("phone right, name wrong still accepted (STT may mangle names)",
      pms.verify_patient(pa[0], name="Nobody", phone=phone_a)["matched_on"] == ["phone"])
check("wrong name refused", raises("VERIFICATION_FAILED", pms.verify_patient, pa[0], "John Smith"))
check("wrong phone refused", raises("VERIFICATION_FAILED", pms.verify_patient, pa[0], phone="+96599999999"))
check("wrong id refused", raises("VERIFICATION_FAILED", pms.verify_patient, 999999999, spoken(pa[1])))
check("ID alone -> asks for more info", raises("MORE_INFO_NEEDED", pms.verify_patient, pa[0]))
config.VERIFY_FACTORS_REQUIRED = 0
check("ID alone works when policy is 0", pms.verify_patient(pa[0])["verified"])
config.VERIFY_FACTORS_REQUIRED = 1
pms.reset_security_state()
for _ in range(3):
    raises("VERIFICATION_FAILED", pms.verify_patient, pb[0], "Nobody Here")
check("locked after 3 failures", raises("LOCKED_OUT", pms.verify_patient, pb[0], spoken(pb[1])))
pms.reset_security_state()
ta = pms.verify_patient(pa[0], spoken(pa[1]).upper())["token"]
tb = pms.verify_patient(pb[0], spoken(pb[1]))["token"]
check("tokens issued", bool(ta and tb))
check("no token -> refused", raises("NOT_VERIFIED", pms.get_patient_appointments, "fake"))

print("\n== Catalogue")
check("15 bookable visit types", len(pms.list_visit_types()) == 15)
check("assistants never listed", all(d["doctor_id"] != 53 for d in pms.list_doctors()))
check("fuzzy doctor name ('tarek')", any(d["doctor_id"] == 11 for d in pms.list_doctors(name="tarek")))

print("\n== Booking checkpoint")
slots = pms.get_slots(DOCTOR, DAY, VISIT)["slots"]
check("doctor has slots on a working day", len(slots) > 0)
first = slots[0]
appt = pms.create_appointment(ta, DOCTOR, VISIT, DAY, first, notes="toothache since last night")
check("booking returns a reference number", appt["reference_number"] > 1423383)
check("status is Book", appt["status"] == "Book")
check("slot disappears after booking", first not in pms.get_slots(DOCTOR, DAY, VISIT)["slots"])
check("same slot refused for another patient", raises("SLOT_TAKEN", pms.create_appointment, tb, DOCTOR, VISIT, DAY, first))
other_doc = next(d["doctor_id"] for d in pms.list_doctors()
                 if d["doctor_id"] != DOCTOR and first in pms.get_slots(d["doctor_id"], DAY, VISIT)["slots"])
check("patient cannot double-book themselves", raises("PATIENT_CONFLICT", pms.create_appointment, ta, other_doc, VISIT, DAY, first))
check("booking appears in patient's list", any(a["reference_number"] == appt["reference_number"]
                                               for a in pms.get_patient_appointments(ta)))

print("\n== Booking rules")
check("past time refused", raises("TOO_SOON", pms.create_appointment, ta, DOCTOR, VISIT, "2026-10-26", "07:00"))
check("too far ahead refused", raises("TOO_FAR", pms.create_appointment, ta, DOCTOR, VISIT, "2027-06-01", "10:00"))
check("doctor day off refused", raises("DOCTOR_NOT_WORKING", pms.create_appointment, ta, DOCTOR, VISIT, "2026-10-30", "10:00"))
check("internal visit type refused", raises("VISIT_TYPE_NOT_BOOKABLE", pms.create_appointment, ta, DOCTOR, 1136, DAY, "12:00"))
check("assistant (id 53) refused", raises("DOCTOR_NOT_BOOKABLE", pms.create_appointment, ta, 53, VISIT, DAY, "12:00"))
check("bad time format refused", raises("BAD_TIME", pms.create_appointment, ta, DOCTOR, VISIT, DAY, "25:99"))

print("\n== Privacy")
check("other patient cannot cancel my appointment",
      raises("APPOINTMENT_NOT_FOUND", pms.cancel_appointment, tb, appt["appointment_id"]))
check("other patient cannot see it", all(a["reference_number"] != appt["reference_number"]
                                         for a in pms.get_patient_appointments(tb)))

print("\n== Confirm / reschedule / cancel")
check("confirm works", pms.confirm_appointment(ta, appt["appointment_id"])["status"] == "Confirm")
new_time = slots[4]
moved = pms.reschedule_appointment(ta, appt["appointment_id"], DAY, new_time)
check("reschedule keeps reference number", moved["reference_number"] == appt["reference_number"])
check("reschedule moves the time", moved["time"] == new_time and moved["status"] == "Rescheduled")
check("old slot is free again", first in pms.get_slots(DOCTOR, DAY, VISIT)["slots"])
check("new slot is taken", new_time not in pms.get_slots(DOCTOR, DAY, VISIT)["slots"])
check("same-slot reschedule refused", raises("SAME_SLOT", pms.reschedule_appointment, ta, appt["appointment_id"], DAY, new_time))

os.environ["DEMO_NOW"] = "2026-10-27T20:00"       # less than 24h before the appointment
check("old token expires after 15 min", raises("NOT_VERIFIED", pms.cancel_appointment, ta, appt["appointment_id"]))
late = pms.verify_patient(pa[0], spoken(pa[1]))["token"]   # caller verifies again
check("cancel inside notice window refused", raises("TOO_LATE_TO_CHANGE", pms.cancel_appointment, late, appt["appointment_id"]))
os.environ["DEMO_NOW"] = "2026-10-26T08:00"
ta = pms.verify_patient(pa[0], spoken(pa[1]))["token"]
cancelled = pms.cancel_appointment(ta, appt["appointment_id"])
check("cancel works", cancelled["status"] == "Cancel")
check("slot returns after cancel", new_time in pms.get_slots(DOCTOR, DAY, VISIT)["slots"])
check("cancelled appointment not in upcoming list", all(a["reference_number"] != appt["reference_number"]
                                                        for a in pms.get_patient_appointments(ta)))
check("cancelling twice refused", raises("NOT_CHANGEABLE", pms.cancel_appointment, ta, appt["appointment_id"]))

print("\n== Search")
nxt = pms.get_next_available(VISIT, unit_id=4, limit=4)
check("next available returns up to 4, sorted", 0 < len(nxt) <= 4 and nxt == sorted(nxt, key=lambda x: (x["date"], x["time"])))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
