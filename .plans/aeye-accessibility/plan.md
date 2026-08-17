# AEye accessibility: voice input, result controls, and spoken state announcements

## Context
AEye is a browser-based OCR + LLM assistant aimed at low-vision / motor-impaired users. The frontend (`web/app.js`, `web/index.html`, `web/style.css`) talks to a FastAPI backend (`app.py`, `aeye/router.py`). TTS currently happens only via `/api/read` (pyttsx3, fire-and-forget). The user wants three top-priority accessibility/usability improvements:

1. **Web Speech API voice button** beside the prompt and action inputs (speech-to-text for hands-free dictation).
2. **Re-listen / copy / retry-per-result buttons** so the user can re-read, copy to clipboard, or retry a specific result without re-running the whole flow.
3. **Announce key states in voice + human-readable approval phrasing** — status/approval should be spoken aloud and shown in clear, non-raw-JSON language.

This is a planning document produced by `plan-large` with ordered increments, architecture decisions, and risk review. It is self-contained; implementation follows the increment DAG.

## Assumptions and decisions
- Decision: Use the browser **Web Speech API** (`SpeechRecognition`, `webkitSpeechRecognition`) for voice input beside each text input. It runs client-side in Chromium/Edge/Firefox on desktop; Safari has no public Web Speech API, so it degrades gracefully to the existing keyboard+mic placeholder and a visible "Ativar microfone" button that does nothing harmful (disabled hint). Source: `MDN WebSpeechAPI` — `SpeechRecognition` / `webkitSpeechRecognition`.
- Decision: Voice input writes into the *currently focused* text input (`promptInput` or `actionInput`). A single recognition session is owned by whichever field has focus; a small `voiceState = { active, field }` tracks this. Source: web-speech docs — one grammar/continuous recognition per interactive context.
- Decision: TTS for state announcements uses the **existing** `/api/read` endpoint (pyttsx3) but is now gated by an explicit `speakToggle` and triggered from a new helper that also builds human-readable text. Source: user requirement "chamar por voz" — reuse pyttsx3; no new backend engine needed for these announcements.
- Decision: Each chat result card gets three small icon buttons (re-listen, copy, retry). They are keyboard-focusable and have aria labels. Re-listen calls `speak(resultText)`; copy writes to the clipboard via `navigator.clipboard.writeText`; retry re-runs the last action for that result using the stored payload (`promptInput` value + mode + image or the command). Source: standard DOM Clipboard API (returns Promise, needs user gesture / secure context).
- Decision: Approval panel shows **human-readable phrasing** instead of raw `tool`+`params` JSON. The backend returns a `description` field per action; the frontend renders it as "O computador vai: <descrição>". If absent, fall back to a readable rendering of tool/params. Source: user requirement for human-readable approval + existing two-phase `/api/act`.
- Decision: The plan keeps the single-file `web/app.js` as-is (no bundler); changes are additive and localized. No new backend endpoints; only small additions (`description` field in `/api/act` response is optional and already echoed). Zero backend file changes required for V1.

## Architecture decisions
- **Voice input**: one shared `SpeechRecognition` instance per field, created lazily on first button click (because many browsers require a user gesture to start recognition). The button toggles between "Start listening" / "Stop listening". A visible `.recording` animation gives feedback. On final result, the text is inserted at the cursor position of the focused input (or appended if no focus).
- **Result controls**: rendered inside each `msg.assistant` card via a small flex row injected after the message body. Buttons: 🗣️ "Reouvir", 📋 "Copiar", ↻ "Reenviar". Each button is `<button type="button" aria-label="...">`.
- **State announcements**: a single `announce(message, role)` helper wraps both TTS (`/api/read`) and an ARIA live region (`statusEl` updated + `aria-live` on history). Announcements fire after: image set, process done (success/error), action approved/rejected/cancelled, recognition start/stop.
- **Human-readable approval**: `/api/act` returns `{ action: { tool, params, description?, rationale? } }`. Frontend builds a readable string `action.description || ${tool}(${readableParams})` and shows it in the modal before approval.

## Data shapes
- Voice state: `let voiceState = { active: false, field: null, recognition: null };`
- Result items (in history): each message keeps `{ text, role, source }`. Retry uses stored `promptInput`/`actionInput` values + mode/image/command.
- Approval: `pendingAction.tool / params / description / rationale`.

