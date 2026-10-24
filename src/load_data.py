"""
load_data.py - Build db/clinic.db from the 3 Excel exports.

Run from the project root:   python src/load_data.py
Re-running rebuilds the database from scratch (safe to repeat).
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = ROOT / "db" / "clinic.db"
REPORT_PATH = ROOT / "data_quality_report.md"

report = []  # lines for the data-quality report


def note(line: str):
    print(line)
    report.append(line)


def clean_text(s):
    """Trim and collapse repeated spaces. Keeps None as None."""
    if pd.isna(s):
        return None
    return re.sub(r"\s+", " ", str(s)).strip()


def hhmm(t):
    """datetime.time -> 'HH:MM' text (SQLite has no TIME type)."""
    return t.strftime("%H:%M")


# ---------------------------------------------------------------- 1. READ
sched_raw = pd.read_excel(DATA / "Doctor_Sche.xlsx")
appt_raw = pd.read_excel(DATA / "Appointments-200.xlsx")
rov_raw = pd.read_excel(DATA / "Rov_List.xlsx")
note(f"# Data quality report\n\nRaw rows: schedule={len(sched_raw)}, "
     f"appointments={len(appt_raw)}, visit types={len(rov_raw)}\n")

# ---------------------------------------------------------------- 2. UNITS + DOCTORS
units = (sched_raw[["OPERATIONUNIT_ID", "OPERATIONUNIT_NAME"]]
         .drop_duplicates()
         .rename(columns={"OPERATIONUNIT_ID": "unit_id", "OPERATIONUNIT_NAME": "name"}))
units["name"] = units["name"].map(clean_text)

doctors = (sched_raw[["DoctorID", "TEAM_NAME", "OPERATIONUNIT_ID"]]
           .drop_duplicates()
           .rename(columns={"DoctorID": "doctor_id", "TEAM_NAME": "name",
                            "OPERATIONUNIT_ID": "unit_id"}))
doctors["name"] = doctors["name"].map(clean_text)

# Doctors that appear in appointments but not in the schedule (e.g. TEAM_ID 53)
missing = (appt_raw[~appt_raw.TEAM_ID.isin(doctors.doctor_id)]
           [["TEAM_ID", "TEAM_NAME", "OPERATIONUNIT_ID"]].drop_duplicates()
           .rename(columns={"TEAM_ID": "doctor_id", "TEAM_NAME": "name",
                            "OPERATIONUNIT_ID": "unit_id"}))
missing["name"] = missing["name"].map(clean_text)
doctors = pd.concat([doctors, missing], ignore_index=True)
note(f"- Doctors found in appointments but missing from the schedule: "
     f"{missing['name'].tolist()}")

# Patients should only be offered real dentists/hygienists, not assistants or equipment
NOT_BOOKABLE_UNITS = {18}                 # Doctor's Asst
NOT_BOOKABLE_NAMES = ("asst dr", "cbct", "home bleaching")
doctors["is_bookable"] = (
    ~doctors.unit_id.isin(NOT_BOOKABLE_UNITS)
    & ~doctors.name.str.lower().str.contains("|".join(NOT_BOOKABLE_NAMES))
).astype(int)
note(f"- Staff marked NOT bookable (assistants/equipment): "
     f"{int((doctors.is_bookable == 0).sum())} of {len(doctors)}")

# ---------------------------------------------------------------- 3. SCHEDULES
schedules = pd.DataFrame({
    "doctor_id": sched_raw.DoctorID,
    "work_date": sched_raw.Date.dt.strftime("%Y-%m-%d"),
    "start_time": sched_raw.StartTime.map(hhmm),
    "end_time": sched_raw.EndTime.map(hhmm),
})
note(f"- Schedule rows: {len(schedules)} "
     f"({schedules.work_date.min()} to {schedules.work_date.max()})")

# ---------------------------------------------------------------- 4. VISIT TYPES
vt = pd.DataFrame({
    "rov_id": rov_raw.ROV_ID,
    "name": rov_raw.DESCRIPTION.map(clean_text),
    "duration_min": rov_raw.DURATION,
    "active": rov_raw.ACTIVE,
})
vt["patient_bookable"] = 0   # YOU curate this list by hand later (about 15 types)
dups = int(vt.name.str.lower().duplicated().sum())
note(f"- Visit types: {len(vt)} total, {int((vt.active == 0).sum())} inactive, "
     f"{dups} duplicate names (after trimming spaces)")

# ---------------------------------------------------------------- 5. STATUSES
status_ref = (appt_raw[["STATUS_ID", "STATUS_NAME", "ACTIVE"]].drop_duplicates()
              .rename(columns={"STATUS_ID": "status_id", "STATUS_NAME": "name",
                               "ACTIVE": "active_flag"}))
# ASSUMPTION (confirm with the clinic): a slot is occupied by live statuses,
# except 'Broken' (failed appointment).
status_ref["occupies_slot"] = ((status_ref.active_flag == 1)
                               & (status_ref.name != "Broken")).astype(int)

# ---------------------------------------------------------------- 6. APPOINTMENTS
a = appt_raw.copy()
a["patient_name_clean"] = a.PATIENT_NAME.map(clean_text)
a["age_years"] = a.patient_name_clean.str.extract(r"\((\d+)Y")[0].astype(float)
a["patient_name_clean"] = (a.patient_name_clean
                           .str.replace(r"\s*\(\d+Y-\d+M\)", "", regex=True)
                           .str.strip())
a["is_block"] = (a.DESCRIPTION.str.strip().str.lower() == "block").astype(int)

# keep every raw row as history
history = pd.DataFrame({
    "appointment_id": a.PAT_APPOINTMENT_ID, "patient_id": a.PATIENT_ID,
    "doctor_id": a.TEAM_ID, "rov_id": a.ROV_ID, "status_id": a.STATUS_ID,
    "status_name": a.STATUS_NAME, "active_flag": a.ACTIVE,
    "start_datetime": a.APPOINTMENT_DATE.dt.strftime("%Y-%m-%d %H:%M"),
    "original_start": a.START_DATE.dt.strftime("%Y-%m-%d %H:%M"),
})

# one row per appointment: prefer a live (ACTIVE=1) record, else the first one
a = a.sort_values(["PAT_APPOINTMENT_ID", "ACTIVE"], kind="stable")
dup_count = int(a.PAT_APPOINTMENT_ID.duplicated().sum())
a = a.drop_duplicates("PAT_APPOINTMENT_ID", keep="first")
note(f"- Duplicate appointment IDs collapsed: {dup_count} "
     f"(full history kept in appointment_history)")

appointments = pd.DataFrame({
    "appointment_id": a.PAT_APPOINTMENT_ID,
    "patient_id": a.PATIENT_ID,
    "doctor_id": a.TEAM_ID,
    "unit_id": a.OPERATIONUNIT_ID,
    "location_id": a.LOCATION_ID,
    "rov_id": a.ROV_ID,
    "start_datetime": a.APPOINTMENT_DATE.dt.strftime("%Y-%m-%d %H:%M"),
    "duration_min": a.MINUTE,
    "status_id": a.STATUS_ID,
    "status_name": a.STATUS_NAME,
    "active_flag": a.ACTIVE,
    "is_block": a.is_block,
    "source": "excel",
})
note(f"- Block (time-holder) rows: {int(appointments.is_block.sum())}")

# ---------------------------------------------------------------- 7. PATIENTS
p = a[(a.PATIENT_ID.notna()) & (a.is_block == 0)].drop_duplicates("PATIENT_ID")
patients = pd.DataFrame({
    "patient_id": p.PATIENT_ID.astype(int),
    "reg_id": p.REC_PAT_REG_ID,
    "name": p.patient_name_clean,
    "age_years": p.age_years,
})
# The source has NO phone numbers (100% empty), so we generate obviously fake ones
patients["phone"] = ["+9655000" + f"{i:04d}" for i in range(len(patients))]
note(f"- Patients: {len(patients)}. Source phone columns were 100% empty, "
     f"so DUMMY phones were generated (never real numbers).")
# drop appointments whose patient is a block/unregistered row (keep blocks)
# Block rows hold a dummy patient record in the source; they are not patients
appointments["patient_id"] = appointments.patient_id.astype("Int64")
appointments.loc[appointments.is_block == 1, "patient_id"] = pd.NA

# ---------------------------------------------------------------- 8. INTEGRITY CHECKS
live = appointments[(appointments.active_flag == 1) & (appointments.is_block == 0)]
sched_keys = set(zip(schedules.doctor_id, schedules.work_date))
no_sched = [(d, s[:10]) for d, s in zip(live.doctor_id, live.start_datetime)
            if (d, s[:10]) not in sched_keys]
note(f"- Live appointments with NO matching schedule day: {len(no_sched)}")
orphans = appointments[appointments.patient_id.notna()
                       & ~appointments.patient_id.isin(patients.patient_id)]
note(f"- Appointments whose patient is missing from patients: {len(orphans)}")

# ---------------------------------------------------------------- 9. WRITE DB
DB_PATH.parent.mkdir(exist_ok=True)
if DB_PATH.exists():
    DB_PATH.unlink()
con = sqlite3.connect(DB_PATH)
con.executescript("""
PRAGMA foreign_keys = ON;
CREATE TABLE units          (unit_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE doctors        (doctor_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                             unit_id INTEGER REFERENCES units(unit_id),
                             is_bookable INTEGER NOT NULL DEFAULT 1);
CREATE TABLE schedules      (doctor_id INTEGER REFERENCES doctors(doctor_id),
                             work_date TEXT NOT NULL, start_time TEXT NOT NULL,
                             end_time TEXT NOT NULL,
                             PRIMARY KEY (doctor_id, work_date));
CREATE TABLE visit_types    (rov_id INTEGER PRIMARY KEY, name TEXT, duration_min INTEGER,
                             active INTEGER, patient_bookable INTEGER DEFAULT 0);
CREATE TABLE statuses       (status_id INTEGER PRIMARY KEY, name TEXT, active_flag INTEGER,
                             occupies_slot INTEGER);
CREATE TABLE patients       (patient_id INTEGER PRIMARY KEY, reg_id INTEGER, name TEXT,
                             age_years REAL, phone TEXT);
CREATE TABLE appointments   (appointment_id INTEGER PRIMARY KEY,
                             patient_id INTEGER REFERENCES patients(patient_id),
                             doctor_id INTEGER REFERENCES doctors(doctor_id),
                             unit_id INTEGER, location_id INTEGER, rov_id INTEGER,
                             start_datetime TEXT NOT NULL, duration_min INTEGER NOT NULL,
                             status_id INTEGER, status_name TEXT, active_flag INTEGER,
                             is_block INTEGER DEFAULT 0, source TEXT);
CREATE TABLE appointment_history (appointment_id INTEGER, patient_id INTEGER,
                             doctor_id INTEGER, rov_id INTEGER, status_id INTEGER,
                             status_name TEXT, active_flag INTEGER,
                             start_datetime TEXT, original_start TEXT);
CREATE INDEX idx_appt_doc_time ON appointments(doctor_id, start_datetime);
CREATE INDEX idx_appt_patient  ON appointments(patient_id);
""")
units.to_sql("units", con, if_exists="append", index=False)
doctors.to_sql("doctors", con, if_exists="append", index=False)
schedules.to_sql("schedules", con, if_exists="append", index=False)
vt.to_sql("visit_types", con, if_exists="append", index=False)
status_ref.to_sql("statuses", con, if_exists="append", index=False)
patients.to_sql("patients", con, if_exists="append", index=False)
appointments.to_sql("appointments", con, if_exists="append", index=False)
history.to_sql("appointment_history", con, if_exists="append", index=False)
con.commit()

print("\nTable row counts:")
for t in ["units", "doctors", "schedules", "visit_types", "statuses",
          "patients", "appointments", "appointment_history"]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"  {t:22s} {n}")
    report.append(f"- table `{t}`: {n} rows")
con.close()

REPORT_PATH.write_text("\n".join(report), encoding="utf-8")
print(f"\nDatabase written to {DB_PATH}\nReport written to {REPORT_PATH}")
