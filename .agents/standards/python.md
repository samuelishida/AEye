# Python standards for AEye

## General
- Python 3.10+ (uses `|` union, `str | None`, `typing.Annotated`).
- Keep functions short; avoid deep nesting (>4 levels).
- Prefer `Sequence[T]` over `list[T]` in public signatures.
- Use `hmac.compare_digest` for secret/PIN comparison (constant-time).
- Never swallow exceptions with bare `except:` when caller needs the cause.

## FastAPI / uvicorn
- Blocking CPU work must run via `run_in_threadpool`.
- Lifespan handles are single-worker only; no multi-worker safety expected.
- Global mutable state in lifespan is acceptable for single-process dev server.

## LLM chain
- build_chain silently skips providers without keys → log a warning.
- Refusal detection must cover ASCII-portuguese variants (no tilde).
- JSON extraction: brace-matching over prose is OK but tests must cover nested braces.

## Security
- PIN comparison constant-time (hmac.compare_digest).
- No secrets in logs; warnings never injected into returned text.
- Action whitelist + kill switch are the main safety boundaries.
