# Common mistakes to avoid in AEye reviews

## Do NOT flag as issues (pre-validated)
- `_backoff` sleeps on every error — rate-limit heuristic, not a bug.
- `extract_json` brace-matching complexity — tests cover pathological cases.
- `killswitch.py` non-Windows no-op — acceptable; UI cancel still works.
- Third-party imports instantiated lazily with availability guards — correct vs current docs.

## Do flag as issues
- convert()/save() outside try block → fold into same except.
- Refusal regex missing ASCII-portuguese variants (nao sou capaz).
- Strong-model failures only shown as warning, never logged → diagnostic print needed.
- Plain string `==` comparison for PIN → timing attack vector; use hmac.compare_digest.
- Type annotations narrowing union types incorrectly after assignment.
