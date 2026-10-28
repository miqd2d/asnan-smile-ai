import type { Lang } from "../../types";

/** Minimal typings for the Web Speech API (not in lib.dom for every TypeScript version). */
interface SRAlternative { transcript: string }
interface SRResult { isFinal: boolean; 0: SRAlternative }
interface SREvent { resultIndex: number; results: ArrayLike<SRResult> & { length: number } }
interface SRErrorEvent { error: string }
interface SRInstance {
  lang: string; continuous: boolean; interimResults: boolean; maxAlternatives: number;
  onresult: ((e: SREvent) => void) | null; onerror: ((e: SRErrorEvent) => void) | null;
  onend: (() => void) | null; onspeechstart: (() => void) | null; onspeechend: (() => void) | null;
  start(): void; abort(): void; stop(): void;
}
type SRCtor = new () => SRInstance;

function getCtor(): SRCtor | undefined {
  if (typeof window === "undefined") return undefined;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition;
}

export interface ListenHandlers {
  onInterim: (text: string) => void;
  /** One finished utterance (recognition ends by itself after the caller stops talking). */
  onFinal: (text: string) => void;
  /** Recognition ended without any speech: the caller should simply listen again. */
  onSilence: () => void;
  /** Cannot continue (microphone blocked, no internet, unsupported language...). */
  onFatal: (message: string) => void;
}

const LOCALE: Record<Lang, string> = { en: "en-US", ar: "ar-KW" };

const FATAL_MESSAGES: Record<string, string> = {
  "not-allowed": "Microphone access required. Allow it in your browser settings, or keep using text chat.",
  "service-not-allowed": "Microphone access required. Allow it in your browser settings, or keep using text chat.",
  "audio-capture": "No microphone was found. You can keep using text chat.",
  network: "Speech recognition needs an internet connection. You can keep using text chat.",
  "language-not-supported": "This language is not supported for speech recognition in your browser.",
};

/**
 * Hands-free turn taking built on the browser's SpeechRecognition (Chrome / Edge / Safari).
 * Turn detection is the browser's own: a recognition session ends after the caller stops speaking.
 * Only one recognition runs at a time, and abort() makes any late callback from an old one a no-op.
 */
export class SpeechListener {
  private rec: SRInstance | null = null;
  private heardSpeech = false;

  static get supported(): boolean {
    return getCtor() !== undefined;
  }

  get listening(): boolean {
    return this.rec !== null;
  }

  /** 0.5 while the browser reports speech, else 0. Only a fallback for the orb when the microphone cannot be metered. */
  getEnvelope(): number {
    return this.rec && this.heardSpeech ? 0.5 : 0;
  }

  start(lang: Lang, h: ListenHandlers): void {
    this.abort();
    const Ctor = getCtor();
    if (!Ctor) { h.onFatal("Voice calls need Chrome, Edge or Safari. You can keep using text chat."); return; }
    const rec = new Ctor();
    rec.lang = LOCALE[lang];
    rec.continuous = false;
    rec.interimResults = true;
    rec.maxAlternatives = 1;
    let finalText = "";
    let error: string | null = null;
    this.heardSpeech = false;

    rec.onspeechstart = () => { if (this.rec === rec) this.heardSpeech = true; };
    rec.onspeechend = () => { if (this.rec === rec) this.heardSpeech = false; };
    rec.onresult = (ev) => {
      if (this.rec !== rec) return;
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
      }
      const shown = (finalText + interim).trim();
      if (shown) h.onInterim(shown);
    };
    rec.onerror = (ev) => { if (this.rec === rec) error = ev.error; };
    rec.onend = () => {
      if (this.rec !== rec) return;                                    // aborted by us: ignore
      this.rec = null;
      this.heardSpeech = false;
      if (error && FATAL_MESSAGES[error]) { h.onFatal(FATAL_MESSAGES[error]); return; }
      const text = finalText.trim();
      if (text) h.onFinal(text); else h.onSilence();                   // 'no-speech', 'aborted' and the rest = silence
    };

    this.rec = rec;
    try {
      rec.start();
    } catch {
      this.rec = null;                                                  // e.g. InvalidStateError: try again shortly
      setTimeout(h.onSilence, 600);
    }
  }

  /** Stops recognition immediately and silences all of its callbacks. */
  abort(): void {
    const rec = this.rec;
    this.rec = null;
    this.heardSpeech = false;
    if (rec) { try { rec.abort(); } catch { /* already stopped */ } }
  }
}
