import { describe, expect, it } from "vitest";
import { detectLang, pickLanguageLines, splitSegments } from "../src/lib/language";

describe("language helpers", () => {
  it("detects Arabic and English, keeps the fallback for digits", () => {
    expect(detectLang("I need a cleaning")).toBe("en");
    expect(detectLang("أريد موعدا")).toBe("ar");
    expect(detectLang("1188", "ar")).toBe("ar");
  });
  it("splits mixed text into runs with the right language", () => {
    const seg = splitSegments("Your appointment is booked. تم حجز موعدك.");
    expect(seg.map((s) => s.lang)).toEqual(["en", "ar"]);
  });
  it("speaks only the greeting line in the chosen language", () => {
    const greeting = "Welcome to the clinic. How can I help?\nمرحبًا بكم في العيادة. كيف يمكنني مساعدتكم؟";
    expect(pickLanguageLines(greeting, "en")).toBe("Welcome to the clinic. How can I help?");
    expect(pickLanguageLines(greeting, "ar")).toMatch(/^مرحبًا/);
    expect(pickLanguageLines("Hello there", "ar")).toBe("Hello there");     // nothing matches: speak it anyway
  });
});
