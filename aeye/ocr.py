"""OCR local com RapidOCR (CPU, gratuito, rápido em texto impresso/screenshots)."""
from __future__ import annotations

import io
import re
import threading
from typing import Any

import numpy as np
from PIL import Image


class OCRUnavailable(Exception):
    """RapidOCR não pôde ser carregado (instale rapidocr-onnxruntime)."""


_engine: Any = None
_engine_lock = threading.Lock()


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        with _engine_lock:  # evita construção dupla em threads concorrentes
            if _engine is None:
                try:
                    from rapidocr_onnxruntime import RapidOCR

                    _engine = RapidOCR()
                except Exception as exc:  # noqa: BLE001
                    raise OCRUnavailable(
                        f"RapidOCR indisponível: {exc}. Instale com: pip install rapidocr-onnxruntime"
                    ) from exc
    return _engine


def _prepare(img: bytes | bytearray | str | Image.Image) -> Any:
    if isinstance(img, (bytes, bytearray)):
        return np.array(Image.open(io.BytesIO(bytes(img))).convert("RGB"))
    if isinstance(img, Image.Image):
        return np.array(img.convert("RGB"))
    return img  # caminho de arquivo


def extract_text(img: bytes | bytearray | str | Image.Image) -> str:
    """Extrai o texto da imagem. Devolve '' se nada for detectado."""
    engine = _get_engine()
    result, _ = engine(_prepare(img))
    if not result:
        return ""
    return "\n".join(str(line[1]) for line in result)


def needs_vlm(text: str) -> bool:
    """Heurística: pouco/nenhum texto detectado -> provável manuscrito/imagem complexa.

    Nesse caso a camada L1 (Ollama + LightOnOCR) deve assumir.
    """
    stripped = re.sub(r"\s+", "", text or "")
    if not stripped:
        return True
    if len(stripped) < 8:
        return True
    # Só símbolos/pontuação não contam como texto útil.
    if re.fullmatch(r"[\W_]+", stripped):
        return True
    return False
