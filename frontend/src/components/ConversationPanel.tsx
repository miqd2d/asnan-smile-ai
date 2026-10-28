import { useLayoutEffect, useRef, useState } from "react";
import type { Message, Phase } from "../types";
import { MessageBubble } from "./MessageBubble";

interface Props { messages: Message[]; phase: Phase; onRetry: (text: string) => void }

/** Chat history. Sticks to the newest message, but stops following if the user scrolls up to read. */
export function ConversationPanel({ messages, phase, onRetry }: Props) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const stick = useRef(true);
  const [away, setAway] = useState(false);
  const thinking = phase === "processing";

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stick.current = near;
    setAway(!near);
  };

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (stick.current) el.scrollTop = el.scrollHeight;
    else setAway(true);
  }, [messages.length, thinking]);

  const jump = () => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
    stick.current = true;
    setAway(false);
  };

  return (
    <div className="relative min-h-0 flex-1">
      <div
        ref={scroller}
        onScroll={onScroll}
        className="h-full space-y-2 overflow-y-auto scroll-smooth px-4 py-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {messages.length === 0 && !thinking && (
          <p className="flex h-full items-center justify-center text-center text-sm text-zinc-600">
            Your conversation will appear here.
          </p>
        )}
        {messages.map((m) => <MessageBubble key={m.id} message={m} onRetry={onRetry} />)}
        {thinking && (
          <div className="flex justify-start animate-fadeUp" aria-label="The assistant is thinking">
            <div className="flex gap-1 rounded-2xl rounded-bl-md bg-bubble px-4 py-3">
              {[0, 1, 2].map((i) => (
                <span key={i} className="h-1.5 w-1.5 animate-dot rounded-full bg-zinc-400" style={{ animationDelay: `${i * 0.16}s` }} />
              ))}
            </div>
          </div>
        )}
      </div>
      {away && (
        <button
          type="button"
          onClick={jump}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-white/10 bg-panel/95 px-3 py-1 text-xs text-zinc-300 shadow-lg backdrop-blur transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        >
          Latest messages
        </button>
      )}
    </div>
  );
}
