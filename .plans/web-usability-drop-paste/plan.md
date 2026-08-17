# Web usability: drag-and-drop photos, Ctrl+V clipboard paste, accessibility polish

## Context
AEye's mobile-first web UI currently requires tapping "Escolher imagem / câmera" to pick a photo. Users asked for: (a) dragging and dropping photos onto the page, (b) reading images pasted from the clipboard via Ctrl+V/Cmd+V, and (c) general accessibility/usability polish so the tool is genuinely usable by people with motor or vision impairments. The backend already exposes `/api/ocr` accepting a multipart `file`, so no new backend endpoints are needed — only frontend wiring + small a11y tweaks.

## Assumptions and decisions
- Decision: Add drag-and-drop to `#previewWrap` / the image card AND clipboard paste on the whole document (with an allowed MIME filter). Source: user request; existing `/api/ocr` accepts multipart files, no backend change needed. Default — confirmed by this plan.
- Decision: Add real Ctrl+V / Cmd+V support via a `paste` event listener on the image card that reads images from `event.clipboardData`. This is the standard browser mechanism for paste (no permission prompt, no clipboard stealing — only `image/*` items are read) and directly implements the user's "leitura do buffer ctrl v" request. Source: native browser paste semantics; used everywhere users expect Ctrl+V to work.
- Decision: Keep a visible "Colar da área de transferência" button as a supplementary mobile/touch entry point (no keyboard shortcut on touch devices); it triggers a hidden `<input type="file" accept="image/*">` click (cross-browser safe). Source: mobile/keyboard-less usage; fires only on explicit user action.
- Decision: Keep image-card focus ring for keyboard navigation and add aria labels to the segmented controls and status region. Source: `.agents/standards/python.md` accessibility ethos (mobile-first, big touch targets); mirrors existing patterns.

## Files to touch

### web/app.js
- What changes: add drag-and-drop file pick on the image card, real Ctrl+V / Cmd+V paste via `paste` event (reads only `image/*` items), and a supplementary "Colar da área de transferência" button that triggers a hidden `<input type="file" accept="image/*">`. Add keyboard focus management for segmented controls.
- Function(s):
  - `function setImage(file)`: centralize preview + file assignment (used by change/drop/paste). Validates MIME; rejects non-images with status message.
  - `function initDragDrop()`: attach dragover/dragenter/dragleave/drop on `.card` image section; prevent defaults, add active class, call `setImage(e.dataTransfer.files[0])`.
  - `function initPasteButton()`: wire "pasteBtn" button → hidden input click on pointerdown/keydown(Enter); read file via input change (same path as existing imageInput handler). Cross-browser safe for touch/mobile.
  - `function initPasteHandler()`: attach `paste` listener on the image card; from `event.clipboardData.items`, iterate and accept only items whose `type.startsWith('image/')`; call `setImage(item.getAsFile())`. Prevent default so the page doesn't insert an `<img>` tag into the document.
- Data shapes: same `selectedImage: File | null`; preview URL via FileReader.readAsDataURL (unchanged).
- Integration points: reuses existing `#imageInput`, `#preview`, `#clearImage`, `#processBtn`. No new backend calls.
- Error paths: non-image clipboard items skipped silently; paste of text-only content yields no file and status "Nenhuma imagem encontrada na área de transferência." Large/HEIC files handled by existing `_normalize_image` + size guard (413).

### web/index.html
- What changes: add a "Colar da área de transferência" ghost button next to "Remover imagem"; add `aria-label`/`title` hints for the segmented buttons and image card (drop zone). Add `tabindex="0"` to the image card so it is keyboard-focusable.
- Function(s): none (pure markup + attributes).
- Data shapes: n/a.
- Integration points: wires into existing `.card` image section.

### web/style.css
- What changes: add `.drop-active` visual cue for drag-over; ensure focus-visible rings on buttons/inputs/segmented; add a small `.sr-only` utility (screen-reader only text) used by paste hints. Keep touch-target sizes ≥ 48px/52px.

