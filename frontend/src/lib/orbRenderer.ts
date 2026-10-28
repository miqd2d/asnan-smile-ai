import type { Phase } from "../types";

/** Pure canvas drawing for the orb (no React, no DOM), so it can be tested and reused. */
type HSL = [number, number, number];

const PALETTES: Record<Phase, HSL[]> = {
  idle:         [[214, 85, 62], [250, 75, 66], [192, 80, 56], [276, 65, 62]],
  initializing: [[214, 85, 62], [250, 75, 66], [192, 80, 56], [276, 65, 62]],
  listening:    [[190, 95, 58], [214, 95, 64], [168, 85, 54], [240, 85, 68]],
  processing:   [[256, 85, 68], [282, 80, 64], [232, 85, 66], [304, 70, 62]],
  speaking:     [[322, 90, 68], [282, 85, 68], [208, 95, 64], [190, 90, 58]],
  error:        [[8, 80, 58], [24, 85, 56], [346, 70, 54], [14, 60, 46]],
};

export interface OrbState {
  time: number;
  level: number;                 // smoothed 0..1
  amp: number;                   // current shape amplitude (smoothed)
  speed: number;                 // current motion speed (smoothed)
  colors: HSL[];                 // current colours (smoothed towards the phase palette)
}

export function createOrbState(): OrbState {
  return { time: 0, level: 0, amp: 0.05, speed: 0.4, colors: PALETTES.idle.map((c) => [...c] as HSL) };
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const hsla = (c: HSL, a: number) => `hsla(${c[0].toFixed(1)}, ${c[1].toFixed(1)}%, ${c[2].toFixed(1)}%, ${a})`;
const PHASES = [0, 1.7, 3.1, 4.6];

export interface FrameInput { phase: Phase; level: number; dt: number; reduceMotion: boolean }

/** Advances the animation state by dt seconds. */
export function stepOrb(st: OrbState, { phase, level, dt, reduceMotion }: FrameInput): void {
  const k = Math.min(1, dt * 9);                                   // smoothing factor, frame-rate independent
  const motion = reduceMotion ? 0.4 : 1;
  const active = phase === "listening" || phase === "speaking";
  const targetLevel = active ? Math.min(1, level) : 0;
  st.level = lerp(st.level, targetLevel, targetLevel > st.level ? Math.min(1, dt * 18) : k);

  let amp = 0.05 + 0.025 * Math.sin(st.time * 1.2);                // idle: gentle breathing
  let speed = 0.4;
  if (phase === "listening") { amp = 0.07 + st.level * 0.30; speed = 0.8 + st.level * 1.4; }
  else if (phase === "speaking") { amp = 0.08 + st.level * 0.28; speed = 0.9 + st.level * 1.2; }
  else if (phase === "processing") { amp = 0.09 + 0.03 * Math.sin(st.time * 3); speed = 1.5; }
  else if (phase === "initializing") { amp = 0.07; speed = 0.9; }
  else if (phase === "error") { amp = 0.035; speed = 0.25; }

  st.amp = lerp(st.amp, amp * motion, k);
  st.speed = lerp(st.speed, speed * motion, k);
  st.time += dt * st.speed;

  const palette = PALETTES[phase];
  for (let i = 0; i < 4; i++) {
    const c = st.colors[i], p = palette[i], ck = Math.min(1, dt * 3);
    let dh = p[0] - c[0];
    if (dh > 180) dh -= 360; else if (dh < -180) dh += 360;        // take the short way round the hue wheel
    c[0] = (c[0] + dh * ck + 360) % 360;
    c[1] = lerp(c[1], p[1], ck);
    c[2] = lerp(c[2], p[2], ck);
  }
}

/** Draws one frame. `w`/`h` are CSS pixels (the caller scales the context for devicePixelRatio). */
export function drawOrb(ctx: CanvasRenderingContext2D, w: number, h: number, st: OrbState, phase: Phase): void {
  const cx = w / 2, cy = h / 2;
  const base = Math.min(w, h) * 0.27;
  const breathe = phase === "idle" ? 1 + 0.03 * Math.sin(st.time * 1.2) : 1 + st.level * 0.12;
  const R = base * breathe;

  ctx.clearRect(0, 0, w, h);
  ctx.save();
  ctx.globalCompositeOperation = "source-over";
  if (phase === "error") ctx.globalAlpha = 0.5;                    // understated, not alarming

  // Soft outer glow
  const glow = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 2.5);
  glow.addColorStop(0, hsla(st.colors[0], 0.20 + st.level * 0.28));
  glow.addColorStop(0.5, hsla(st.colors[1], 0.07 + st.level * 0.10));
  glow.addColorStop(1, hsla(st.colors[1], 0));
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // Dark glassy core gives the orb volume
  const core = ctx.createRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 0.1, cx, cy, R * 1.05);
  core.addColorStop(0, "rgba(255,255,255,0.10)");
  core.addColorStop(0.55, "rgba(18,20,30,0.55)");
  core.addColorStop(1, "rgba(10,11,16,0.0)");
  ctx.fillStyle = core;
  ctx.beginPath(); ctx.arc(cx, cy, R * 1.05, 0, Math.PI * 2); ctx.fill();

  // Four organic blobs blended additively
  ctx.globalCompositeOperation = "lighter";
  const N = 90;
  for (let b = 0; b < 4; b++) {
    const ph = PHASES[b];
    const t = st.time;
    const ox = Math.cos(t * 0.45 + ph) * R * 0.10 * (1 + st.level);
    const oy = Math.sin(t * 0.38 + ph * 1.3) * R * 0.10 * (1 + st.level);
    ctx.beginPath();
    for (let i = 0; i <= N; i++) {
      const a = (i / N) * Math.PI * 2;
      const wob = 0.5 * Math.sin(3 * a + t * 1.1 + ph) + 0.2 * Math.sin(5 * a - t * 0.9 + ph * 2) + 0.12 * Math.sin(2 * a + t * 1.7 - ph);
      const r = R * (0.92 + st.amp * wob * 1.6);
      const x = cx + ox + Math.cos(a) * r, y = cy + oy + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    const g = ctx.createRadialGradient(cx + ox * 0.6, cy + oy * 0.6, R * 0.05, cx + ox, cy + oy, R * 1.15);
    g.addColorStop(0, hsla([st.colors[b][0], st.colors[b][1], st.colors[b][2] - 10], 0.52));
    g.addColorStop(0.6, hsla(st.colors[b], 0.30));
    g.addColorStop(1, hsla(st.colors[b], 0));
    ctx.fillStyle = g;
    ctx.fill();
  }

  // Specular highlight
  ctx.globalCompositeOperation = "source-over";
  const hl = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.45, 0, cx - R * 0.35, cy - R * 0.45, R * 0.55);
  hl.addColorStop(0, "rgba(255,255,255,0.20)");
  hl.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = hl;
  ctx.beginPath(); ctx.arc(cx - R * 0.35, cy - R * 0.45, R * 0.55, 0, Math.PI * 2); ctx.fill();

  // Understated "thinking" ring
  if (phase === "processing" || phase === "initializing") {
    ctx.strokeStyle = hsla(st.colors[1], 0.55);
    ctx.lineWidth = Math.max(1.5, R * 0.025);
    ctx.lineCap = "round";
    const a0 = st.time * 2.2;
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.28, a0, a0 + Math.PI * 0.7); ctx.stroke();
  }
  ctx.restore();
}
