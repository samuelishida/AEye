"""Smoke test do servidor FastAPI (sem chaves reais, tudo mockado por ausência)."""
from __future__ import annotations

import logging
import os

import pytest


@pytest.fixture(scope="module")
def client():
    # Ambiente limpo: sem chaves -> router=None; watcher/MCP/PIN desligados.
    # Importante: neutraliza o load_dotenv() do app para que um .env real da
    # máquina de dev não vaze para os testes.
    import dotenv

    dotenv.load_dotenv = lambda *a, **k: None

    for k in (
        "GEMINI_API_KEY",
        "CEREBRAS_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "AEYE_PIN",
    ):
        os.environ.pop(k, None)
    os.environ["AI_FALLBACK_CHAIN"] = "gemini,cerebras"
    os.environ["AEYE_CLIPBOARD"] = "0"
    os.environ["AEYE_MCP"] = "0"

    from fastapi.testclient import TestClient

    from app import app

    with TestClient(app) as c:
        yield c


def test_health(client) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["chain"] == []  # sem chaves -> nenhum provedor


def test_index_serve_ui(client) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "AEye" in r.text


def test_chat_sem_chaves_503(client) -> None:
    r = client.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 503


def test_act_sem_mcp_503(client) -> None:
    r = client.post("/api/act", json={"command": "abre o word", "approved": False})
    assert r.status_code == 503


def test_clipboard_poll_invalid_fallback(monkeypatch) -> None:
      """AEYE_CLIPBOARD_POLL inválido cai no default 0.5; válido é respeitado."""
      from app import _clipboard_poll_seconds

      monkeypatch.setenv("AEYE_CLIPBOARD_POLL", "not-a-number")
      assert _clipboard_poll_seconds() == 0.5
      monkeypatch.setenv("AEYE_CLIPBOARD_POLL", "1.5")
      assert _clipboard_poll_seconds() == 1.5


def test_clipboard_poll_zero_and_negative(monkeypatch) -> None:
      """0/negativo caem no default 0.5 (evita busy-loop do watcher)."""
      from app import _clipboard_poll_seconds

      monkeypatch.setenv("AEYE_CLIPBOARD_POLL", "0")
      assert _clipboard_poll_seconds() == 0.5
      monkeypatch.setenv("AEYE_CLIPBOARD_POLL", "-2")
      assert _clipboard_poll_seconds() == 0.5
      monkeypatch.setenv("AEYE_CLIPBOARD_POLL", "0.1")
      assert _clipboard_poll_seconds() == 0.1


def test_read_status_shape(client, monkeypatch) -> None:
    """GET /api/read/status devolve {speaking, current} (TTS mockado)."""

    class _FakeTTS:
        def status(self):
            return ("texto falando", True)

    monkeypatch.setattr("app.tts", _FakeTTS())
    r = client.get("/api/read/status")
    assert r.status_code == 200
    assert r.json() == {"speaking": True, "current": "texto falando"}


def test_request_id_filter_injects_field() -> None:
    """O _RequestIdFilter anexa o request_id atual ao LogRecord."""
    from app import _RequestIdFilter, _request_id_var

    _request_id_var.set("abc123")
    rec = logging.LogRecord("aeye.test", logging.INFO, __file__, 1, "hi", None, None)
    assert _RequestIdFilter().filter(rec) is True
    assert rec.request_id == "abc123"


# --------------------------------------------------------------------------- #
# Regressões do code review
# --------------------------------------------------------------------------- #
def test_chat_com_router_fake_nao_quebra_kwargs(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regressão: router.run tem parâmetros keyword-only; o endpoint não pode
    passar o dict de kwargs posicionalmente (dava TypeError -> 500)."""
    import app as appmod

    class StrictRouter:
        def run(self, messages, *, temperature=0.2, max_tokens=None):  # keyword-only
            assert temperature == 0.3
            assert max_tokens == 2048
            return "resposta fake", "fake", False

    monkeypatch.setattr(appmod, "router", StrictRouter())
    r = client.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 200
    assert r.json()["text"] == "resposta fake"


def test_pin_obrigatorio_quando_configurado(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """Com AEYE_PIN no .env, requisições sem o header são rejeitadas (401)."""
    import app as appmod

    monkeypatch.setenv("AEYE_PIN", "1234")

    # Sem header -> 401 (antes de qualquer outra validação)
    r = client.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 401

    # Header errado -> 401
    r = client.post("/api/chat", json={"message": "oi"}, headers={"X-AEYE-PIN": "0000"})
    assert r.status_code == 401

    # Header certo -> passa (aqui: 503 por falta de chaves, não 401)
    r = client.post("/api/chat", json={"message": "oi"}, headers={"X-AEYE-PIN": "1234"})
    assert r.status_code == 503

    monkeypatch.delenv("AEYE_PIN", raising=False)


def test_pin_ignorado_sem_configuracao(client) -> None:
    """Sem AEYE_PIN configurado, o header não é exigido."""
    r = client.post("/api/chat", json={"message": "oi"})
    assert r.status_code == 503  # falta de chaves, e não 401
