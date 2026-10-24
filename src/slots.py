"""
slots.py - The slot engine: "when can this doctor see this patient?"

Working window (schedules) minus occupied time (appointments), on a 15-minute
grid, keeping only start times where the WHOLE visit fits.
"""
from datetime import datetime, timedelta

from config import CAPACITY, STEP_MIN
from db import connect

FMT = "%Y-%m-%d %H:%M"


def get_available_slots(doctor_id: int, date: str, duration_min: int,
                        earliest: datetime | None = None,
                        exclude_appointment_id: int | None = None,
                        con=None) -> list[str]:
    """
    Free start times ('HH:MM') for one doctor on one date ('YYYY-MM-DD').

    earliest                - drop slots starting at or before this moment
    exclude_appointment_id  - ignore this appointment (used when rescheduling,
                              so an appointment does not block its own new time)
    """
    own = con is None
    con = con or connect()
    try:
        sched = con.execute(
            "SELECT start_time, end_time FROM schedules WHERE doctor_id=? AND work_date=?",
            (doctor_id, date)).fetchone()
        if not sched:
            return []                                   # doctor does not work that day
        day_start = datetime.strptime(f"{date} {sched['start_time']}", FMT)
        day_end = datetime.strptime(f"{date} {sched['end_time']}", FMT)

        rows = con.execute("""
            SELECT a.start_datetime, a.duration_min
            FROM appointments a JOIN statuses s ON s.status_id = a.status_id
            WHERE a.doctor_id = ? AND date(a.start_datetime) = ?
              AND s.occupies_slot = 1 AND a.appointment_id != ?
        """, (doctor_id, date, exclude_appointment_id or -1)).fetchall()
        busy = []
        for r in rows:
            s = datetime.strptime(r["start_datetime"], FMT)
            busy.append((s, s + timedelta(minutes=r["duration_min"])))

        slots, t = [], day_start
        while t + timedelta(minutes=duration_min) <= day_end:
            end = t + timedelta(minutes=duration_min)
            overlaps = sum(1 for (bs, be) in busy if bs < end and be > t)
            if overlaps < CAPACITY and (earliest is None or t > earliest):
                slots.append(t.strftime("%H:%M"))
            t += timedelta(minutes=STEP_MIN)
        return slots
    finally:
        if own:
            con.close()
