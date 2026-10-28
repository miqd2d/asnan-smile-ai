import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { INACTIVITY_MS, POST_SPEECH_DELAY_MS } from "../config";
import { pickLanguageLines } from "../lib/language";
import { MicMeter } from "../services/speech/micMeter";
import { SpeechListener } from "../services/speech/recognition";
import { SpeechSpeaker } from "../services/speech/tts";
import { ApiError, voiceService } from "../services/voiceService";
import { initialState, reduce, type MachineEvent, type MachineState } from "../state/sessionMachine";
import type { CallLog, Lang, Message } from "../types";

class VoiceError extends Error {}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const uid = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random()).slice(2));
const isAbort = (e: unknown) => e instanceof DOMException && e.name === "AbortError";

const OUTCOMES: Record<string, string> = {
  BOOKED: "Appointment booked", RESCHEDULED: "Appointment rescheduled", CANCELLED: "Appointment cancelled",
  TRANSFERRED: "Transferred to a team member", INFO_ONLY: "Information provided", ABANDONED: "No request made",
};
const outcomeText = (log: CallLog) => `Call ended · ${OUTCOMES[log.outcome] ?? log.outcome}`;

function micMessage(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access required. Allow it in your browser settings, or keep using text chat.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found. You can keep using text chat.";
  return "Could not open the microphone. You can keep using text chat.";
}

/**
 * The whole voice conversation lifecycle in one place:
 * session with the existing backend, microphone, speech recognition, spoken replies, automatic listening,
 * interruptions and cleanup. Every async step checks an "epoch" (call) and "turn" (message) number, so work
 * belonging to an ended call or an older message can never touch the current state.
 */
