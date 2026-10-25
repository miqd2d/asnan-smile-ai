"""
agent.py - The conversation loop.

Per caller message:  safety pre-check (code) -> model -> (tool -> model)* -> reply.
The model forgets everything between calls, so the Session object remembers for it.
"""
import json
import logging

import config
from rules import RuleError

from . import ai_config, calls, llm, prompts, safety, summary, tools
from . import session as store

log = logging.getLogger("uvicorn.error")

APOLOGY = {"en": "Sorry, I am having technical trouble. I am transferring you to a team member.",
           "ar": "عذرًا، لدي مشكلة تقنية. سأحوّلك إلى أحد أعضاء الفريق."}
STUCK = {"en": "I am sorry, I could not complete that. Let me transfer you to a team member.",
         "ar": "عذرًا، لم أتمكن من إكمال ذلك. سأحوّلك إلى أحد أعضاء الفريق."}
CLOSED = {"en": "This call has ended. Please call again if you need anything.",
          "ar": "انتهت المكالمة. يرجى الاتصال مرة أخرى إذا احتجتم لأي شيء."}
EMPTY = {"en": "Sorry, could you say that again?", "ar": "عذرًا، هل يمكنك إعادة ذلك؟"}


def _lang(text: str) -> str:
    return "ar" if safety.is_arabic(text) else "en"


def _not_found():
    return RuleError("SESSION_NOT_FOUND", "This conversation was not found or has expired.", 404)


# ------------------------------------------------------------------ lifecycle
def start_session() -> dict:
    expire_stale_sessions()
    s = store.create()
    s.transcript.append(("assistant", prompts.GREETING))
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
    """Close the call: build the summary, store it, return the stored record."""
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


# ------------------------------------------------------------------ one caller message
def _trim(messages: list) -> list:
    m = messages[-ai_config.MAX_HISTORY_MESSAGES:]
    while m and m[0]["role"] != "user":        # never start in the middle of a tool exchange
        m = m[1:]
    return m


def _assistant_msg(out: dict) -> dict:
    msg = {"role": "assistant", "content": out["content"]}
    if out["tool_calls"]:
        msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["arguments"]}}
                             for c in out["tool_calls"]]
    return msg


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
        lang = _lang(text)
        if s.ended or s.transferred:
            return {"session_id": s.id, "ended": s.ended, "transferred": s.transferred,
                    "reply": CLOSED[lang] if s.ended else
                    ("A team member will be with you shortly." if lang == "en" else "سيكون أحد أعضاء الفريق معكم قريبًا.")}
        s.last_active = config.get_now()
        s.transcript.append(("user", text))

        hit = safety.check(text)                                  # 1. code-level safety, before the model
        if hit:
            kind, reason = hit
            tools.do_transfer(s, reason)
            return _reply(s, safety.reply_for(kind, text))

        s.messages.append({"role": "user", "content": text})
        reply = _run_turn(s, lang)
        out = _reply(s, reply)
        if s.end_requested and not s.transferred:
            end_session(s.id, "agent_ended")
            out["ended"] = True
        return out


def _run_turn(s, lang: str) -> str:
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
            return out["content"].strip() or EMPTY[lang]
        for call in out["tool_calls"]:
            result = tools.run_tool(s, call["name"], call["arguments"])
            s.messages.append({"role": "tool", "tool_name": call["name"],
                               "content": json.dumps(result, ensure_ascii=False)})
        if s.transferred:
            return safety.REPLIES["transfer"][lang]
    tools.do_transfer(s, "agent_loop_limit")
    return STUCK[lang]
