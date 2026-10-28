import { useEffect, useRef, useState } from "react";
import { createOrbState, drawOrb, stepOrb } from "../lib/orbRenderer";
import type { Phase } from "../types";

interface Props {
  phase: Phase;
  /** Returns the current 0..1 level (microphone while listening, speech while speaking). Read every frame, so no re-renders. */
  getLevel: () => number;
  /** Tapping the orb while it speaks interrupts the assistant. */
  onInterrupt?: () => void;
  label: string;
}

/**
 * Siri-style orb on a 2D canvas: organic blobs, soft glow, breathing when idle.
 * Falls back to a CSS-animated gradient when canvas is unavailable.
 */
export function AudioReactiveOrb({ phase, getLevel, onInterrupt, label }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const phaseRef = useRef(phase);
  const levelRef = useRef(getLevel);
  const [canvasOk, setCanvasOk] = useState(true);
  phaseRef.current = phase;
  levelRef.current = getLevel;

  useEffect(() => {
    const canvas = canvasRef.current, wrap = wrapRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !wrap || !ctx) { setCanvasOk(false); return; }

    const reduceMotion = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const state = createOrbState();
    let w = 0, h = 0, raf = 0, last = performance.now();

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = Math.max(1, rect.width); h = Math.max(1, rect.height);
      canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    ro?.observe(wrap);

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);              // clamp after tab switches
      last = now;
      stepOrb(state, { phase: phaseRef.current, level: levelRef.current(), dt, reduceMotion });
      drawOrb(ctx, w, h, state, phaseRef.current);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); ro?.disconnect(); };
  }, []);

  const interactive = phase === "speaking" && !!onInterrupt;
  return (
    <div
      ref={wrapRef}
      className="relative aspect-square w-[min(78vw,36dvh,420px)] lg:w-[min(40vw,52dvh,460px)]"
      role="img"
      aria-label={label}
    >
      {canvasOk ? (
        <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      ) : (
        <div className="absolute inset-[18%] animate-breathe rounded-full bg-[radial-gradient(circle_at_35%_30%,#a5b4fc,#6366f1_45%,#0ea5e9_80%)] shadow-[0_0_80px_20px_rgba(99,102,241,0.35)]" />
      )}
      {interactive && (
        <button
          type="button"
          onClick={onInterrupt}
          aria-label="Interrupt the assistant"
          title="Tap to interrupt"
          className="absolute inset-[22%] rounded-full outline-none focus-visible:ring-2 focus-visible:ring-accent/70"
        />
      )}
    </div>
  );
}