export function useVoiceSession() {
  const [state, setState] = useState<MachineState>(initialState);
  const [messages, setMessages] = useState<Message[]>([]);
  const [interim, setInterim] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [lang, setLangState] = useState<Lang>("en");
  const [voiceReplies, setVoiceRepliesState] = useState(true);

  const stateRef = useRef(state);
  const langRef = useRef(lang);
  const voiceRepliesRef = useRef(voiceReplies);
  const engines = useRef<{ mic: MicMeter; listener: SpeechListener; speaker: SpeechSpeaker } | null>(null);
  if (!engines.current) engines.current = { mic: new MicMeter(), listener: new SpeechListener(), speaker: new SpeechSpeaker() };
  const sessionIdRef = useRef<string | null>(null);
  const epochRef = useRef(0);
  const turnRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const startingRef = useRef(false);
  const closedRef = useRef(false);
  const lastActivityRef = useRef(Date.now());
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const api = useMemo(() => {
    const { mic, listener, speaker } = engines.current!;

    const send = (e: MachineEvent) => {
      const next = reduce(stateRef.current, e);
      if (next !== stateRef.current) { stateRef.current = next; setState(next); }
    };
    const later = (fn: () => void, ms: number) => {
      const t = setTimeout(() => { timers.current.delete(t); fn(); }, ms);
      timers.current.add(t);
    };
    const clearTimers = () => { timers.current.forEach(clearTimeout); timers.current.clear(); };
    const showNotice = (text: string) => {
      setNotice(text);
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
      noticeTimer.current = setTimeout(() => setNotice(null), 6000);
    };
    const addMessage = (m: Omit<Message, "id" | "ts">): string => {
      const id = uid();
      setMessages((p) => [...p, { id, ts: Date.now(), ...m }]);
      return id;
    };
    const teardownAudio = () => {
      listener.abort(); speaker.cancel(); mic.stop(); clearTimers(); setInterim("");
    };
    const clearIfClosed = () => {
      if (closedRef.current) { setMessages([]); closedRef.current = false; }
    };

    /** Reuses the backend session (text chat may already have one) or creates it and shows its greeting. */
    async function ensureSession(signal: AbortSignal): Promise<{ created: boolean; greeting?: string }> {
      if (sessionIdRef.current) return { created: false };
      const r = await voiceService.startSession(signal);
      sessionIdRef.current = r.session_id;
      addMessage({ role: "assistant", text: r.reply });
      return { created: true, greeting: r.reply };
    }

    function listen() {
      const s = stateRef.current;
      if (!s.callActive || s.phase !== "listening") return;
      const epoch = epochRef.current;
      const alive = () => epochRef.current === epoch && stateRef.current.callActive && stateRef.current.phase === "listening";
      listener.start(langRef.current, {
        onInterim: (t) => { if (alive()) { lastActivityRef.current = Date.now(); setInterim(t); } },
        onFinal: (t) => { if (alive()) { setInterim(""); void submit(t, "voice"); } },
        onSilence: () => {
          if (!alive()) return;
          if (Date.now() - lastActivityRef.current > INACTIVITY_MS) { void finishCall("inactivity"); return; }
          later(listen, 250);                                           // keep the line open
        },
        onFatal: (message) => {
          if (!alive()) return;
          teardownAudio();
          send({ type: "FAIL", message, fatal: true });
        },
      });
    }

    function scheduleResume() {
      const epoch = epochRef.current;
      later(() => {
        if (epochRef.current !== epoch || stateRef.current.phase !== "error") return;
        send({ type: "RESUME" });
        if (stateRef.current.callActive) listen();
      }, stateRef.current.callActive ? 2500 : 4000);
    }

    /** One caller message (spoken or typed) through the real agent, then speak the answer and listen again. */
    async function submit(text: string, source: "voice" | "text"): Promise<boolean> {
      const clean = text.trim();
      if (!clean) return false;
      const phase = stateRef.current.phase;
      if (phase === "processing" || phase === "initializing") return false;

      listener.abort(); speaker.cancel(); clearTimers(); setInterim("");
      const turn = ++turnRef.current;
      const epoch = epochRef.current;
      const current = () => turnRef.current === turn && epochRef.current === epoch;
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      lastActivityRef.current = Date.now();
      send({ type: source === "voice" ? "UTTERANCE" : "TEXT_SUBMIT" });

      let userId: string | null = null;
      try {
        clearIfClosed();
        await ensureSession(ctrl.signal);
        if (!current()) return true;
        userId = addMessage({ role: "user", text: clean, source });
        const res = await voiceService.sendMessage(sessionIdRef.current!, clean, ctrl.signal);
        if (!current()) return true;
        lastActivityRef.current = Date.now();
        addMessage({ role: "assistant", text: res.reply });
        const finish = res.transferred ? "transferred" : res.ended ? "ended" : null;
        const speak = voiceRepliesRef.current && SpeechSpeaker.supported;
        send({ type: "REPLY", speak });
        if (speak) {
          await speaker.speak(res.reply);
          if (!current()) return true;
          if (stateRef.current.callActive && !finish) await sleep(POST_SPEECH_DELAY_MS);   // do not hear the tail of our own voice
          if (!current()) return true;
          send({ type: "SPEAK_DONE" });
        }
        if (finish) { await finishCall(finish); return true; }
        if (stateRef.current.callActive) listen();
        return true;
      } catch (e) {
        if (isAbort(e) || !current()) return true;
        const err = e instanceof ApiError ? e : new ApiError("UNKNOWN", "Something went wrong. Please try again.");
        if (userId) { const id = userId; setMessages((p) => p.filter((m) => m.id !== id)); }
        if (err.code === "SESSION_NOT_FOUND") {                         // backend restarted or the call timed out
          epochRef.current++; teardownAudio();
          sessionIdRef.current = null; closedRef.current = true;
          addMessage({ role: "system", text: "This session has expired. Start a new call or send a message to begin again." });
          send({ type: "END_CALL" });
          return true;
        }
        addMessage({ role: "system", text: err.message, retryText: clean });
        send({ type: "FAIL", message: err.message, fatal: false });
        scheduleResume();
        return true;
      }
    }

    /** The conversation is over (agent hung up, transfer, silence): stop the audio but keep the transcript on screen. */
    async function finishCall(kind: "ended" | "transferred" | "inactivity") {
      const id = sessionIdRef.current;
      epochRef.current++;
      abortRef.current?.abort();
      teardownAudio();
      sessionIdRef.current = null;
      closedRef.current = true;
      addMessage({
        role: "system",
        text: kind === "transferred" ? "Transferred to a team member." : kind === "inactivity" ? "Call ended after a period of silence." : "The call has ended.",
      });
      send({ type: "END_CALL" });
      if (id) {
        const log = await voiceService.endSession(id);                  // writes the call summary
        if (log) showNotice(outcomeText(log));
      }
    }

    async function startCall() {
      const s = stateRef.current;
      if (startingRef.current || s.callActive) return;                  // no duplicate sessions
      if (s.phase !== "idle" && s.phase !== "error" && s.phase !== "speaking") return;
      startingRef.current = true;
      turnRef.current++; speaker.cancel();                              // cut off a spoken text reply, drop its follow-ups
      const epoch = ++epochRef.current;
      const alive = () => epochRef.current === epoch;
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setNotice(null);
      send({ type: "START_CALL" });
      try {
        if (!SpeechListener.supported) throw new VoiceError("Voice calls need Chrome, Edge or Safari. You can keep using text chat.");
        if (!MicMeter.supported) throw new VoiceError("This browser cannot access a microphone. You can keep using text chat.");
        try { await mic.start(); } catch (e) { throw new VoiceError(micMessage(e)); }
        if (!alive()) { mic.stop(); return; }
        clearIfClosed();
        const { created, greeting } = await ensureSession(ctrl.signal);
        if (!alive()) return;
        lastActivityRef.current = Date.now();
        const speak = created && voiceRepliesRef.current && SpeechSpeaker.supported;
        send({ type: "CALL_READY", speak });
        if (speak) {
          await speaker.speak(pickLanguageLines(greeting!, langRef.current));
          if (!alive()) return;
          await sleep(POST_SPEECH_DELAY_MS);
          if (!alive()) return;
          send({ type: "SPEAK_DONE" });
        }
        listen();
      } catch (e) {
        if (isAbort(e) || !alive()) return;
        teardownAudio();
        const message = e instanceof VoiceError || e instanceof ApiError ? e.message : "Could not start the call.";
        send({ type: "FAIL", message, fatal: true });
      } finally {
        startingRef.current = false;
      }
    }

    function endCall() {
      const s = stateRef.current;
      if (!s.callActive && s.phase !== "initializing") return;
      const id = sessionIdRef.current;
      epochRef.current++; turnRef.current++;
      abortRef.current?.abort();
      teardownAudio();
      sessionIdRef.current = null;
      closedRef.current = false;
      send({ type: "END_CALL" });
      setMessages([]);
      if (id) void voiceService.endSession(id).then((log) => { if (log) showNotice(outcomeText(log)); });
    }

    return {
      startCall, endCall,
      /** Resolves true as soon as the message is ACCEPTED (so the box clears at once); the turn continues in the background. */
      sendText: (t: string): Promise<boolean> => {
        const phase = stateRef.current.phase;
        if (!t.trim() || phase === "processing" || phase === "initializing") return Promise.resolve(false);
        void submit(t, "text");
        return Promise.resolve(true);
      },
      interrupt: () => { if (stateRef.current.phase === "speaking") speaker.cancel(); },
      setLang: (l: Lang) => {
        langRef.current = l; setLangState(l);
        if (stateRef.current.phase === "listening") { listener.abort(); listen(); }   // switch recognition language live
      },
      setVoiceReplies: (on: boolean) => {
        voiceRepliesRef.current = on; setVoiceRepliesState(on);
        if (!on) speaker.cancel();
      },
      getLevel: (): number => {
        const ph = stateRef.current.phase;
        if (ph === "listening") return mic.metering ? mic.getLevel() : listener.getEnvelope();
        if (ph === "speaking") return speaker.getLevel();
        return 0;
      },
    };
  }, []);

  useEffect(() => {
    const onHide = () => { if (sessionIdRef.current) voiceService.endSessionBeacon(sessionIdRef.current); };
    window.addEventListener("pagehide", onHide);
    const { mic, listener, speaker } = engines.current!;
    const pending = timers.current;
    return () => {
      window.removeEventListener("pagehide", onHide);
      epochRef.current++; turnRef.current++;
      abortRef.current?.abort();
      listener.abort(); speaker.cancel(); mic.stop();
      pending.forEach(clearTimeout); pending.clear();
      if (noticeTimer.current) clearTimeout(noticeTimer.current);
    };
  }, []);

  const supports = useMemo(() => ({
    recognition: SpeechListener.supported, speech: SpeechSpeaker.supported, microphone: MicMeter.supported,
  }), []);

  const getLevel = useCallback(() => api.getLevel(), [api]);

  return {
    phase: state.phase, callActive: state.callActive, error: state.error, fatal: state.fatal,
    messages, interim, notice, lang, voiceReplies, supports,
    startCall: api.startCall, endCall: api.endCall, sendText: api.sendText, interrupt: api.interrupt,
    setLang: api.setLang, setVoiceReplies: api.setVoiceReplies, getLevel,
  };
}
