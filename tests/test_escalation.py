"""Testes da escalada por julgamento (Inc 3): tool:"escalate" e force_strong."""
from __future__ import annotations

import pytest

from aeye.agent import ActionError, _ORCH_MAX_TOKENS, parse_command
from aeye.llm import LLMClient
from aeye.router import Router

from .conftest import JsonClient, RecordingClient


def _router(client: LLMClient) -> Router:
    return Router(chain=[(client.name, client)], backoff_base=0.0, backoff_cap=0.0)


def _click() -> dict:
    return {"tool": "click", "params": {"element_description": "OK"}, "rationale": "r"}


def _escalate() -> dict:
    return {"tool": "escalate", "params": {}, "rationale": "precisa de código", "escalate_reason": "código"}


# (a) tool:"escalate" → re-executa com o escalador
def test_escalate_reexecuta_com_escalador() -> None:
    orch = RecordingClient(_escalate(), name="minicpm")
    escal = RecordingClient(_click(), name="claudecode")
    action = parse_command(_router(orch), "faça algo", escalation_router=_router(escal))
    assert action["tool"] == "click"
    assert len(orch.calls) == 1
    assert len(escal.calls) == 1


# (b) tool:"escalate" sem escalador → ActionError
def test_escalate_sem_escalador_levanta() -> None:
    orch = JsonClient(_escalate(), name="minicpm")
    with pytest.raises(ActionError, match="modelo forte"):
        parse_command(_router(orch), "faça algo")


# (c) force_strong=True → roda direto no escalador
def test_force_strong_roda_no_escalador() -> None:
    orch = RecordingClient(_click(), name="minicpm")
    escal = RecordingClient(_click(), name="claudecode")
    action = parse_command(_router(orch), "faça algo", escalation_router=_router(escal), force_strong=True)
    assert action["tool"] == "click"
    assert len(orch.calls) == 0
    assert len(escal.calls) == 1


# (d) force_strong=True sem escalador → ActionError
def test_force_strong_sem_escalador_levanta() -> None:
    with pytest.raises(ActionError, match="Modelo forte indisponível"):
        parse_command(_router(JsonClient(_click(), name="minicpm")), "faça algo", force_strong=True)


# (e) ação normal segue intacta (sem escalar)
def test_acao_normal_nao_escala() -> None:
    orch = RecordingClient(_click(), name="minicpm")
    escal = RecordingClient(_click(), name="claudecode")
    action = parse_command(_router(orch), "clica", escalation_router=_router(escal))
    assert action["tool"] == "click"
    assert len(orch.calls) == 1
    assert len(escal.calls) == 0


# (f) escalador sinaliza escalate → ActionError claro (sem loop)
def test_escalador_escalate_levanta_sem_loop() -> None:
    orch = RecordingClient(_escalate(), name="minicpm")
    escal = RecordingClient(_escalate(), name="claudecode")
    with pytest.raises(ActionError, match="também não conseguiu resolver"):
        parse_command(_router(orch), "faça algo", escalation_router=_router(escal))


# (g) cap de tokens explícito nas chamadas json
def test_max_tokens_explicito_nas_chamadas() -> None:
    orch = RecordingClient(_click(), name="minicpm")
    parse_command(_router(orch), "clica")
    assert orch.calls == [{"max_tokens": _ORCH_MAX_TOKENS}]
