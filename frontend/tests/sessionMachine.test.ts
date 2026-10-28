import { describe, expect, it } from "vitest";
import { initialState, reduce, type MachineEvent, type MachineState } from "../src/state/sessionMachine";

const run = (events: MachineEvent[], from: MachineState = initialState) => events.reduce(reduce, from);

describe("session state machine", () => {
  it("runs a full voice turn: idle -> initializing -> speaking -> listening -> processing -> speaking -> listening", () => {
    let s = run([{ type: "START_CALL" }]);
    expect(s).toMatchObject({ phase: "initializing", callActive: true });
    s = run([{ type: "CALL_READY", speak: true }], s);
    expect(s.phase).toBe("speaking");
    s = run([{ type: "SPEAK_DONE" }, { type: "UTTERANCE" }], s);
    expect(s.phase).toBe("processing");
    s = run([{ type: "REPLY", speak: true }], s);
    expect(s.phase).toBe("speaking");
    s = run([{ type: "SPEAK_DONE" }], s);
    expect(s).toMatchObject({ phase: "listening", callActive: true });
  });

  it("goes straight to listening when nothing is spoken", () => {
    expect(run([{ type: "START_CALL" }, { type: "CALL_READY", speak: false }]).phase).toBe("listening");
  });

  it("ignores events that do not fit the current state (late async callbacks)", () => {
    expect(run([{ type: "REPLY", speak: true }]).phase).toBe("idle");
    expect(run([{ type: "SPEAK_DONE" }]).phase).toBe("idle");
    expect(run([{ type: "UTTERANCE" }]).phase).toBe("idle");
    const s = run([{ type: "START_CALL" }, { type: "START_CALL" }]);
    expect(s.phase).toBe("initializing");                                  // no duplicate session
  });

  it("text chat works without a call and returns to idle", () => {
    let s = run([{ type: "TEXT_SUBMIT" }]);
    expect(s).toMatchObject({ phase: "processing", callActive: false });
    s = run([{ type: "REPLY", speak: false }], s);
    expect(s.phase).toBe("idle");
  });

  it("a typed message during a call keeps the call and resumes listening", () => {
    let s = run([{ type: "START_CALL" }, { type: "CALL_READY", speak: false }, { type: "TEXT_SUBMIT" }]);
    expect(s).toMatchObject({ phase: "processing", callActive: true });
    s = run([{ type: "REPLY", speak: false }], s);
    expect(s.phase).toBe("listening");
  });

  it("a fatal failure ends the call but allows text chat afterwards", () => {
    let s = run([{ type: "START_CALL" }, { type: "FAIL", message: "Microphone access required", fatal: true }]);
    expect(s).toMatchObject({ phase: "error", callActive: false, fatal: true });
    s = run([{ type: "TEXT_SUBMIT" }], s);
    expect(s).toMatchObject({ phase: "processing", error: null });
    expect(run([{ type: "START_CALL" }], run([{ type: "START_CALL" }, { type: "FAIL", message: "x", fatal: true }])).phase).toBe("initializing");
  });

  it("a recoverable failure keeps the call and resumes listening", () => {
    let s = run([{ type: "START_CALL" }, { type: "CALL_READY", speak: false }, { type: "UTTERANCE" }, { type: "FAIL", message: "network", fatal: false }]);
    expect(s).toMatchObject({ phase: "error", callActive: true });
    s = run([{ type: "RESUME" }], s);
    expect(s).toMatchObject({ phase: "listening", callActive: true, error: null });
  });

  it("END_CALL resets from every state", () => {
    for (const events of [
      [{ type: "START_CALL" }], [{ type: "START_CALL" }, { type: "CALL_READY", speak: true }],
      [{ type: "START_CALL" }, { type: "CALL_READY", speak: false }, { type: "UTTERANCE" }],
    ] as MachineEvent[][]) {
      expect(run([...events, { type: "END_CALL" }])).toEqual(initialState);
    }
  });
});
