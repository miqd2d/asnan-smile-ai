"""
loop.py - The conversation loop. CODE runs the structured parts; the model is used only where it is good.

Per caller message, in this order:
  1. safety pre-check (emergency / complaint / human)            - code
  2. waiting for a yes/no on a read-back?   -> run or drop it     - code
  3. collecting file number + phone/name?   -> verify             - code
  4. otherwise ask the model to choose ONE tool or ask a question - model
After the turn the tool chatter is thrown away; only the caller's words and what they heard are remembered.
"""
import json
import logging
import re

import config
import pms
from rules import RuleError

from . import ai_config, calls, llm, nlu, prompts, safety, speech, summary, tools
from . import session as store
from .dates import normalize_time

log = logging.getLogger("uvicorn.error")

APOLOGY = {"en": "Sorry, I am having technical trouble. I am transferring you to a team member.",
           "ar": "عذرًا، لدي مشكلة تقنية. سأحوّلك إلى أحد أعضاء الفريق."}
STUCK = {"en": "I am sorry, I could not complete that. Let me transfer you to a team member.",
         "ar": "عذرًا، لم أتمكن من إكمال ذلك. سأحوّلك إلى أحد أعضاء الفريق."}
CLOSED = {"en": "This call has ended. Please call again if you need anything.",
          "ar": "انتهت المكالمة. يرجى الاتصال مرة أخرى إذا احتجتم لأي شيء."}
WAITING = {"en": "A team member will be with you shortly.", "ar": "سيكون أحد أعضاء الفريق معكم قريبًا."}
EMPTY = {"en": "Sorry, could you say that again?", "ar": "عذرًا، هل يمكنك إعادة ذلك؟"}
BLOCKED = {"en": "Sorry, I have not completed that yet. Could you tell me again what you would like to do?",
           "ar": "عذرًا، لم أُكمل ذلك بعد. هل يمكنك إخباري مرة أخرى بما تود فعله؟"}
BLOCKED_TIMES = {"en": "Let me check the exact available times for you. Which day would you like?",
                 "ar": "دعني أتحقق من المواعيد المتاحة بدقة. أي يوم تفضّل؟"}

# a success claim in the model's own words ("has been cancelled", "I've booked") - the system, not the model, announces results
_CLAIM = re.compile(
    r"\b(?:has|have)\s+(?:now\s+)?been\s+(?:successfully\s+)?(?:booked|cancel+ed|rescheduled)\b"
    r"|\bi(?:'ve|\s+have)\s+(?:now\s+|successfully\s+)*(?:booked|cancel+ed|rescheduled)\b"
    r"|\b(?:is|are)\s+now\s+(?:booked|cancel+ed|rescheduled)\b|\bsuccessfully\s+(?:booked|cancel+ed|rescheduled)\b"
    r"|تم\s+(?:حجز|إلغاء|الغاء|تغيير|تعديل)", re.I)
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)|\b(\d{1,2}):(\d{2})\b", re.I)


def _lang(text: str, fallback: str) -> str:
    if not any(c.isalpha() for c in text):
        return fallback                           # digits only ("1188"): keep the language of the call
    return "ar" if safety.is_arabic(text) else "en"


def _not_found():
    return RuleError("SESSION_NOT_FOUND", "This conversation was not found or has expired.", 404)


def _times_in(text: str) -> set[str]:
    out = set()
    for m in _TIME.finditer(text or ""):
        if m.group(1):
            t = normalize_time(f"{m.group(1)}:{m.group(2) or '00'} {m.group(3)}")
        else:
            t = normalize_time(f"{m.group(4)}:{m.group(5)}")
        if t:
            out.add(t)
    return out


# ------------------------------------------------------------------ lifecycle
def start_session() -> dict:
    expire_stale_sessions()
    s = store.create()
    s.transcript.append(("assistant", prompts.GREETING))
    s.messages.append({"role": "assistant", "content": prompts.GREETING})
    return {"session_id": s.id, "reply": prompts.GREETING}


def expire_stale_sessions() -> None:
    now = config.get_now()
    for s in store.all_sessions():
        idle_min = (now - s.last_active).total_seconds() / 60
        if not s.ended and idle_min > ai_config.SESSION_TTL_MIN:
            end_session(s.id, "timeout")
        elif s.ended and idle_min > 10:
            store.remove(s.id)


