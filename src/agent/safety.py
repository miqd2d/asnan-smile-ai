"""
safety.py - Rules that run BEFORE the model, in plain code.

A 3B model must never be the only thing standing between a caller and help in an
emergency, or between a complaint and a human. These are crude on purpose:
they err on the side of transferring.
"""
import re

from . import ai_config

_EMERGENCY = [
    r"can.?t breathe|cannot breathe|trouble breathing|difficulty breathing|short of breath|hard to breathe",
    r"(swollen|swelling|swelled).{0,30}(face|neck|throat|jaw|eye)|(face|neck|throat|jaw|eye).{0,30}(swollen|swelling)",
    r"bleeding.{0,30}(won.?t stop|can.?t stop|not stopping|heavy|a lot|uncontrol)|(won.?t stop|can.?t stop).{0,20}bleeding",
    r"knocked out|knocked.{0,10}tooth|broken jaw|car accident|accident|unconscious|passed out|fainted|chest pain|seizure|allergic reaction",
    r"لا أستطيع التنفس|لا استطيع التنفس|ما اقدر اتنفس|ما أقدر أتنفس|صعوبة في التنفس|ضيق في التنفس",
    r"تورم (في )?(الوجه|الرقبة|الفك|العين|الحلق)|وجهي منتفخ|الوجه منتفخ|انتفاخ في الوجه",
    r"نزيف.{0,20}(لا يتوقف|ما يوقف|شديد|كثير)|الدم (ما|لا) (يوقف|يتوقف)",
    r"حادث|حادثة|فاقد الوعي|أغمي|اغمي|ألم في الصدر|الم في الصدر",
]
_COMPLAINT = [r"complain|complaint|unhappy|furious|refund|lawyer|\bsue\b", r"شكوى|اشتكي|أشتكي|محامي"]
_HUMAN = [r"\b(human|real person|live person|representative|operator|manager|supervisor|agent|someone else)\b",
          r"موظف|مدير|مسؤول|أكلم أحد|اكلم احد|شخص حقيقي|خدمة العملاء"]
_ASKING_IF_BOT = r"are you (a |an )?(human|real|robot|bot|ai|person|machine)"

REPLIES = {
    "emergency": {
        "en": f"This sounds urgent. Please call emergency services on {ai_config.EMERGENCY_NUMBER} now, "
              "or go to the nearest emergency room. I am alerting our team right away.",
        "ar": f"هذه حالة عاجلة. يرجى الاتصال بالطوارئ على {ai_config.EMERGENCY_NUMBER} الآن أو التوجه إلى أقرب "
              "قسم طوارئ. وسأبلغ فريقنا فورًا."},
    "transfer": {
        "en": "Of course. I am transferring you to a team member now.",
        "ar": "بالتأكيد، سأحوّلك الآن إلى أحد أعضاء الفريق."},
}


def is_arabic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum("\u0600" <= c <= "\u06ff" for c in letters) > len(letters) / 2


def reply_for(kind: str, text: str) -> str:
    return REPLIES["emergency" if kind == "emergency" else "transfer"]["ar" if is_arabic(text) else "en"]


def check(text: str) -> tuple[str, str] | None:
    """Returns (kind, reason) - kind is 'emergency' or 'transfer' - or None."""
    t = (text or "").lower()
    if any(re.search(p, t) for p in _EMERGENCY):
        return "emergency", "emergency"
    if any(re.search(p, t) for p in _COMPLAINT):
        return "transfer", "complaint"
    if re.search(_ASKING_IF_BOT, t):
        return None                       # "are you a human?" is a question for the model, not a transfer
    if any(re.search(p, t) for p in _HUMAN):
        return "transfer", "requested_human"
    return None