### app.py
- No changes. The existing `/api/ocr` endpoint already accepts multipart `file`; the frontend continues posting FormData with `file`. Confirmed via grep: `_normalize_image(data)` + `_handle_clipboard_image` path unchanged.

## Edge cases
- Paste of a non-image (e.g., text) → reject in `setImage`, show status "A área de transferência não contém imagem."
- Drag-and-drop of multiple files → use only the first file (existing single-file contract).
- Drop while an image is already selected → replace it (clear preview, set new file).
- User pastes a large GIF/HEIC → handled by existing `_normalize_image` + size guard (413).
- Keyboard-only user: segmented controls still work via arrow keys (role="radiogroup" + native radio behavior); paste button reachable via Tab.
- Mobile no-mouse: drag-drop irrelevant; paste button remains accessible and the camera capture stays.

## Verification
- Run: `python3 -m py_compile web/app.js web/style.css` is not applicable for JS/CSS (no compiler). Instead validate by opening `web/index.html` in browser devtools and testing: (1) drag a photo onto the image card → preview appears + file set, (2) click "Colar da área de transferência" → picks from clipboard/prompt, (3) process works end-to-end with dropped/pasted image. Run existing tests: `python3 -m pytest tests/ -q` (49 pass expected).
- Tests to add/update: none in Python; frontend behavior validated manually via browser. Could add a tiny unit-free smoke check that the HTML contains the paste button + drop-zone ARIA attributes.
- Manual: open http://localhost:8080 on desktop, drag image, click process → verify result appears.

## Standards / common-mistakes referenced
- `.agents/standards/python.md` — accessibility ethos (big touch targets, mobile-first); FastAPI endpoints unchanged so existing `run_in_threadpool` + `hmac.compare_digest` PIN rules still apply.
- `.agents/common-mistakes/python.md` — no backend change needed; avoid swallowing exceptions in paste handling (use specific rejection message).

## Estimated scope
S (single PR, frontend only: index.html + app.js + style.css; zero backend changes).

## Open questions (CONSIDER from review)
- The supplementary mobile/touch paste button keeps the input-based pick as cross-browser default; optionally also attempt `navigator.clipboard.readBinary()` when available for a true desktop Ctrl+V. Plan implements BOTH: desktop paste via native `paste` event, and the button uses the input fallback (mobile-safe).
- Auto-focus management after successful image set: plan moves focus to "Processar" so keyboard users can fire with Enter; this is implemented as an optional, non-jarring transition.

## Implementation status — DONE
All changes applied in one frontend-only commit (no backend files touched):
- `web/index.html`: added `.image-card` drop zone (`tabindex`, aria-label), "Colar da área de transferência" ghost button next to "Remover imagem", aria-labels on segmented radio buttons.
- `web/app.js`: centralized `setImage(file)`; `initDragDrop()` (dragenter/over/dragleave/drop, first file); `initPasteButton()` (hidden `<input>` for mobile/touch); `initPasteHandler()` (native `paste` event reading only `image/*` from `event.clipboardData`, `preventDefault`).
- `web/style.css`: `.sr-only`, `.drop-active`, focus-visible rings on interactive elements; footer rule restored after a post-review patch accidentally dropped it.

Verification: `python3 -m pytest tests/ -q` = 49 passed; `node --check web/app.js` = OK. Manual verification (browser): drag photo onto card -> preview + file set; Ctrl+V on card -> pastes image; "Colar" button opens file picker; Processar fires the existing `/api/ocr` multipart endpoint unchanged.

## Implementation notes applied during review
- `.sr-only` utility must use `position:absolute; left:-9999px; clip:rect(0,0,0,0)` (visually hidden but accessible to screen readers).
- If a document-level paste handler is added later, prevent default there too so pasting elsewhere does not insert an `<img>` tag into the page.
