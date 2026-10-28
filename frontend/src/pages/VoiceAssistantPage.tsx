import { AudioReactiveOrb } from "../components/AudioReactiveOrb";
import { CallControls } from "../components/CallControls";
import { ConversationPanel } from "../components/ConversationPanel";
import { MessageComposer } from "../components/MessageComposer";
import { useVoiceSession } from "../hooks/useVoiceSession";
import { STATUS_TEXT } from "../state/sessionMachine";
import type { Lang } from "../types";

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; text: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex rounded-full border border-white/10 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-3 py-1 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${
            value === o.value ? "bg-white/10 text-zinc-100" : "text-zinc-500 hover:text-zinc-300"
          }`}
        >
          {o.text}
        </button>
      ))}
    </div>
  );
}

export function VoiceAssistantPage() {
  const v = useVoiceSession();
  const status = v.phase === "error" && v.error ? v.error : STATUS_TEXT[v.phase];
  const composerBusy = v.phase === "processing" || v.phase === "initializing";
  const showVoiceNote = !v.supports.recognition && v.phase === "idle";

  return (
    <div className="flex h-dvh w-full flex-col overflow-hidden bg-ink font-sans text-zinc-100 lg:flex-row">
      {/* Workspace: orb and call controls */}
      <main className="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-4 bg-[radial-gradient(60%_50%_at_50%_42%,rgba(94,110,255,0.10),transparent_70%)] px-6 pb-4 pt-16 lg:gap-6 lg:pb-8">
        <header className="absolute inset-x-0 top-0 flex items-center justify-between px-5 py-4">
          <div className="leading-tight">
            <p className="text-sm font-medium tracking-wide text-zinc-200">Asnan Tower</p>
            <p className="text-xs text-zinc-500">AI Receptionist</p>
          </div>
          <div className="flex items-center gap-2">
            <Segmented<Lang>
              label="Language"
              value={v.lang}
              onChange={v.setLang}
              options={[{ value: "en", text: "EN" }, { value: "ar", text: "عربي" }]}
            />
            <Segmented<"on" | "off">
              label="Voice replies"
              value={v.voiceReplies ? "on" : "off"}
              onChange={(x) => v.setVoiceReplies(x === "on")}
              options={[{ value: "on", text: "Voice on" }, { value: "off", text: "Voice off" }]}
            />
          </div>
        </header>

        <AudioReactiveOrb phase={v.phase} getLevel={v.getLevel} onInterrupt={v.interrupt} label={`Assistant status: ${status}`} />

        <div className="flex min-h-[3.5rem] flex-col items-center gap-1 text-center" aria-live="polite">
          <p className={`text-sm tracking-wide ${v.phase === "error" ? "text-red-300" : "text-zinc-300"}`}>{status}</p>
          {v.phase === "listening" && v.interim && (
            <p dir="auto" className="max-w-[28rem] text-sm italic text-zinc-500">{v.interim}</p>
          )}
          {v.notice && v.phase !== "error" && <p className="text-xs text-zinc-500">{v.notice}</p>}
        </div>

        <CallControls phase={v.phase} callActive={v.callActive} onStart={v.startCall} onEnd={v.endCall} />

        {showVoiceNote && (
          <p className="max-w-xs text-center text-xs text-zinc-600">Voice calls need Chrome, Edge or Safari. Text chat works everywhere.</p>
        )}
      </main>

      {/* Conversation: chat history and text composer */}
      <aside className="flex h-[44dvh] min-h-0 w-full flex-col border-t border-white/5 bg-panel lg:h-auto lg:w-[420px] lg:border-l lg:border-t-0 xl:w-[460px]">
        <ConversationPanel messages={v.messages} phase={v.phase} onRetry={(t) => void v.sendText(t)} />
        <MessageComposer onSend={v.sendText} busy={composerBusy} />
      </aside>
    </div>
  );
}
