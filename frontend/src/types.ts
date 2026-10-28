export type Lang = "en" | "ar";

export type Phase = "idle" | "initializing" | "listening" | "processing" | "speaking" | "error";

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  ts: number;
  source?: "voice" | "text";
  /** For a failed send: the text the "Try again" button re-sends. */
  retryText?: string;
}

/** Shapes returned by the backend (see agent/chat_schemas.py). */
export interface ChatStartResponse { session_id: string; reply: string }
export interface ChatResponse { session_id: string; reply: string; transferred: boolean; ended: boolean }
export interface CallLog { call_id: number; outcome: string; summary: string; follow_up: string }
