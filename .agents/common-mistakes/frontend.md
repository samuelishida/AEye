# Common mistakes to avoid in AEye frontend reviews

## Do flag as issues
- `classList.add("loading")` (or any state mutation) placed OUTSIDE the event
  listener callback → runs at module load, permanently breaking the UI until
  the user interacts. State mutations must be the first line INSIDE the handler.
- `classList.remove("loading")` only in `catch`, not `finally` → spinner
  persists on the success path. Always pair add/remove symmetrically with
  `disabled` toggling in `finally`.
- Missing trailing newline at end of file (POSIX).
