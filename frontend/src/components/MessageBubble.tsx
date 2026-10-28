import type { Message } from "../types";

const time = (ts: number) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

interface Props { message: Message; onRetry?: (text: string) => void }

/** One chat message. `dir="auto"` makes Arabic lines flow right-to-left and English lines left-to-right. */
export function MessageBubble({ message: m, onRetry }: Props) {
  if (m.role === "system") {
    return (
      <div className="animate-fadeUp py-1 text-center text-xs text-zinc-500" role="status">
        <span dir="auto">{m.text}</span>
        {m.retryText && onRetry && (
          <button
            type="button"
            onClick={() => onRetry(m.retryText!)}
            className="ml-2 rounded-full border border-white/10 px-2.5 py-0.5 text-zinc-300 transition hover:bg-white/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
          >
            Try again
          </button>
        )}
      </div>
    );
  }
  const mine = m.role === "user";
  return (
    <div className={`flex animate-fadeUp ${mine ? "justify-end" : "justify-start"}`} data-role={m.role}>
      <div
        className={`max-w-[86%] rounded-2xl px-3.5 py-2 text-[15px] leading-relaxed shadow-sm ${
          mine ? "rounded-br-md bg-[#2a4a8f] text-white" : "rounded-bl-md bg-bubble text-zinc-100"
        }`}
      >
        {m.text.split("\n").map((line, i) => (
          <p key={i} dir="auto" className="whitespace-pre-wrap break-words">{line}</p>
        ))}
        <time className="mt-1 block text-right text-[10px] tabular-nums opacity-50" dateTime={new Date(m.ts).toISOString()}>
          {time(m.ts)}
        </time>
      </div>
    </div>
  );
}
