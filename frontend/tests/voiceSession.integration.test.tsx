/**
 * End-to-end test of the real UI + real hook + real HTTP calls against the real agent backend
 * (tests/support/fake_backend.py). Only the browser hardware APIs are replaced by controllable fakes:
 * microphone, SpeechRecognition and speechSynthesis.
 *
 *   python tests/support/fake_backend.py 8765      (in one terminal)
 *   npm test                                       (in another)
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceAssistantPage } from "../src/pages/VoiceAssistantPage";

const BASE = import.meta.env.VITE_API_BASE as string;
const backendUp = await fetch(`${BASE}/health`).then((r) => r.ok).catch(() => false);
const patient: { patient_id: number; phone: string } = backendUp ? await fetch(`${BASE}/_test/patient`).then((r) => r.json()) : { patient_id: 0, phone: "" };

// ------------------------------------------------------------------ fake browser hardware
type Fn = ((e?: unknown) => void) | null;
class FakeRecognition {
  static all: FakeRecognition[] = [];
  lang = ""; continuous = false; interimResults = false; maxAlternatives = 1; started = false;
  onresult: ((e: unknown) => void) | null = null; onerror: Fn = null; onend: Fn = null; onspeechstart: Fn = null; onspeechend: Fn = null;
  start() { this.started = true; FakeRecognition.all.push(this); }
  abort() { this.started = false; }
  stop() { this.started = false; }
  say(text: string) {
    this.onspeechstart?.();
    this.onresult?.({ resultIndex: 0, results: [Object.assign({ isFinal: true }, { 0: { transcript: text } })] });
    this.started = false; this.onend?.();
  }
}
let spoken: string[] = [];
let holdSpeech = false;
let cancels = 0;
let currentUtterance: { onstart?: Fn; onend?: Fn; onerror?: Fn } | null = null;
let trackStops = 0;
let getUserMedia: ReturnType<typeof vi.fn>;

const win = window as unknown as Record<string, unknown>;
const activeRecognition = () => FakeRecognition.all.filter((r) => r.started).at(-1);

beforeEach(() => {
  FakeRecognition.all = []; spoken = []; holdSpeech = false; cancels = 0; trackStops = 0; currentUtterance = null;
  win.SpeechRecognition = FakeRecognition;
  win.SpeechSynthesisUtterance = class { text: string; lang = ""; voice = null; onstart: Fn = null; onend: Fn = null; onerror: Fn = null; onboundary: Fn = null; constructor(t: string) { this.text = t; } };
  win.speechSynthesis = {
    speak(u: { text: string; onstart?: Fn; onend?: Fn; onerror?: Fn }) {
      spoken.push(u.text); currentUtterance = u;
      if (holdSpeech) u.onstart?.(); else setTimeout(() => { u.onstart?.(); u.onend?.(); }, 10);
    },
    cancel() { cancels++; const u = currentUtterance; currentUtterance = null; u?.onerror?.(); },
    getVoices: () => [], addEventListener() {},
  };
  win.AudioContext = class {
    state = "running"; resume() { return Promise.resolve(); } close() { return Promise.resolve(); }
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() { return { fftSize: 0, smoothingTimeConstant: 0, getFloatTimeDomainData(b: Float32Array) { b.fill(0.05); } }; }
  };
  getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop: () => { trackStops++; } }] }));
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// ------------------------------------------------------------------ helpers
const see = (text: string | RegExp) => screen.findByText(text, undefined, { timeout: 6000 });
const press = (name: string) => fireEvent.click(screen.getByRole("button", { name }));
const callerSays = async (text: string) => {
  await waitFor(() => expect(activeRecognition()).toBeTruthy(), { timeout: 6000 });
  act(() => { activeRecognition()!.say(text); });
};
const typeAndSend = (text: string) => {
  const box = screen.getByPlaceholderText("Type a message...");
  fireEvent.change(box, { target: { value: text } });
  fireEvent.keyDown(box, { key: "Enter" });
};

describe.skipIf(!backendUp)("voice assistant, end to end against the real backend", () => {
  it("shows the idle state with Start Call enabled and End Call disabled", () => {
    render(<VoiceAssistantPage />);
    expect(screen.getByText("Ready to begin")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start Call" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "End Call" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Your conversation will appear here.")).toBeTruthy();
  });

  it("runs a complete spoken booking: greeting, listening, agent turns, receipt, hands-free throughout", async () => {
    render(<VoiceAssistantPage />);
    press("Start Call");
    expect(await see("Listening...")).toBeTruthy();
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Welcome to Asnan Tower Dental Clinic/)).toBeTruthy();
    expect(spoken[0]).toMatch(/^Welcome/);
    expect(spoken[0]).not.toMatch(/[\u0600-\u06FF]/);                       // English selected: only the English line is spoken

    await callerSays("I need a cleaning with Dr Burezq on Wednesday");
    expect(await see(/I have these times/)).toBeTruthy();                   // real agent reply, shown in chat
    expect(screen.getByText("I need a cleaning with Dr Burezq on Wednesday")).toBeTruthy();
    expect(await see("Listening...")).toBeTruthy();                         // resumed automatically after speaking
    expect(spoken.join(" ")).toMatch(/I have these times/);                  // the whole reply is spoken

    await callerSays("the first one");
    expect(await see(/patient file number/)).toBeTruthy();                  // the system asks for identity once
    await callerSays(`my file number is ${patient.patient_id} and my phone is ${patient.phone}`);
    expect(await see(/Shall I book it\?/)).toBeTruthy();
    await callerSays("yes please");
    expect(await see(/Your appointment is booked/)).toBeTruthy();
    expect(await see("Listening...")).toBeTruthy();
    expect(getUserMedia).toHaveBeenCalledTimes(1);                          // one permission prompt for the whole call
  });

  it("End Call stops the microphone, recognition and speech, resets the page, and a second call works", async () => {
    render(<VoiceAssistantPage />);
    press("Start Call");
    await see("Listening...");
    await callerSays("hello");
    await see(/Hello! How can I help you today\?/);
    await see("Listening...");
    press("End Call");

    await screen.findByText("Ready to begin");
    expect(trackStops).toBeGreaterThanOrEqual(1);                           // microphone released
    expect(FakeRecognition.all.some((r) => r.started)).toBe(false);         // nothing is listening any more
    expect(cancels).toBeGreaterThanOrEqual(1);                              // speech cancelled
    expect(screen.getByText("Your conversation will appear here.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start Call" }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole("button", { name: "End Call" }) as HTMLButtonElement).disabled).toBe(true);
    await new Promise((r) => setTimeout(r, 900));                           // no late auto-listening after the call ended
    expect(FakeRecognition.all.some((r) => r.started)).toBe(false);

    press("Start Call");
    await see("Listening...");
    expect(screen.getAllByText(/Welcome to Asnan Tower Dental Clinic/)).toHaveLength(1);   // fresh session, no duplicates
    expect(getUserMedia).toHaveBeenCalledTimes(2);
  });

  it("ignores repeated Start Call clicks (no duplicate sessions)", async () => {
    render(<VoiceAssistantPage />);
    const start = screen.getByRole("button", { name: "Start Call" });
    fireEvent.click(start); fireEvent.click(start); fireEvent.click(start);
    await see("Listening...");
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText(/Welcome to Asnan Tower Dental Clinic/)).toHaveLength(1);
  });

  it("text chat works with no call and no microphone", async () => {
    render(<VoiceAssistantPage />);
    typeAndSend("hello");
    await waitFor(() => expect((screen.getByPlaceholderText("Type a message...") as HTMLTextAreaElement).value).toBe(""));   // cleared at once
    expect(await see(/Hello! How can I help you today\?/)).toBeTruthy();
    expect(screen.getByText("hello")).toBeTruthy();
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(spoken.at(-1)).toMatch(/Hello!/);                                // Voice on: the reply is spoken
    expect((screen.getByPlaceholderText("Type a message...") as HTMLTextAreaElement).value).toBe("");
  });

  it("Shift+Enter does not send; voice off keeps replies silent", async () => {
    render(<VoiceAssistantPage />);
    fireEvent.click(screen.getByRole("button", { name: "Voice off" }));
    const box = screen.getByPlaceholderText("Type a message...");
    fireEvent.change(box, { target: { value: "hello" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    await new Promise((r) => setTimeout(r, 200));
    expect(screen.queryByText(/Hello! How can I help/)).toBeNull();
    fireEvent.keyDown(box, { key: "Enter" });
    await see(/Hello! How can I help you today\?/);
    expect(spoken).toHaveLength(0);
  });

  it("a typed message during a call is answered and listening resumes", async () => {
    render(<VoiceAssistantPage />);
    press("Start Call");
    await see("Listening...");
    typeAndSend("hello");
    await see(/Hello! How can I help you today\?/);
    expect(await see("Listening...")).toBeTruthy();
  });

  it("microphone denied: clear message, text chat still works, Start Call can be retried", async () => {
    getUserMedia.mockRejectedValueOnce(Object.assign(new Error("denied"), { name: "NotAllowedError" }));
    render(<VoiceAssistantPage />);
    press("Start Call");
    expect(await see(/Microphone access required/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "End Call" }) as HTMLButtonElement).disabled).toBe(true);
    typeAndSend("hello");
    expect(await see(/Hello! How can I help you today\?/)).toBeTruthy();
    press("Start Call");
    expect(await see("Listening...")).toBeTruthy();                         // permission granted this time
  });

  it("unsupported speech recognition: explains it and keeps text chat", async () => {
    delete win.SpeechRecognition;
    render(<VoiceAssistantPage />);
    expect(screen.getByText(/Voice calls need Chrome, Edge or Safari/)).toBeTruthy();
    press("Start Call");
    expect(await see(/Voice calls need Chrome, Edge or Safari. You can keep using text chat./)).toBeTruthy();
    typeAndSend("hello");
    expect(await see(/Hello! How can I help you today\?/)).toBeTruthy();
  });

  it("tapping the orb while the assistant speaks interrupts it and resumes listening", async () => {
    holdSpeech = true;
    render(<VoiceAssistantPage />);
    press("Start Call");
    expect(await see("Speaking...")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Interrupt the assistant" }));
    expect(await see("Listening...")).toBeTruthy();
    expect(cancels).toBeGreaterThanOrEqual(1);
  });

  it("a network failure shows a message with Try again, and the call recovers", async () => {
    const realFetch = globalThis.fetch;
    let failed = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (!failed && String(input).endsWith("/chat") && init?.method === "POST") { failed = true; return Promise.reject(new TypeError("offline")); }
      return realFetch(input, init);
    });
    render(<VoiceAssistantPage />);
    press("Start Call");
    await see("Listening...");
    await callerSays("hello");
    expect(await see(/Cannot reach the assistant/)).toBeTruthy();
    expect(screen.queryByText("hello")).toBeNull();                         // the unsent message is not left behind
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await see(/Hello! How can I help you today\?/)).toBeTruthy();
    expect(await see("Listening...")).toBeTruthy();
  });

  it("the agent ending the call keeps the transcript, releases the microphone, and allows a new call", async () => {
    render(<VoiceAssistantPage />);
    press("Start Call");
    await see("Listening...");
    await callerSays("goodbye");
    expect(await see(/Goodbye/)).toBeTruthy();
    expect(await see("The call has ended.")).toBeTruthy();
    expect(await see(/Call ended ·/)).toBeTruthy();                         // outcome from the saved call summary
    await screen.findByText("Ready to begin");
    expect(trackStops).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("goodbye")).toBeTruthy();                       // transcript still readable
    press("Start Call");
    await see("Listening...");
    expect(screen.queryByText("goodbye")).toBeNull();                       // new call starts clean
  });

  it("an emergency is transferred: message shown, spoken, call closed", async () => {
    render(<VoiceAssistantPage />);
    press("Start Call");
    await see("Listening...");
    await callerSays("my face is swollen and I can't breathe");
    expect(await see(/112/)).toBeTruthy();
    expect(await see("Transferred to a team member.")).toBeTruthy();
    await screen.findByText("Ready to begin");
  });

  it("Arabic: language toggle switches recognition and the spoken greeting", async () => {
    render(<VoiceAssistantPage />);
    fireEvent.click(screen.getByRole("button", { name: "عربي" }));
    press("Start Call");
    await see("Listening...");
    expect(spoken[0]).toMatch(/^مرحبًا/);
    await waitFor(() => expect(activeRecognition()).toBeTruthy());
    expect(activeRecognition()!.lang).toBe("ar-KW");
  });
});
