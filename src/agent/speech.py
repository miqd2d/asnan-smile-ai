"""
speech.py - Everything the caller HEARS from the system, written by code from real data, in Arabic or English.
Times, doctors, reference numbers and results can therefore never be invented or mis-stated.
"""
from . import ai_config

EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
             "October", "November", "December"]
AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر",
             "أكتوبر", "نوفمبر", "ديسمبر"]
AR_DAYS = {"Monday": "الاثنين", "Tuesday": "الثلاثاء", "Wednesday": "الأربعاء", "Thursday": "الخميس",
           "Friday": "الجمعة", "Saturday": "السبت", "Sunday": "الأحد"}


def t12(hhmm: str, lang: str) -> str:
    h, m = map(int, hhmm.split(":"))
    suffix = ("PM" if h >= 12 else "AM") if lang == "en" else ("م" if h >= 12 else "ص")
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def day_str(weekday: str, iso: str, lang: str) -> str:
    _, m, d = map(int, iso.split("-"))
    if lang == "en":
        return f"{weekday} {d} {EN_MONTHS[m - 1]}"
    return f"{AR_DAYS.get(weekday, weekday)} {d} {AR_MONTHS[m - 1]}"


def _at(o: dict, lang: str) -> str:
    return f"{day_str(o['weekday'], o['date'], lang)} {'at' if lang == 'en' else 'الساعة'} {t12(o['time'], lang)}"


# ---------------------------------------------------------------- availability and appointments
def options_say(options: list, lang: str, header: str | None = None) -> str:
    w = "with" if lang == "en" else "مع"
    items = "; ".join(f"{o['n']}) {_at(o, lang)} {w} {o['doctor']}" for o in options)
    if lang == "en":
        return f"{header + ' ' if header else 'I have these times: '}{items}. Which one would you like?"
    return f"{header + ' ' if header else 'عندي هذه المواعيد: '}{items}. أيّها تفضّل؟"


def none_that_day(options: list, day: str, lang: str) -> str:
    if lang == "en":
        return options_say(options, lang, f"I do not have free times on {day}. The nearest are: ")
    return options_say(options, lang, f"لا توجد مواعيد متاحة يوم {day}. أقرب المواعيد: ")


def nothing_free(lang: str) -> str:
    return ("I could not find any free time in the next two weeks for that. I can transfer you to a team member."
            if lang == "en" else "لم أجد أي موعد متاح خلال الأسبوعين القادمين. يمكنني تحويلك إلى أحد الموظفين.")


def ask_which_doctor(names: list, lang: str) -> str:
    j = ", ".join(names[:5])
    return f"Which doctor do you mean: {j}?" if lang == "en" else f"أي طبيب تقصد: {j}؟"


def no_such_doctor(lang: str) -> str:
    return ("I could not find a doctor with that name. Would you like any available doctor, or a specialty?"
            if lang == "en" else "لم أجد طبيبًا بهذا الاسم. هل تفضّل أي طبيب متاح أو تخصصًا معينًا؟")


def appointments_say(appts: list, lang: str) -> str:
    if not appts:
        return ("You have no upcoming appointments. Would you like to book one?"
                if lang == "en" else "ليس لديك مواعيد قادمة. هل تريد حجز موعد؟")
    w = "with" if lang == "en" else "مع"
    ref = "reference" if lang == "en" else "رقم المرجع"
    items = "; ".join(f"{a['n']}) {a['visit_type']} {w} {a['doctor']} {_at(a, lang)} ({ref} {a['reference_number']})"
                      for a in appts)
    if lang == "en":
        n = len(appts)
        return f"You have {n} upcoming appointment{'s' if n > 1 else ''}: {items}. Which one would you like to change?"
    return f"لديك {len(appts)} موعد قادم: {items}. أي موعد تريد تغييره؟"


# ---------------------------------------------------------------- read-back, results
def readback(p: dict, lang: str) -> str:
    if p["type"] == "book":
        a = p["option"]
        return (f"Just to confirm: {p['visit_type']} with {a['doctor']} on {_at(a, lang)}. Shall I book it?"
                if lang == "en" else f"للتأكيد: {p['visit_type']} مع {a['doctor']} يوم {_at(a, lang)}. هل أحجزه؟")
    if p["type"] == "reschedule":
        o, n = p["old"], p["option"]
        return (f"Just to confirm: move your appointment {o['reference_number']} from {_at(o, lang)} to "
                f"{_at(n, lang)} with {n['doctor']}. Shall I do that?" if lang == "en" else
                f"للتأكيد: نقل موعدك رقم {o['reference_number']} من {_at(o, lang)} إلى {_at(n, lang)} مع "
                f"{n['doctor']}. هل أنفّذ ذلك؟")
    o = p["old"]
    return (f"Just to confirm: cancel your appointment {o['reference_number']}, {o['visit_type']} with "
            f"{o['doctor']} on {_at(o, lang)}. Shall I cancel it?" if lang == "en" else
            f"للتأكيد: إلغاء موعدك رقم {o['reference_number']}، {o['visit_type']} مع {o['doctor']} "
            f"يوم {_at(o, lang)}. هل ألغيه؟")


