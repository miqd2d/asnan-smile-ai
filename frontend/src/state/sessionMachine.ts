import type { Phase } from "../types";

/**
 * The voice session as an explicit state machine. Invalid transitions are ignored,
 * so late async callbacks (a reply arriving after End Call, a stale 'speech finished') cannot corrupt state.
 *
 *   idle -> initializing -> (speaking greeting) -> listening <-> processing <-> speaking
 *   any  -> error (recoverable or fatal)  -> idle / listening
 *   any  -> idle on END_CALL
 */
export interface MachineState {
  phase: Phase;
  /** True while a hands-free voice call is running (microphone open, auto-listening). */
  callActive: boolean;
  error: string | null;
  /** A fatal error ended the call (microphone denied, unsupported browser...). Text chat still works. */
  fatal: boolean;
}

export type MachineEvent =
  | { type: "START_CALL" }
  | { type: "CALL_READY"; speak: boolean }
  | { type: "UTTERANCE" }                 // recognised speech sent to the agent
  | { type: "TEXT_SUBMIT" }               // typed message sent to the agent
  | { type: "REPLY"; speak: boolean }     // the agent answered
  | { type: "SPEAK_DONE" }
  | { type: "FAIL"; message: string; fatal: boolean }
  | { type: "RESUME" }
  | { type: "END_CALL" };

export const initialState: MachineState = { phase: "idle", callActive: false, error: null, fatal: false };

export function reduce(s: MachineState, e: MachineEvent): MachineState {
  switch (e.type) {
    case "START_CALL":
      if ((s.phase === "idle" || s.phase === "error" || s.phase === "speaking") && !s.callActive)
        return { phase: "initializing", callActive: true, error: null, fatal: false };
      return s;
    case "CALL_READY":
      if (s.phase === "initializing") return { ...s, phase: e.speak ? "speaking" : "listening" };
      return s;
    case "UTTERANCE":
      if (s.phase === "listening") return { ...s, phase: "processing", error: null };
      return s;
    case "TEXT_SUBMIT":
      if (["idle", "error", "listening", "speaking"].includes(s.phase)) return { ...s, phase: "processing", error: null, fatal: false };
      return s;
    case "REPLY":
      if (s.phase !== "processing") return s;
      return { ...s, phase: e.speak ? "speaking" : s.callActive ? "listening" : "idle" };
    case "SPEAK_DONE":
      if (s.phase !== "speaking") return s;
      return { ...s, phase: s.callActive ? "listening" : "idle" };
    case "FAIL":
      return e.fatal
        ? { phase: "error", callActive: false, error: e.message, fatal: true }
        : { ...s, phase: "error", error: e.message, fatal: false };
    case "RESUME":
      if (s.phase !== "error") return s;
      return { phase: s.callActive && !s.fatal ? "listening" : "idle", callActive: s.callActive && !s.fatal, error: null, fatal: false };
    case "END_CALL":
      return initialState;
  }
}

export const STATUS_TEXT: Record<Phase, string> = {
  idle: "Ready to begin",
  initializing: "Connecting...",
  listening: "Listening...",
  processing: "Thinking...",
  speaking: "Speaking...",
  error: "Something went wrong",
};
