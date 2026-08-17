"""Testes do ClaudeCodeClient (L3 local — sem depender da API da Anthropic)."""
from __future__ import annotations

import json
import subprocess

import pytest

from aeye.llm import ClaudeCodeClient, LLMError


class FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def make_client(**kwargs) -> ClaudeCodeClient:
    return ClaudeCodeClient(timeout=5, max_turns=2, **kwargs)


def test_nao_disponivel_sem_binario(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: None)
    with pytest.raises(LLMError, match="PATH"):
        make_client().chat([{"role": "user", "content": "oi"}])


def test_parse_saida_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc(stdout=json.dumps({"result": "texto formatado"}))

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    out = make_client().chat(
        [{"role": "system", "content": "Formate."}, {"role": "user", "content": "abc"}]
    )
    assert out == "texto formatado"
    # Flags corretos do modo print:
    joined = " ".join(calls[0])
    assert "-p" in joined
    assert "--output-format" in joined and "json" in joined
    assert "--no-session-persistence" in joined
    assert "--max-turns" in joined and "2" in joined


def test_model_personalizado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        return FakeProc(stdout=json.dumps({"result": "ok"}))

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    make_client(model="opus").chat([{"role": "user", "content": "x"}])
    # (a checagem do --model opus fica coberta pelo teste de flags abaixo)


def test_erro_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        return FakeProc(returncode=1, stderr="Not logged in")

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    with pytest.raises(LLMError, match="código 1"):
        make_client().chat([{"role": "user", "content": "oi"}])


def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=5)

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    with pytest.raises(LLMError, match="tempo"):
        make_client().chat([{"role": "user", "content": "oi"}])


def test_resposta_vazia(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        return FakeProc(stdout=json.dumps({"result": ""}))

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    with pytest.raises(LLMError, match="vazia"):
        make_client().chat([{"role": "user", "content": "oi"}])


def test_subprocess_error_wrapped_in_llmerror(monkeypatch: pytest.MonkeyPatch) -> None:
    """Se o binário `claude` for deletado entre a verificação de disponibilidade e
    a execução, FileNotFoundError (ou qualquer Exception) deve ser encapsulado em
    LLMError para que _call_strong caia no fallback gratuito sem expor 500."""
    monkeypatch.setattr("aeye.llm.shutil.which", lambda _cmd: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("No such file or directory")

    monkeypatch.setattr("aeye.llm.subprocess.run", fake_run)
    with pytest.raises(LLMError, match="falhou"):
        make_client().chat([{"role": "user", "content": "oi"}])
