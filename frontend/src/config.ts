/** Base URL for the FastAPI backend. In dev, "/api" is proxied to it by vite.config.ts (no CORS needed). */
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

/** A chat request may take a while on a small local model. */
export const REQUEST_TIMEOUT_MS = 90_000;

/** A call with no speech for this long is ended automatically. */
export const INACTIVITY_MS = 3 * 60_000;

/** Pause after the assistant finishes speaking before the microphone reopens (avoids hearing its own tail). */
export const POST_SPEECH_DELAY_MS = 450;
