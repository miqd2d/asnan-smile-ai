import type { Lang } from "../../types";
import { splitSegments } from "../../lib/language";

/**
 * Spoken replies through the browser's speechSynthesis.
 *
 * HONEST LIMITATION: speechSynthesis plays audio inside the browser and does not expose it, so a true
 * playback volume cannot be measured. getLevel() is therefore driven by the engine's real word-boundary
 * events (a pulse on every spoken word). Some voices (e.g. Chrome's network voices) emit no boundary events;
 * then a steady "speech activity" level is reported instead. When the backend later streams real audio
 * (an <audio> element), replace this engine with one that reads an AnalyserNode: nothing else changes.
 */
export class SpeechSpeaker {
  private voices: SpeechSynthesisVoice[] = [];
  private gen = 0;
  private speaking = false;
  private startedAt = 0;
  private envelope = 0;
  private envelopeAt = 0;
  private sawBoundary = false;
  private finishCurrent: (() => void) | null = null;
  private alive = new Set<SpeechSynthesisUtterance>();                  // prevents a Chrome GC bug (utterance never ends)

  static get supported(): boolean {
    return typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
  }

  constructor() {
    if (!SpeechSpeaker.supported) return;
    const load = () => { this.voices = window.speechSynthesis.getVoices(); };
    load();
    window.speechSynthesis.addEventListener?.("voiceschanged", load);
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  /** Speaks the text (mixed Arabic/English is split so each part uses a matching voice). Never rejects. */
  async speak(text: string): Promise<void> {
    if (!SpeechSpeaker.supported || !text.trim()) return;
    const mine = ++this.gen;
    window.speechSynthesis.cancel();
    this.speaking = true;
    this.startedAt = performance.now();
    this.sawBoundary = false;
    try {
      for (const seg of splitSegments(text)) {
        if (this.gen !== mine) break;
        await this.speakSegment(seg.text, seg.lang);
      }
    } finally {
      if (this.gen === mine) { this.speaking = false; this.envelope = 0; }
    }
  }

  /** Stops speaking now; the pending speak() promise resolves. */
  cancel(): void {
    this.gen++;
    this.speaking = false;
    this.envelope = 0;
    if (SpeechSpeaker.supported) window.speechSynthesis.cancel();
    this.finishCurrent?.();
  }

  /** 0..1 for the orb. See the class comment: event-driven, not an audio measurement. */
  getLevel(): number {
    if (!this.speaking) return 0;
    const now = performance.now();
    if (this.sawBoundary || now - this.startedAt < 700) return this.envelope * Math.exp(-(now - this.envelopeAt) / 180);
    return 0.42;
  }

  private pulse(v: number) {
    this.envelope = v;
    this.envelopeAt = performance.now();
  }

  private pickVoice(locale: string): SpeechSynthesisVoice | undefined {
    if (!this.voices.length) this.voices = window.speechSynthesis.getVoices();
    const prefix = locale.slice(0, 2).toLowerCase();
    return this.voices.find((v) => v.lang.toLowerCase() === locale.toLowerCase())
      ?? this.voices.find((v) => v.lang.toLowerCase().startsWith(prefix));
  }

  private speakSegment(text: string, lang: Lang): Promise<void> {
    return new Promise<void>((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang === "ar" ? "ar-SA" : "en-US";
      const voice = this.pickVoice(u.lang);
      if (voice) { u.voice = voice; u.lang = voice.lang; }
      let done = false;
      let watchdog: ReturnType<typeof setTimeout>;
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(watchdog);
        if (this.finishCurrent === finish) this.finishCurrent = null;
        this.alive.delete(u);
        resolve();
      };
      // Some browsers never fire 'end'; never let a call hang on it.
      watchdog = setTimeout(finish, Math.max(5000, text.length * 130 + 3000));
      u.onstart = () => this.pulse(0.5);
      u.onboundary = (e: SpeechSynthesisEvent) => {
        this.sawBoundary = true;
        this.pulse(Math.min(1, 0.45 + (e.charLength ?? 5) / 12));
      };
      u.onend = finish;
      u.onerror = finish;
      this.finishCurrent = finish;
      this.alive.add(u);
      window.speechSynthesis.speak(u);
    });
  }
}
