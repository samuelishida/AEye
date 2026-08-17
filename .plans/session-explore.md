# AEye accessibility improvements — exploration notes

## Scope (from user request)
Improve the browser UI (`web/index.html`, `web/style.css`, `web/app.js`) and small backend tweaks for:
- P0 #1: Web Speech API voice button beside prompt/action inputs.
- P0 #2: re-listen results via `/api/read` + stop narration.
- P0 #3: announce key state changes in voice; `aria-live` on status/approval.
- P0 #4: dynamic CTA ("Ler imagem" / "Responder").
- P0 #5: copy button per message.
- P0 #6: retry-same-image button.
- P1 #7: `.image-card:focus-visible`.
- P1 #8: human-readable approval phrasing (not raw tool+params JSON).
- P1 #9: "aumentar texto" toggle + rem units.
- P1 #10: staged progress feedback ("Lendo imagem..." → "Analisando com IA...").
- P2 #12-14: first-use onboarding overlay, persist prefs in localStorage, clear history button.

## Endpoints (confirmed from app.py)
- GET `/` -> index.html; `GET /health`; static at `/web/`.
- POST `/api/ocr` (pin opt): form file/mode/instruction/strong -> {ok,text,source,provider,warning}. 600s timeout.
- POST `/api/chat` (pin): {message} -> {text,provider,escalated}.
- POST `/api/act` (pin): two-phase WYSIWYG; approved:false returns action for approval; approved:true executes exact action.
- POST `/api/cancel` (pin): sets cancel_event.
- POST `/api/read` (pin): {text} -> tts.speak(text).

## Current frontend state (web/app.js)
- Vanilla fetch via `authedFetch(url, opts, timeoutMs)` with X-AEYE-PIN header from localStorage; 300s default / 600s OCR. On 401 prompts PIN and retries.
- `postJSON` sends JSON body + Content-Type.
- mode radiogroup: texto/manuscrito/perguntar (aria-checked toggled).
- processBtn: image -> `/api/ocr` FormData; else if instruction -> `/api/chat`. Result->history, then `speak(data.text)`. Status text only.
- actBtn -> `/api/act {command, approved:false}` -> approval modal shows raw tool+params JSON + rationale. approve calls /api/act with action. reject cancels.

## Test baseline
- pytest; 50 tests pass. fastapi.testclient.TestClient for endpoints; mock LLMClient for router/agent units.

## Standards (.agents/standards/python.md)
- Python 3.10+ (`|` union, `Annotated`). Short funcs, no deep nesting. Sequence[T] in public sigs. hmac.compare_digest for PIN. run_in_threadpool for blocking work. Refusal regex ASCII-pt variants. No bare except when caller needs cause.

## Common mistakes (.agents/common-mistakes)
- Do NOT flag: _backoff sleep; extract_json brace matching; killswitch non-Windows no-op; lazy 3rd-party imports with guards.
- DO flag: convert()/save outside try; refusal regex missing nao variants; strong-model failures only warning -> need diagnostic print; plain == for PIN; type narrowing after assignment.

## Key decisions already taken (from code, not to be re-derived)
- TTS via pyttsx3 local engine (offline). /api/read is the single speak entry point.
- Approval modal currently shows raw tool+params — must be humanized in front end.
- No existing Web Speech API integration anywhere.
