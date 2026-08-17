"""Kill switch: segurar a tecla Esc no PC cancela a ação em andamento (Windows).

Sem dependências externas — usa GetAsyncKeyState via ctypes. Em sistemas
não-Windows o watcher é um no-op (o cancelamento continua disponível pela UI).
"""
from __future__ import annotations

import ctypes
import os
import threading
import time


def start_escape_watcher(flag: threading.Event) -> None:
    """Inicia uma thread que seta ``flag`` enquanto a tecla Esc estiver pressionada."""
    if os.name != "nt":
        return
    thread = threading.Thread(target=_poll_escape, args=(flag,), name="kill-switch", daemon=True)
    thread.start()


def _poll_escape(flag: threading.Event) -> None:
    try:
        user32 = ctypes.windll.user32
        VK_ESCAPE = 0x1B
        while True:
            if user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000:
                flag.set()
            time.sleep(0.1)
    except Exception:  # noqa: BLE001 - sem acesso à API do Windows: segue sem kill switch
        pass
