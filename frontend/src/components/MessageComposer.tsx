import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

interface Props {
  /** Resolves true when the message was accepted (the box is then cleared). */
  onSend: (text: string) => Promise<boolean>;
  busy: boolean;
}

/** Text fallback. Enter sends, Shift+Enter adds a new line. Works without a microphone. */
export function MessageComposer({ onSend, busy }: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [text]);

  const submit = async () => {
    const value = text.trim();
    if (!value || busy) return;
    if (await onSend(value)) setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  const canSend = text.trim().length > 0 && !busy;
  return (
    <div className="border-t border-white/5 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
      <div className="flex items-end gap-2 rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-2 transition focus-within:border-accent/50">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          dir="auto"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a message..."
          aria-label="Type a message"
          className="max-h-[120px] min-h-[24px] flex-1 resize-none bg-transparent text-[15px] leading-6 text-zinc-100 outline-none placeholder:text-zinc-600"
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={!canSend}
          className="rounded-xl bg-accent px-3.5 py-1.5 text-sm font-medium text-ink transition enabled:hover:brightness-110 enabled:active:scale-95 disabled:cursor-not-allowed disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
        >
          Send
        </button>
      </div>
    </div>
  );
}
