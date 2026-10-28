import type { Lang } from "../types";

const ARABIC = /[\u0600-\u06FF]/;
const LETTER = /\p{L}/u;

export function hasArabic(text: string): boolean {
  return ARABIC.test(text);
}

/** 'ar' when most letters are Arabic, otherwise 'en'. Digits/punctuation-only text keeps the fallback. */
export function detectLang(text: string, fallback: Lang = "en"): Lang {
  const letters = Array.from(text).filter((c) => LETTER.test(c));
  if (letters.length === 0) return fallback;
  const ar = letters.filter((c) => ARABIC.test(c)).length;
  return ar > letters.length / 2 ? "ar" : "en";
}

export interface Segment { text: string; lang: Lang }

/** Splits mixed text into runs of one script, so each run can be spoken with the right voice. */
export function splitSegments(text: string): Segment[] {
  const out: Segment[] = [];
  const parts = text.split(/(?<=[.!?؟؛\n])\s+/);
  for (const part of parts) {
    const t = part.trim();
    if (!t) continue;
    const lang = detectLang(t, out.length ? out[out.length - 1].lang : "en");
    const last = out[out.length - 1];
    if (last && last.lang === lang && last.text.length + t.length < 180) last.text += " " + t;
    else out.push({ text: t, lang });
  }
  return out;
}

/**
 * The backend greeting is bilingual (English line, Arabic line). Speak only the line(s) in the
 * language the caller selected; fall back to everything if none match.
 */
export function pickLanguageLines(text: string, lang: Lang): string {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const matching = lines.filter((l) => detectLang(l, lang) === lang);
  return (matching.length ? matching : lines).join(" ");
}
