"""Fakes compartilhados entre testes (clientes LLM de teste)."""
from __future__ import annotations

import json

from aeye.llm import LLMClient, LLMError


class JsonClient(LLMClient):
    """Devolve um payload JSON fixo."""

    def __init__(self, payload: dict, name: str = "fake") -> None:
        self.payload = payload
        self.name = name

    def chat(self, messages, *, json_mode=False, temperature=0.2, max_tokens=None) -> str:
        return json.dumps(self.payload)


class RecordingClient(LLMClient):
    """Como JsonClient, mas grava max_tokens de cada chamada."""

    def __init__(self, payload: dict, name: str = "recording") -> None:
        self.payload = payload
        self.name = name
        self.calls: list[dict] = []

    def chat(self, messages, *, json_mode=False, temperature=0.2, max_tokens=None) -> str:
        self.calls.append({"max_tokens": max_tokens})
        return json.dumps(self.payload)


class OfflineClient(LLMClient):
    """Sempre levanta LLMError (simula provedor offline)."""

    def __init__(self, name: str) -> None:
        self.name = name

    def chat(self, messages, *, json_mode=False, temperature=0.2, max_tokens=None) -> str:
        raise LLMError(f"{self.name} offline")
