"""Testes da fábrica de provedores (build_chain) e do parse de JSON."""
from __future__ import annotations

import pytest

from aeye.llm import (
    AnthropicClient,
    ClaudeCodeClient,
    GeminiClient,
    LLMError,
    OpenAICompatClient,
    build_chain,
)


def test_build_chain_sem_chaves_levanta(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    with pytest.raises(LLMError):
        build_chain("gemini,cerebras")


def test_placeholder_do_env_example_e_rejeitado(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chave ainda com o texto do .env.example não pode entrar na cadeia."""
    monkeypatch.setenv("GEMINI_API_KEY", "coloque_aqui_a_chave_gemini")
    monkeypatch.setenv("CEREBRAS_API_KEY", "coloque_aqui_a_chave_cerebras")
    with pytest.raises(LLMError, match="Nenhum provedor"):
        build_chain("gemini,cerebras")


def test_build_chain_pula_provedor_sem_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    chain = build_chain("gemini,cerebras")
    assert [n for n, _ in chain] == ["gemini"]


def test_build_chain_ordem_e_instancia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("CEREBRAS_API_KEY", "c")
    chain = build_chain("gemini,cerebras")
    names = [n for n, _ in chain]
    assert names == ["gemini", "cerebras"]
    assert isinstance(chain[0][1], GeminiClient)
    assert isinstance(chain[1][1], OpenAICompatClient)


def test_build_chain_ignora_nome_desconhecido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    chain = build_chain("gemini,nao-existe")
    assert [n for n, _ in chain] == ["gemini"]


def test_openai_compat_exige_chave(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    with pytest.raises(LLMError):
        OpenAICompatClient(name="cerebras", base_url="x", api_key_env="CEREBRAS_API_KEY")


def test_chain_pode_incluir_claude_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    chain = build_chain("gemini,claudecode")
    assert [n for n, _ in chain] == ["gemini", "claudecode"]
    assert isinstance(chain[1][1], ClaudeCodeClient)



def test_build_chain_warns_when_pulando_sem_chave(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.CaptureFixture[str]
) -> None:
    """Pular provedor sem chave deve gerar um aviso de diagnóstico."""
    import logging
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    with caplog.at_level(logging.WARNING, logger="aeye.llm"):
        chain = build_chain("gemini,cerebras")
    assert [n for n, _ in chain] == ["gemini"]
    assert any("sem chave" in r.message.lower() for r in caplog.records)
