"""
dates.py - Turn caller words into exact dates and times, in code.
Small models are bad at "next Sunday"; code is not.
"""
import re
from datetime import date, datetime, timedelta

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
             "saturday": 5, "sunday": 6,
             "الاثنين": 0, "الإثنين": 0, "الثلاثاء": 1, "الأربعاء": 2, "الاربعاء": 2,
             "الخميس": 3, "الجمعة": 4, "السبت": 5, "الأحد": 6, "الاحد": 6}
_TODAY = {"today", "اليوم"}
_TOMORROW = {"tomorrow", "غدا", "غدًا", "بكرة", "بكره"}
_DAY_AFTER = {"بعد بكرة", "بعد بكره", "بعد غد", "day after tomorrow"}


def resolve_date(text: str, today: date) -> str | None:
    """'2026-11-03' | 'today' | 'tomorrow' | 'sunday' | 'next sunday' | 'الأربعاء' -> 'YYYY-MM-DD' or None."""
    t = (text or "").strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        try:
            return date.fromisoformat(t).isoformat()
        except ValueError:
            return None
    if t in _TODAY:
        return today.isoformat()
    if t in _DAY_AFTER:
        return (today + timedelta(days=2)).isoformat()
    if t in _TOMORROW:
        return (today + timedelta(days=1)).isoformat()
    for word in re.split(r"[\s,]+", t):
        if word in _WEEKDAYS:
            delta = (_WEEKDAYS[word] - today.weekday()) % 7 or 7   # next such day, never today
            return (today + timedelta(days=delta)).isoformat()
    return None


def normalize_time(text: str) -> str | None:
    """'9:00' | '09:00' | '2 pm' | '2:30 PM' | '14:30' | '٣ م' -> 'HH:MM' or None."""
    t = (text or "").strip().lower()
    t = t.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    m = re.fullmatch(r"(\d{1,2})(?::|\.)?(\d{2})?\s*(am|pm|a\.m\.|p\.m\.|ص|م)?", t)
    if not m:
        return None
    h, minute, mer = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if mer in ("pm", "p.m.", "م") and h < 12:
        h += 12
    if mer in ("am", "a.m.", "ص") and h == 12:
        h = 0
    if h > 23 or minute > 59:
        return None
    return f"{h:02d}:{minute:02d}"


def weekday_name(iso_date: str) -> str:
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%A")