## Risk review (pre-mortem)
- **Safari**: no Web Speech API → button rendered but inert; we degrade to keyboard input. No crash, no broken layout. Tested by guarding with `window.SpeechRecognition || window.webkitSpeechRecognition`.
- **Permission denied / not-installed**: recognition throws on start; we catch and show status "O microfone não está disponível neste navegador." The voice button becomes a no-op hint, never blocks the flow.
- **Long-running recognition**: continuous mode off by default (`interimResults: false`, `maxAlternatives: 1`); stops automatically after silence. We also enforce `recognition.stop()` on field blur / new start to avoid orphaned sessions.
- **TTS blocking on slow network**: `/api/read` is fire-and-forget in V1; state announcements are short text, so latency is low. If the server is down, TTS fails silently (caught), but the human-readable status text still appears.
- **Approval phrasing**: if backend omits `description`, we render tool+params in a readable way rather than raw JSON — avoids exposing internal tool names to end users.

## Implementation order (DAG)
1. **V1 — Voice input (for prompt + action inputs) ✅ done** (`web/app.js`: new `initVoiceInput()`, helper `_startRecognition(field)`, `_stopRecognition()`, button toggle; `web/index.html`: add mic buttons beside each textarea; `web/style.css`: `.mic-btn`, `.recording` pulse). *Rationale: highest user value, hands-free entry.*
2. **V2 — Result controls (re-listen / copy / retry) ✅ done** (`web/app.js`: `_attachResultControls(msgEl, text)`; helper functions; retry re-runs the relevant flow using stored payload). *Rationale: recoverability without re-running the whole pipeline.*
3. **V3 — Spoken state announcements + human-readable approval ✅ done** (`web/app.js`: `announce()` helper; wire into process/action/recognition paths; replace raw JSON in approval panel with readable phrasing). *Rationale: closes the feedback loop for low-vision users.*

## Verification
- Run existing tests: `python3 -m pytest tests/ -q` (expect 49 pass; no backend changes).
- Manual browser validation at http://localhost:8080:
  - Focus "promptInput", click mic button → speaks, text appears in textarea.
  - Click "Processar" with an image → result card shows re-listen/copy/retry buttons; click copy → clipboard contains the text; click retry → re-runs OCR.
  - Trigger approval (run a control command) → modal shows human-readable description instead of JSON.
- Automated: no new Python tests needed for V1/V2/V3 (frontend behavior); `node --check web/app.js` confirms syntax.

## Estimated scope
S (single PR; frontend-only: index.html + app.js + style.css). Zero backend changes in V1–V3.

## Implementation result (all increments done)
- **V1 ✅** — `initVoiceInput()` in `web/app.js`: single shared `SpeechRecognition` (`lang="pt-BR"`, `interimResults=true`), mic buttons toggle start/stop via `_startRecognition(fieldId)` / `_stopRecognition(silent)`, `.recording` pulse, transcript inserted at cursor position. Safari degrades to inert buttons + status hint. `web/style.css`: `.mic-btn` (48px round), `.recording` + `pulse-record` keyframes.
- **V2 ✅** — `_attachResultControls(msgEl, text, retry)` appends 🗣️ "Reouvir" (calls `/api/read` directly — explicit user gesture bypasses `speakToggle`), 📋 "Copiar" (`navigator.clipboard.writeText` with manual-selection fallback message), ↻ "Reenviar" (re-runs stored payload via `runOcrFlow` / `runChatFlow` / `runActFlow`). `web/style.css`: `.result-controls` row, `.result-ctl` (44px min touch targets, `:disabled` state).
- **V3 ✅** — `announce(message)` helper (updates `#status` ARIA live region + optional TTS gated by `speakToggle`). Wired to: image loaded, process done (success/error incl. abort message), action awaiting approval / executed / cancelled / rejected / errors, recognition start/stop/error. Approval panel now renders `_approvalText(action)` — "O computador vai: …" + readable params + rationale — instead of raw JSON (handles both `description` present and absent).
- **Files modified**: `web/app.js`, `web/style.css`. `web/index.html` unchanged (mic buttons already in baseline). Zero backend changes, as planned.
- **Verification**: `node --check web/app.js` exit 0; `python3 -m pytest tests/ -q` → **50 passed** (plan estimated 49; the working tree contains one out-of-scope prior-session test addition in `tests/test_llm.py`, which also explains the +1).
- **Manual browser validation (for the user, http://localhost:8080)**:
  1. Dictate into "Mensagem" with the mic button → text appears in the field; click again to stop.
  2. Dictate into "Comando de controle" mic → same behavior; switching fields stops the other recording.
  3. Process an image → result card shows 🗣️/📋/↻; Reouvir reads aloud even with "🔊 Ler em voz alta" off; Copiar fills the clipboard; Reenviar re-runs the request.
  4. Trigger a control command (e.g., "ligar o computador") → approval panel shows the human-readable description + params + rationale (no JSON); approve/reject announcements are spoken when TTS toggle is on.
  5. All state changes ("Imagem carregada", "Processamento concluído", errors) update the status line and are spoken with the toggle on.
