import type { Phase } from "../types";

interface Props { phase: Phase; callActive: boolean; onStart: () => void; onEnd: () => void }

const base =
  "min-w-[132px] rounded-full px-6 py-2.5 text-sm font-medium tracking-wide transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed";

/** Text-only call buttons (no phone icons). */
export function CallControls({ phase, callActive, onStart, onEnd }: Props) {
  const connecting = phase === "initializing";
  const canStart = !callActive && (phase === "idle" || phase === "error" || phase === "speaking");
  const canEnd = callActive || connecting;
  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onStart}
        disabled={!canStart}
        aria-busy={connecting}
        className={`${base} bg-white text-ink shadow-[0_0_30px_-6px_rgba(122,162,255,0.55)] focus-visible:ring-white/70 enabled:hover:bg-zinc-100 enabled:active:scale-95 disabled:opacity-40`}
      >
        {connecting ? (
          <span className="inline-flex items-center gap-2">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink/30 border-t-ink" />
            Connecting...
          </span>
        ) : (
          "Start Call"
        )}
      </button>
      <button
        type="button"
        onClick={onEnd}
        disabled={!canEnd}
        className={`${base} border border-red-400/40 bg-red-500/10 text-red-200 focus-visible:ring-red-400/60 enabled:hover:bg-red-500/20 enabled:active:scale-95 disabled:opacity-25`}
      >
        End Call
      </button>
    </div>
  );
}
