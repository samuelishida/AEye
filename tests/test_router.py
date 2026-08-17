"""Testes do roteador: cadeia de fallback, escalada e parse de JSON."""
from __future__ import annotations

import json

import pytest

from aeye.llm import LLMClient, LLMError
from aeye.router import Router, RouterExhausted, extract_json


class FakeClient(LLMClient):
    """Cliente simulado para isolar a lógica do roteador."""

    def __init__(
        self,
        name: str,
        *,
        fail: str | None = None,
        refuse: bool = False,
        empty: bool = False,
        bad_json: bool = False,
        text: str | None = None,
    ) -> None:
        self.name = name
        self.fail = fail
        self.refuse = refuse
        self.empty = empty
        self.bad_json = bad_json
        self.text = text
        self.calls = 0

    def chat(self, messages, *, json_mode=False, temperature=0.2, max_tokens=None) -> str:
        self.calls += 1
        if self.fail:
            raise LLMError(f"{self.name}: {self.fail}")
        if self.empty:
            raise LLMError(f"{self.name}: resposta vazia")
        if json_mode:
            if self.bad_json:
                return "isto não é json"
            return json.dumps({"ok": True, "provider": self.name})
        if self.refuse:
            return "Desculpe, não posso fazer isso."
        return self.text or f"resposta de {self.name}"


def make_router(*clients) -> Router:
    return Router(chain=[(c.name, c) for c in clients], backoff_base=0.0, backoff_cap=0.0)


def test_primeiro_provedor_sucesso() -> None:
    a, b = FakeClient("a"), FakeClient("b")
    r = make_router(a, b)
    text, provider, escalated = r.run([{"role": "user", "content": "oi"}])
    assert text == "resposta de a"
    assert provider == "a"
    assert escalated is False
    assert b.calls == 0


def test_fallback_quando_429() -> None:
    a = FakeClient("a", fail="429 rate limit")
    b = FakeClient("b")
    r = make_router(a, b)
    text, provider, escalated = r.run([{"role": "user", "content": "oi"}])
    assert provider == "b"
    assert escalated is True
    assert text == "resposta de b"


def test_escalada_por_recusa() -> None:
    a = FakeClient("a", refuse=True)
    b = FakeClient("b")
    r = make_router(a, b)
    _, provider, escalated = r.run([{"role": "user", "content": "oi"}])
    assert provider == "b"
    assert escalated is True


def test_recusa_ascii_portugues_escalada() -> None:
    """Refusals in ASCII Portuguese (no tilde) must escalate to the next provider."""
    ascii_refuse = FakeClient("a", text="nao sou capaz de fazer isso.")
    b = FakeClient("b")
    r = make_router(ascii_refuse, b)
    _, provider, escalated = r.run([{"role": "user", "content": "oi"}])
    assert provider == "b"
    assert escalated is True


def test_escalada_por_resposta_vazia() -> None:
    a = FakeClient("a", empty=True)
    b = FakeClient("b")
    r = make_router(a, b)
    _, provider, _ = r.run([{"role": "user", "content": "oi"}])
    assert provider == "b"


def test_todos_falham_levanta_exhausted() -> None:
    a = FakeClient("a", fail="429")
    b = FakeClient("b", fail="timeout")
    r = make_router(a, b)
    with pytest.raises(RouterExhausted):
        r.run([{"role": "user", "content": "oi"}])


def test_json_mode_retry_e_fallback() -> None:
    a = FakeClient("a", bad_json=True)  # JSON inválido -> retry -> falha -> escala
    b = FakeClient("b")
    r = make_router(a, b)
    parsed, provider, escalated = r.run([{"role": "user", "content": "x"}], json_mode=True)
    assert parsed == {"ok": True, "provider": "b"}
    assert provider == "b"
    assert escalated is True
    assert a.calls == 3  # 1 tentativa + 2 retries


def test_json_mode_sucesso_no_primeiro() -> None:
    a = FakeClient("a")
    r = make_router(a)
    parsed, provider, escalated = r.run([{"role": "user", "content": "x"}], json_mode=True)
    assert parsed == {"ok": True, "provider": "a"}
    assert escalated is False


def test_extract_json_com_cercas() -> None:
    raw = '```json\n{"a": 1}\n```'
    assert extract_json(raw) == {"a": 1}


def test_extract_json_sem_objeto() -> None:
    with pytest.raises(ValueError):
        extract_json("nada de json aqui")


def test_extract_json_lista() -> None:
    assert extract_json('texto antes ["a", {"b": 2}] depois') == ["a", {"b": 2}]


def test_extract_json_com_chaves_em_prosa_antes() -> None:
    """Prosa com chaves (ex.: "o valor {x} era...") não pode quebrar o parse."""
    raw = 'O valor {x} era inválido, mas o JSON é {"tool": "click", "params": {}}'
    assert extract_json(raw) == {"tool": "click", "params": {}}
