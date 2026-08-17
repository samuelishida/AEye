"""Watcher de clipboard: detecta capturas de tela (PrtScn / Win+Shift+S).

Usa a tecla nativa de screenshot do Windows — sem admin, sem lib de hotkey.
Deduplicação por hash para não reprocessar a mesma imagem.
"""
from __future__ import annotations

import hashlib
import io
import threading
from collections import deque
from typing import Callable


class ClipboardWatcher:
    def __init__(self, on_image: Callable[[bytes, str], None], poll_seconds: float = 0.5) -> None:
        self.on_image = on_image  # callable(image_bytes: bytes, sha256: str)
        self.poll_seconds = poll_seconds
        self._seen: deque[str] = deque(maxlen=50)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="clipboard-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        try:
            from PIL import ImageGrab
        except ImportError:  # pragma: no cover
            return

        while not self._stop.is_set():
            try:
                img = ImageGrab.grabclipboard()
                if img is not None and hasattr(img, "save"):
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    data = buf.getvalue()
                    digest = hashlib.sha256(data).hexdigest()
                    if digest not in self._seen:
                        self._seen.append(digest)
                        self.on_image(data, digest)
            except Exception:  # noqa: BLE001 - clipboard pode estar bloqueado; ignora
                pass
            self._stop.wait(self.poll_seconds)
