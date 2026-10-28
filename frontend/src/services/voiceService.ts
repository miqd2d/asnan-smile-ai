import { API_BASE, REQUEST_TIMEOUT_MS } from "../config";
import type { CallLog, ChatResponse, ChatStartResponse } from "../types";

/** An error from the backend ({"error": CODE, "message": ...}) or from the network. */
export class ApiError extends Error {
  constructor(public code: string, message: string, public status = 0) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), REQUEST_TIMEOUT_MS);
  const onAbort = () => timeout.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
      signal: timeout.signal,
    });
    const body = await res.json().catch(() => null);
    if (!res.ok) {
      throw new ApiError(body?.error ?? "HTTP_ERROR", body?.message ?? `The assistant returned an error (${res.status}).`, res.status);
    }
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");       // we cancelled it (End Call)
    if (timeout.signal.aborted) throw new ApiError("TIMEOUT", "The assistant took too long to answer.");
    throw new ApiError("NETWORK", "Cannot reach the assistant. Check that the backend is running.");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

/** The existing backend contract: POST /chat/start, POST /chat, POST /chat/{id}/end. */
export const voiceService = {
  startSession: (signal?: AbortSignal) =>
    request<ChatStartResponse>("/chat/start", { method: "POST" }, signal),

  sendMessage: (sessionId: string, message: string, signal?: AbortSignal) =>
    request<ChatResponse>("/chat", { method: "POST", body: JSON.stringify({ session_id: sessionId, message }) }, signal),

  /** Closes the call on the server (writes the call summary). Failures are harmless. */
  endSession: async (sessionId: string): Promise<CallLog | null> => {
    try {
      return await request<CallLog>(`/chat/${encodeURIComponent(sessionId)}/end`, { method: "POST" });
    } catch {
      return null;
    }
  },

  /** Best effort when the tab is closed mid-call. */
  endSessionBeacon: (sessionId: string): void => {
    try {
      navigator.sendBeacon?.(`${API_BASE}/chat/${encodeURIComponent(sessionId)}/end`);
    } catch { /* nothing to do */ }
  },
};