def end_session(session_id: str, reason: str = "user_ended") -> dict:
    s = store.get(session_id)
    if not s:
        raise _not_found()
    with s.lock:
        if s.call_log:
            return s.call_log
        info = summary.build(s, reason)
        now = config.get_now()
        record = {
            "session_id": s.id, "started_at": s.started.strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_sec": int((now - s.started).total_seconds()),
            "language": summary.language_of(s), "patient_id": s.patient_id,
            "outcome": info["outcome"], "summary": info["summary"], "follow_up": info["follow_up"],
            "appointment_refs": summary.refs_of(s), "transferred": int(s.transferred), "end_reason": reason}
        record["call_id"] = calls.save_call_log(**record)
        s.ended, s.call_log, s.last_active = True, record, now
        return record


# ------------------------------------------------------------------ step 2: yes / no on a read-back
def _handle_pending(s, text: str, lang: str) -> str | None:
    kind = nlu.classify_reply(text)
    if kind == "no":
        s.pending = None
        return speech.declined(lang)
    if kind == "other":
        s.pending = None                          # the caller moved on: treat it as a new request
        return None
    call = s.pending.get("call")
    try:
        event = tools.execute_pending(s)
    except RuleError as e:
        if e.code == "NOT_VERIFIED":
            tools.forget_identity(s)
            s.awaiting_identity, s.resume = True, call
            return _identity_step(s, None, lang)
        if e.code in ("SLOT_TAKEN", "DOCTOR_NOT_WORKING", "PATIENT_CONFLICT"):
            s.options = []
        return speech.error_text(e.code, e.message, lang)
    return speech.receipt(event, lang) + speech.ANYTHING_ELSE[lang]


# ------------------------------------------------------------------ step 3: identity, collected by code
def _identity_step(s, text: str | None, lang: str) -> str | None:
    if text is None:      # just asked to verify: use anything the caller already said earlier in the call
        for role, t in s.transcript[s.id_scan_from:]:
            if role == "user":
                f = nlu.extract_identity(t)
                for k in ("patient_id", "phone"):
                    if f.get(k):
                        s.id_fields[k] = f[k]
    else:
        f = nlu.extract_identity(text)
        if nlu.wants_to_drop(text) and not (f.get("patient_id") or f.get("phone")):
            s.awaiting_identity, s.resume, s.id_fields, s.id_asks = False, None, {}, 0
            return None                           # "never mind": back to the model
        for k in ("patient_id", "phone", "name"):
            if f.get(k):
                s.id_fields[k] = f[k]

    F = s.id_fields
    if F.get("patient_id") and (F.get("phone") or F.get("name")):
        try:
            r = pms.verify_patient(int(F["patient_id"]), F.get("name"), F.get("phone"))
        except RuleError as e:
            s.verify_failures += 1
            s.events.append({"type": "VERIFY_FAILED"})
            s.id_fields = {}
            if e.code == "LOCKED_OUT" or s.verify_failures >= 2:
                tools.do_transfer(s, "identity_check_failed")
                return speech.REPLIES_TRANSFER[lang]
            return speech.ask_identity("retry", lang)
        s.token, s.patient_id, s.first_name = r["token"], r["patient_id"], r["first_name"]
        s.events.append({"type": "VERIFIED"})
        s.awaiting_identity, s.id_fields, s.id_asks = False, {}, 0
        resume, s.resume = s.resume, None
        if resume:
            result = tools.run_tool(s, resume["tool"], resume["args"])
            if "say" in result:
                return result["say"]
        return speech.thanks_verified(r["first_name"], lang)

    s.id_asks += 1
    if s.id_asks > 4:                             # they cannot or will not identify themselves
        tools.do_transfer(s, "identity_details_missing")
        return speech.REPLIES_TRANSFER[lang]
    if not F.get("patient_id"):
        return speech.ask_identity("both" if not (F.get("phone") or F.get("name")) else "file", lang)
    return speech.ask_identity("phone_or_name", lang)


# ------------------------------------------------------------------ step 4: the model
def _trim(messages: list) -> list:
    m = messages[-ai_config.MAX_HISTORY_MESSAGES:]
    while m and m[0]["role"] != "user":
        m = m[1:]
    return m


def _assistant_msg(out: dict) -> dict:
    msg = {"role": "assistant", "content": out["content"]}
    if out["tool_calls"]:
        msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                             for c in out["tool_calls"]]
    return msg


