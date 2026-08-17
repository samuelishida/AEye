"""Testes do contrato de _call_strong (L3 — Claude Code local / Anthropic / fallback).

Foca na lógica de *orquestração* do modelo forte: a caller distingue "modelo
forte funcionou" de "caiu no fallback gratuito" pelo provider e pela ausência/
presença de strong_warning.
"""
from __future__ import annotations

import pytest


def test_strong_claude_code_sucesso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Code disponível + sucesso → warning=None, provider=claude_code."""
    import app as appmod

    class FakeCC:
        available = staticmethod(lambda: True)

        def chat(self, messages, **kw):
            return "claudinho"

    class FakeAnth:
        name = "anthropic"
        def __init__(self, *a, **k): raise RuntimeError("não deve ser chamado")
        def chat(self, messages, **kw): raise RuntimeError("não deve ser chamado")

    monkeypatch.setattr(appmod, "_call_llm", lambda m: ("fallback", "free", True))  # não será chamado
    monkeypatch.setattr("aeye.llm.ClaudeCodeClient", FakeCC)
    monkeypatch.setattr("aeye.llm.AnthropicClient", FakeAnth)

    from app import _call_strong

    text, provider, warning = _call_strong([{"role": "user", "content": "oi"}])
    assert warning is None            # forte funcionou → aviso inexistente
    assert provider == "claude_code"
    assert text == "claudinho"


def test_strong_fallback_quando_claude_indisponivel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Code não instalado → cai no fallback gratuito com warning."""
    import app as appmod

    class FakeCC:
        available = staticmethod(lambda: False)
        def chat(self, messages, **kw): raise RuntimeError("não deve ser chamado")

    monkeypatch.setattr("aeye.llm.ClaudeCodeClient", FakeCC)
    call_llm_calls = {"n": 0}

    def fake_call_llm(messages):
        call_llm_calls["n"] += 1
        return "fallback-text", "cerebras", True

    monkeypatch.setattr(appmod, "_call_llm", fake_call_llm)
    # AnthropicClient não deve ser construído se a chave estiver ausente
    def require_no_anthropic_init():
        raise AssertionError("AnthropicClient() foi instanciado sem chave")
    import aeye.llm as llmmod

    orig_init = llmmod.AnthropicClient.__init__
    llmmod.AnthropicClient.__init__ = lambda self, *a, **k: require_no_anthropic_init()

    from app import _call_strong

    text, provider, warning = _call_strong([{"role": "user", "content": "oi"}])
    assert warning is not None and "indisponível" in warning.lower()
    assert provider == "cerebras"
    assert text == "fallback-text"
    assert call_llm_calls["n"] == 1

    # restaura
    llmmod.AnthropicClient.__init__ = orig_init


def test_strong_anthropico_sobe_quando_ha_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Claude Code indisponível + ANTHROPIC_API_KEY → usa Anthropic (warning=None)."""
    import app as appmod

    class FakeCC:
        available = staticmethod(lambda: False)
        def chat(self, messages, **kw): raise RuntimeError("não chamado")

    monkeypatch.setattr("aeye.llm.ClaudeCodeClient", FakeCC)

    captured = {"msgs": None}

    class FakeAnth:
        name = "anthropic"
        def __init__(self, api_key=None, model=None):
            captured["msgs"] = api_key
        def chat(self, messages, **kw):
            return "anth-text"

    monkeypatch.setattr("aeye.llm.AnthropicClient", FakeAnth)
    # chave presente no env para que a construção não levante LLMError
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")

    from app import _call_strong

    text, provider, warning = _call_strong([{"role": "user", "content": "oi"}])
    assert warning is None            # forte (Anthropic) funcionou → aviso inexistente
    assert provider == "anthropic"
    assert text == "anth-text"
    # _call_strong não repassa a chave: AnthropicClient() lê ANTHROPIC_API_KEY
    # internamente do env; FakeAnth recebe None no positional (comportamento real).
    assert captured["msgs"] is None
