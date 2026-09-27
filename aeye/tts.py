"""Leitura em voz alta no PC (opcional, offline, via Windows SAPI/pyttsx3)."""
from __future__ import annotations

import threading
from typing import Any


class TTSEngine:
    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = threading.Lock()
        self._current: str = ""
        self._speaking: bool = False
        self._generation: int = 0

    def _get(self) -> Any:
        if self._engine is None:
            import pyttsx3

            self._engine = pyttsx3.init()
        return self._engine

    def speak(self, text: str) -> None:
        """Fala o texto em thread separada (não bloqueia a UI)."""
        if not text:
            return
        with self._lock:
            self._current = text
            self._speaking = True
            generation = self._generation + 1
            self._generation = generation
        threading.Thread(
            target=self._speak_sync, args=(text, generation), daemon=True
        ).start()

    def _speak_sync(self, text: str, generation: int) -> None:
        try:
            with self._lock:
                engine = self._get()
                engine.say(text)
                engine.runAndWait()
        except Exception:  # noqa: BLE001 - TTS é opcional; nunca derruba o app
            pass
        finally:
            with self._lock:
                # Só limpa se nenhuma fala nova começou no meio (evita
                # marcar como "não falando" enquanto a próxima ainda roda).
                if generation == self._generation:
                    self._speaking = False

    def status(self) -> tuple[str, bool]:
        """Devolve (texto falando, se está falando) de forma thread-safe."""
        with self._lock:
            return self._current, self._speaking
