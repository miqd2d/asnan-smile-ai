# AI Receptionist: voice frontend

A single-page, dark, minimal voice interface for the dental-clinic AI agent: a Siri-style audio-reactive
orb in the centre, a WhatsApp-style conversation panel, a text composer, and **Start Call / End Call**.
It talks to your **existing FastAPI backend** (`/chat/start`, `/chat`, `/chat/{id}/end`). The agent, tools,
prompts and business logic are not touched.

```
frontend/               <- everything lives here (separate from src/ and src/agent/)
  src/
    pages/VoiceAssistantPage.tsx     layout (workspace + conversation panel)
    components/AudioReactiveOrb.tsx  the orb (canvas, CSS fallback)
    components/ConversationPanel.tsx chat list, auto-scroll, typing indicator
    components/MessageBubble.tsx  MessageComposer.tsx  CallControls.tsx
    hooks/useVoiceSession.ts         the whole voice lifecycle (see below)
    state/sessionMachine.ts          idle | initializing | listening | processing | speaking | error
    services/voiceService.ts         calls the existing backend
    services/speech/                 microphone meter, speech recognition, speech synthesis
    lib/orbRenderer.ts               pure orb drawing code      lib/language.ts  Arabic/English helpers
  tests/                             unit tests + end-to-end test against the real backend
```

## Run it

```bash
cd frontend
npm install
npm run dev            # http://localhost:5173   (the backend must be running on http://localhost:8000)
```

Backend on another address? Copy `.env.example` to `.env` and set `VITE_BACKEND_URL`.
The dev server forwards `/api/*` to the backend, so **no CORS change is needed in `main.py`**.
Production: `npm run build` (output in `dist/`), serve it behind the same host as the API, or set `VITE_API_BASE`
to the API URL and enable CORS on the backend.

The backend needs only the three chat routes (you already have them):

| Route | Used for |
|---|---|
| `POST /chat/start` -> `{session_id, reply}` | starts a call or text session; `reply` is the greeting |
| `POST /chat` `{session_id, message}` -> `{reply, transferred, ended}` | every spoken or typed message |
| `POST /chat/{session_id}/end` -> call log | End Call (writes the call summary) |

## How a call works

1. **Start Call**: asks for the microphone (once), opens a session, shows and speaks the greeting, then listens.
2. The caller speaks. The browser recognises it, it appears as a user message, and goes to the real agent.
3. The agent's reply appears in the chat and is spoken. When it finishes (+0.45 s, so it never hears itself) listening resumes.
4. This repeats until **End Call**, which stops the microphone, recognition and speech, closes the session on the backend,
   and resets the page. Starting another call needs no refresh.

Also handled: typed messages during a call; tapping the orb while it speaks (interrupts); silence (keeps listening,
ends the call after 3 minutes of nothing); a failed request (message + "Try again", the call recovers); the agent
ending the call or transferring to a human (transcript stays on screen, microphone released); backend restarted
(session-expired message); microphone denied or unsupported browser (clear message, text chat keeps working).

## Voice: what is real and what is a limit

- **Speech to text** uses the browser's Web Speech API. Best in **Chrome and Edge** (Chrome sends audio to Google,
  so it needs internet). Safari works partly. Firefox has no speech recognition: it falls back to text chat.
  English = `en-US`, Arabic = `ar-KW` (use the **EN / عربي** switch).
- **Text to speech** uses the browser's speech synthesis. Arabic needs an Arabic voice installed in the OS.
- **Orb while the caller speaks:** driven by the real microphone level (Web Audio `AnalyserNode`).
- **Orb while the assistant speaks:** browsers do not expose the audio of speech synthesis, so a true playback volume
  is impossible. The orb pulses on the engine's real word-boundary events (or shows a steady "speaking" level for
  voices that emit none). It is not random, but it is not volume. When the backend streams real audio later
  (Day 3 TTS), replace `services/speech/tts.ts` with an engine that plays an `<audio>` element through an
  `AnalyserNode`; nothing else changes.
- **Hands-free turn taking:** the browser ends recognition after the caller stops talking. There is no separate
  voice-activity detector, and no second voice pipeline was added.

## Tests

```bash
npm test      # state machine + language helpers always; the end-to-end test needs the backend (below)
```
The end-to-end test renders the real page, clicks Start Call, "speaks" through a fake recogniser, and checks the real
agent's replies, the receipt, End Call cleanup (microphone tracks stopped, nothing still listening), a second call,
the network-failure retry, microphone denial and Arabic. Only the browser hardware is faked. To run it:
`python tests/support/fake_backend.py 8765` (real `src/agent` code, scripted model, a COPY of the database), then `npm test`.

## Not verified here

There was no browser available while building this, so the visual layout was checked by rendering the orb to images
and by the tests above, **not by opening the page**. Real microphone behaviour, voices, and phone layouts need a
quick look in Chrome. The things to check: orb size on a phone, the Arabic voice, and echo on laptop speakers.
