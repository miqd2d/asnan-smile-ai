"""
nlu.py - Understanding done in plain code, where code is more reliable than a small model:
yes/no answers, and pulling a file number / phone / name out of what the caller said.
"""
import re

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

YES_WORDS = {"yes", "yeah", "yep", "yup", "ok", "okay", "sure", "correct", "confirm", "confirmed", "right",
             "fine", "perfect", "agreed", "please", "نعم", "ايوه", "أيوه", "ايوا", "أيوا", "اي", "إي", "ايه",
             "أكيد", "اكيد", "تمام", "موافق", "طيب", "زين", "ماشي", "صحيح", "اوكي", "أوكي", "تأكيد", "اكد", "أكد"}
YES_PHRASES = ("go ahead", "do it", "book it", "that's right", "thats right", "sounds good", "of course")
NO_WORDS = {"no", "nope", "nah", "not", "don't", "dont", "stop", "wait", "لا", "لأ", "كلا", "بلاش", "وقف", "انتظر"}
NO_PHRASES = ("never mind", "nevermind", "forget it", "خلاص لا", "لا تحجز", "لا تلغي")
CHANGE_WORDS = {"but", "instead", "rather", "actually", "change", "different", "another", "other",
                "لكن", "بس", "غير", "ثاني", "آخر"}
_FILLER = {"my", "is", "its", "it's", "the", "and", "name", "file", "number", "phone", "mobile", "id",
           "patient", "please", "hi", "hello", "yes", "ok", "okay", "thanks", "thank", "you", "am", "me",
           "registered", "on", "with", "for", "of", "here", "sure", "yeah", "mine", "cell", "contact",
           "اسمي", "رقم", "رقمي", "ملف", "ملفي", "الملف", "الهاتف", "هاتفي", "جوالي", "جوال", "موبايل",
           "المريض", "الاسم", "هو", "مع", "نعم", "ايوه", "شكرا", "شكراً"}


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", (text or "").lower().translate(_AR_DIGITS))


def classify_reply(text: str) -> str:
    """Caller's answer to 'Shall I book it?': 'yes' | 'no' | 'other' (anything else = a new request)."""
    t = (text or "").lower().translate(_AR_DIGITS)
    w = words(t)
    if not w:
        return "other"
    if any(x in NO_WORDS for x in w) or any(p in t for p in NO_PHRASES):
        return "no"
    if len(w) <= 8 and not re.search(r"\d", t) and not any(x in CHANGE_WORDS for x in w):
        if any(x in YES_WORDS for x in w) or any(p in t for p in YES_PHRASES):
            return "yes"
    return "other"


def wants_to_drop(text: str) -> bool:
    t = (text or "").lower()
    return any(p in t for p in NO_PHRASES) or any(x in NO_WORDS for x in words(t))


def extract_identity(text: str) -> dict:
    """{'patient_id': '1188', 'phone': '99887766', 'name': 'abdullah'} - only what is really in the text."""
    t = (text or "").translate(_AR_DIGITS)
    t = re.sub(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2}:\d{2}", " ", t)   # dates, times
    out: dict = {}
    # digits separated only by a single space or dash belong together: "9965 4321", "1188 99887766"
    for g in re.findall(r"\d+(?:[ \-]\d+)*", t):
        d = re.sub(r"\D", "", g)
        if "phone" not in out and (len(d) == 8 or (len(d) == 11 and d.startswith("965"))
                                   or (len(d) == 13 and d.startswith("00965"))):
            out["phone"] = d[-8:]
        elif "phone" not in out and len(d) > 8:
            out["phone"], rest = d[-8:], d[:-8]
            if rest.lstrip("0") not in ("", "965") and 3 <= len(rest) <= 7 and "patient_id" not in out:
                out["patient_id"] = rest
        elif "patient_id" not in out and 3 <= len(d) <= 7:
            out["patient_id"] = d
    words_ = [w for w in re.findall(r"[^\W\d_]{2,}", text or "")
              if w.lower() not in _FILLER and not (w.startswith("و") and len(w) > 3 and w[1:] in _FILLER)]
    if words_ and "?" not in (text or "") and len(words_) <= 4:       # a question or a long sentence is not a name
        out["name"] = " ".join(words_)
    return out
