"""Leitura em voz alta no PC (opcional, offline, via Windows SAPI/pyttsx3)."""
from __future__ import annotations

import threading
from typing import Any


class TTSEngine:
    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = threading.Lock()

    def _get(self) -> Any:
        if self._engine is None:
            import pyttsx3

            self._engine = pyttsx3.init()
        return self._engine

    def speak(self, text: str) -> None:
        """Fala o texto em thread separada (não bloqueia a UI)."""
        if not text:
            return
        threading.Thread(target=self._speak_sync, args=(text,), daemon=True).start()

    def _speak_sync(self, text: str) -> None:
        try:
            with self._lock:
                engine = self._get()
                engine.say(text)
                engine.runAndWait()
        except Exception:  # noqa: BLE001 - TTS é opcional; nunca derruba o app
            pass