def receipt(e: dict, lang: str) -> str:
    a = e["appt"]
    when = _at(a, lang)
    if lang == "en":
        return {"BOOKED": f"Your appointment is booked: {a['visit_type']} with {a['doctor']} on {when}. "
                          f"Your reference number is {a['reference_number']}.",
                "RESCHEDULED": f"Your appointment {a['reference_number']} has been moved to {when} with {a['doctor']}.",
                "CANCELLED": f"Your appointment {a['reference_number']} on {when} has been cancelled."}[e["type"]]
    return {"BOOKED": f"تم حجز موعدك: {a['visit_type']} مع {a['doctor']} يوم {when}. رقم المرجع {a['reference_number']}.",
            "RESCHEDULED": f"تم نقل موعدك رقم {a['reference_number']} إلى {when} مع {a['doctor']}.",
            "CANCELLED": f"تم إلغاء موعدك رقم {a['reference_number']} يوم {when}."}[e["type"]]


ANYTHING_ELSE = {"en": " Is there anything else I can help you with?",
                 "ar": " هل هناك أي شيء آخر يمكنني مساعدتك به؟"}


def declined(lang: str) -> str:
    return ("No problem, I have not changed anything. Is there anything else I can help you with?"
            if lang == "en" else "لا مشكلة، لم أغيّر شيئًا. هل هناك أي شيء آخر؟")


REPLIES_TRANSFER = {"en": "Of course. I am transferring you to a team member now.",
                    "ar": "بالتأكيد، سأحوّلك الآن إلى أحد أعضاء الفريق."}


def goodbye(lang: str) -> str:
    return (f"Thank you for calling {ai_config.CLINIC_NAME} Dental Clinic. Goodbye!"
            if lang == "en" else f"شكرًا لاتصالكم بعيادة {ai_config.CLINIC_NAME}. مع السلامة!")


def thanks_verified(first: str, lang: str) -> str:
    return (f"Thank you, {first}. How can I help you?" if lang == "en" else f"شكرًا {first}. كيف يمكنني مساعدتك؟")


# ---------------------------------------------------------------- identity
def ask_identity(kind: str, lang: str) -> str:
    en = {"both": "To continue I need to verify you. Please tell me your patient file number and the phone number on the file.",
          "file": "Thank you. What is your patient file number?",
          "phone_or_name": "Thank you. And what is the phone number on the file, or your name?",
          "retry": "I could not verify those details. Please tell me your patient file number and phone number again."}
    ar = {"both": "للمتابعة أحتاج إلى التحقق من هويتك. من فضلك أخبرني برقم ملفك ورقم الهاتف المسجل.",
          "file": "شكرًا. ما هو رقم ملفك؟",
          "phone_or_name": "شكرًا. وما هو رقم الهاتف المسجل في الملف، أو اسمك؟",
          "retry": "لم أتمكن من التحقق من هذه البيانات. من فضلك أخبرني برقم ملفك ورقم هاتفك مرة أخرى."}
    return (en if lang == "en" else ar)[kind]


# ---------------------------------------------------------------- rule errors in the caller's language
ERRORS_AR = {
    "SLOT_TAKEN": "عذرًا، هذا الموعد لم يعد متاحًا. هل أبحث لك عن موعد آخر؟",
    "TOO_LATE_TO_CHANGE": "التغييرات تتطلب إشعارًا قبل 24 ساعة على الأقل. يمكنني تحويلك إلى أحد الموظفين.",
    "NOT_CHANGEABLE": "لا يمكن تغيير هذا الموعد.",
    "PATIENT_CONFLICT": "لديك موعد آخر في نفس الوقت.",
    "DOCTOR_NOT_WORKING": "الطبيب لا يعمل في ذلك اليوم.",
    "TOO_SOON": "هذا الوقت قريب جدًا أو قد مضى. من فضلك اختر وقتًا لاحقًا.",
    "SAME_SLOT": "هذا هو موعدك الحالي بالفعل.",
    "APPOINTMENT_NOT_FOUND": "لم أجد هذا الموعد في ملفك."}


def error_text(code: str, message: str, lang: str) -> str:
    return ERRORS_AR.get(code, message) if lang == "ar" else message
