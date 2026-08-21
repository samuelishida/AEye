"""Modelo de visão local via Ollama (backend Vulkan na Vega 8 ou CPU).

Padrão: ``aipib/LightOnOCR-2-1B:Q8_0`` — modelo OCR principal (~1GB Q8).
Alternativa: ``deepseek-ocr`` (6,7GB, mais preciso em documentos).
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.request
from typing import Any


class VLMUnavailable(Exception):
    """Ollama fora do ar ou modelo não baixado."""


class OllamaVLM:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_URL", "http://localhost:11435")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "aipib/LightOnOCR-2-1B:Q8_0")
        self._cache_until: float = 0.0
        self._cache_value: tuple[bool, bool] = (False, False)

    # ------------------------------------------------------------------ #
    def _tags_url(self) -> str:
        return f"{self.base_url}/api/tags"

    def _openai_base(self) -> str:
        # Raiz da API OpenAI-compatível do Ollama (o SDK acrescenta /chat/completions).
        return f"{self.base_url}/v1"

    # ------------------------------------------------------------------ #
    def available(self, timeout: float = 2.0) -> bool:
        """Ollama está no ar? (não garante que o modelo foi baixado). Cache de 10s."""
        return self._status(timeout)[0]

    def model_ready(self, timeout: float = 2.0) -> bool:
        """O modelo configurado já foi baixado (ollama pull)? Cache de 10s."""
        return self._status(timeout)[1]

    def _status(self, timeout: float) -> tuple[bool, bool]:
        now = time.monotonic()
        if now < self._cache_until:
            return self._cache_value
        up = False
        ready = False
        try:
            with urllib.request.urlopen(self._tags_url(), timeout=timeout) as resp:  # noqa: S310
                up = resp.status == 200
                if up:
                    data = json.loads(resp.read().decode("utf-8"))
                    ready = any(
                        t.get("name", "").split(":")[0] == self.model.split(":")[0]
                        for t in data.get("models", [])
                    )
        except Exception:  # noqa: BLE001
            up = False
        self._cache_until = now + 10.0
        self._cache_value = (up, ready)
        return self._cache_value

    # ------------------------------------------------------------------ #
    def describe(self, image_bytes: bytes, prompt: str, mime: str = "image/png") -> str:
        """Envia a imagem para o VLM local e devolve o texto gerado."""
        if not self.available():
            raise VLMUnavailable(
                "Ollama não está rodando. Inicie o Ollama (OllamaSetup.exe) e rode: "
                f"ollama pull {self.model}"
            )
        if not self.model_ready():
            raise VLMUnavailable(
                f"Modelo '{self.model}' não baixado. Rode no terminal: ollama pull {self.model}"
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise VLMUnavailable("Pacote 'openai' não instalado (pip install openai)") from exc

        b64 = base64.b64encode(image_bytes).decode("ascii")
        content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            },
            {"type": "text", "text": prompt},
        ]
        client = OpenAI(base_url=self._openai_base(), api_key="ollama", timeout=180)
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                temperature=0.1,
                max_tokens=4096,
            )
        except Exception as exc:  # noqa: BLE001 - modelo grande pode demorar; 429, etc.
            raise VLMUnavailable(f"Falha na chamada ao Ollama ({self.model}): {exc}") from exc

        text = ""
        if getattr(resp, "choices", None):
            text = getattr(resp.choices[0].message, "content", None) or ""
        return text.strip()