def _finalize(s, text: str, lang: str, user_text: str) -> str:
    """Model-written words may not contradict the facts."""
    if _CLAIM.search(text):
        s.events.append({"type": "CLAIM_BLOCKED"})
        log.warning("Blocked a success claim in model text")
        return BLOCKED[lang]
    known = {o["time"] for o in s.options} | {a["time"] for a in s.appts} | _times_in(user_text)
    if not _times_in(text) <= known:              # the model named a time no tool gave it
        s.events.append({"type": "INVENTED_TIME_BLOCKED"})
        log.warning("Blocked an invented time in model text")
        return BLOCKED_TIMES[lang]
    return text


def _run_turn(s, lang: str, user_text: str) -> str:
    for _ in range(ai_config.MAX_TOOL_ROUNDS):
        system = {"role": "system", "content": prompts.build_system_prompt(s, config.get_now())}
        try:
            out = llm.chat([system] + _trim(s.messages), tools.tools_for(s))
        except Exception:
            log.exception("Model call failed")
            tools.do_transfer(s, "system_error")
            return APOLOGY[lang]
        s.messages.append(_assistant_msg(out))
        if not out["tool_calls"]:
            text = out["content"].strip()
            return _finalize(s, text, lang, user_text) if text else EMPTY[lang]
        for call in out["tool_calls"]:
            result = tools.run_tool(s, call["name"], call["arguments"])
            if result.get("need_identity"):
                return _identity_step(s, None, lang)
            if s.pending is not None and "call" not in s.pending:
                s.pending["call"] = {"tool": call["name"], "args": call["arguments"]}
            if "say" in result:                   # a code-written reply: speak it, do not ask the model to rephrase
                return result["say"]
            s.messages.append({"role": "tool", "tool_name": call["name"],
                               "content": json.dumps(result, ensure_ascii=False)})
    tools.do_transfer(s, "agent_loop_limit")
    return STUCK[lang]


# ------------------------------------------------------------------ one caller message
def _reply(s, text: str) -> dict:
    s.transcript.append(("assistant", text))
    return {"session_id": s.id, "reply": text, "transferred": s.transferred, "ended": s.ended}


def handle_message(session_id: str, text: str) -> dict:
    expire_stale_sessions()
    s = store.get(session_id)
    if not s:
        raise _not_found()
    with s.lock:
        text = (text or "").strip()[:ai_config.MAX_MESSAGE_CHARS]
        lang = s.lang = _lang(text, s.lang)
        if s.ended or s.transferred:
            return {"session_id": s.id, "ended": s.ended, "transferred": s.transferred,
                    "reply": CLOSED[lang] if s.ended else WAITING[lang]}
        s.last_active = config.get_now()
        if s.token and not pms.touch_token(s.token):          # stay verified while the caller is active
            tools.forget_identity(s)
        s.transcript.append(("user", text))

        hit = safety.check(text)                              # 1. safety, before anything else
        if hit:
            kind, reason = hit
            tools.do_transfer(s, reason)
            return _reply(s, safety.reply_for(kind, text))

        s.messages.append({"role": "user", "content": text})
        base = len(s.messages)
        reply = None
        if s.pending:                                         # 2. yes/no
            reply = _handle_pending(s, text, lang)
        if reply is None and s.awaiting_identity:             # 3. identity
            reply = _identity_step(s, text, lang)
        if reply is None:                                     # 4. model
            reply = _run_turn(s, lang, text)
        del s.messages[base:]                                 # forget the tool chatter of this turn
        s.messages.append({"role": "assistant", "content": reply})
        out = _reply(s, reply)
        if s.end_requested and not s.transferred:
            end_session(s.id, "agent_ended")
            out["ended"] = True
        return out


def session_state(session_id: str) -> dict:
    """Debug view of a call (no personal data beyond the first name)."""
    s = store.get(session_id)
    if not s:
        raise _not_found()
    return {"verified": s.verified, "first_name": s.first_name, "awaiting_identity": s.awaiting_identity,
            "pending_action": s.pending["type"] if s.pending else None, "ctx": s.ctx,
            "options": len(s.options), "appointments_listed": len(s.appts),
            "transferred": s.transferred, "ended": s.ended, "events": [e["type"] for e in s.events]}
