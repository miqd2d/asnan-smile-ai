"""prompts.py - A SHORT system prompt (small models follow short prompts) plus a live CALL STATE block."""
from . import ai_config, speech
import pms
from .dates import weekday_name

GREETING = (f"Welcome to {ai_config.CLINIC_NAME} Dental Clinic. How can I help you today?\n"
            f"مرحبًا بكم في عيادة {ai_config.CLINIC_NAME} لطب الأسنان. كيف يمكنني مساعدتكم؟")

# what callers say -> which visit type (ids are the real rov_ids from your visit_types table)
VISIT_HINTS = {
    39: "new patient, first visit, consultation, check my teeth, استشارة, مريض جديد",
    5: "consultation, see the doctor, استشارة",
    50: "second opinion, re-consultation, come back to discuss",
    1055: "pain, toothache, emergency, swelling gum, ألم, وجع, طوارئ",
    1242: "broken bracket or wire (braces), تقويم",
    1059: "scaling, tartar, تقليح",
    48: "cleaning, polishing, تنظيف",
    1074: "check-up, routine check, كشف",
    2: "6-month recall",
    20: "filling, cavity, حشوة, تسوس",
    1147: "root canal, nerve, عصب",
    49: "extraction, remove a tooth, خلع",
    1099: "whitening, bleaching, تبييض",
    51: "follow-up after treatment, متابعة",
    1108: "fluoride, kids, children, فلورايد, أطفال"}


def _state_block(s) -> str:
    c = s.ctx
    who = f"identified (first name {s.first_name})" if s.verified else "not identified yet (the system collects this when needed)"
    visit = f"{c['visit_type']} (id {c['visit_type_id']})" if c.get("visit_type_id") else "not chosen"
    doctor = c.get("doctor") or ("any doctor" if c.get("visit_type_id") else "not chosen")
    lines = [f"- Caller: {who}",
             f"- Visit type: {visit}",
             f"- Doctor: {doctor}",
             f"- Day last asked about: {c.get('last_day') or 'none'}"]
    if s.options:
        lines.append("- Times offered (the caller may pick by number): " + " | ".join(
            f"{o['n']}) {o['weekday']} {o['date']} {speech.t12(o['time'], 'en')} {o['doctor']}" for o in s.options))
    if s.appts:
        lines.append("- Caller's appointments: " + " | ".join(
            f"{a['n']}) {a['visit_type']} {a['weekday']} {a['date']} {speech.t12(a['time'], 'en')}" for a in s.appts))
    return "\n".join(lines)


def build_system_prompt(session, now) -> str:
    units = "; ".join(f"{u['unit_id']}={u['name']}" for u in pms.list_units())
    visits = "\n".join(f"{v['rov_id']} = {v['name']} ({VISIT_HINTS.get(v['rov_id'], v['name'].lower())})"
                       for v in pms.list_visit_types())
    today = now.strftime("%Y-%m-%d")
    return f"""You are the phone receptionist of {ai_config.CLINIC_NAME} Dental Clinic in Kuwait. Today is {weekday_name(today)} {today}.
Speak the caller's language (Arabic or English). Keep every reply to 1-2 short sentences. Ask one question at a time. No lists. If asked, say you are an AI assistant.

THE SYSTEM HANDLES (never do these yourself): verifying the caller, reading times and appointments aloud, asking "Shall I book it?", and announcing results. You only choose the right tool, or ask the caller for what is missing.

WHAT YOU NEED for a new booking: 1) the reason for the visit  2) a doctor name, a specialty, or "any"  3) which day, or "soonest". Ask only for what CALL STATE does not already show. As soon as you have the reason, call check_availability: do not ask anything extra.

WHICH TOOL:
- availability, times, or "I want to book" -> check_availability
- caller picks a time ("the first", "9 am", "number 2") -> book_appointment(option=N)
- see, cancel or change their appointment -> get_my_appointments, then cancel_appointment or reschedule_appointment
- prices, insurance, complaints, medical advice, a person, or anything else you cannot do -> transfer_to_agent
- goodbye -> end_call
Never say that something was booked, moved or cancelled. Never state a time, doctor or price yourself; only the tools know them. Never diagnose.

VISIT TYPES (id = name (what callers say)):
{visits}
SPECIALTIES (id=name): {units}

EXAMPLES:
Caller: I need a cleaning with Dr Tareq on Wednesday -> check_availability(visit_type_id=48, doctor_name="Tareq", date="wednesday")
Caller: my tooth hurts a lot -> check_availability(visit_type_id=1055)
Caller: the second one -> book_appointment(option=2)
Caller: I want to cancel my appointment -> get_my_appointments()
Caller: cancel the first one -> cancel_appointment(appointment=1)
Caller: I need a filling -> ask: "Do you prefer a certain doctor, and which day?"

CALL STATE (trust it; never ask again for what is already here):
{_state_block(session)}"""
