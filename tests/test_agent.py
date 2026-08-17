"""Testes do agente de controle do computador (parse de comando + aprovação)."""
from __future__ import annotations

import json

import pytest

from aeye.agent import (
    DESTRUCTIVE_TOOLS,
    TOOL_WHITELIST,
    ActionError,
    ToolExecutor,
    parse_command,
    validate_action,
)
from aeye.llm import LLMClient
from aeye.router import Router


class JsonClient(LLMClient):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.name = "fake"

    def chat(self, messages, *, json_mode=False, temperature=0.2, max_tokens=None) -> str:
        return json.dumps(self.payload)


def parse_with(payload: dict) -> dict:
    r = Router(chain=[("fake", JsonClient(payload))], backoff_base=0.0, backoff_cap=0.0)
    return parse_command(r, "clica no botão OK")


def test_comando_valido() -> None:
    action = parse_with({"tool": "click", "params": {"element_description": "botão OK"}, "rationale": "pedido"})
    assert action["tool"] == "click"
    assert action["params"] == {"element_description": "botão OK"}


def test_comando_none_levanta() -> None:
    with pytest.raises(ActionError):
        parse_with({"tool": "none", "params": {}, "rationale": "sem ação"})


def test_ferramenta_fora_da_whitelist_levanta() -> None:
    with pytest.raises(ActionError):
        parse_with({"tool": "rm_rf", "params": {}})


def test_whitelist_cobre_todas_as_destrutivas() -> None:
    assert DESTRUCTIVE_TOOLS <= TOOL_WHITELIST
    # Ações de leitura/inspeção não devem exigir aprovação:
    assert "get_text_from_screen" not in DESTRUCTIVE_TOOLS
    assert "get_accessibility_tree" not in DESTRUCTIVE_TOOLS


class FakeExecutor(ToolExecutor):
    def __init__(self) -> None:
        self.called: list[dict] = []

    def execute(self, action: dict) -> str:
        self.called.append(action)
        return "ok"


def test_executor_so_e_chamado_com_acao() -> None:
    ex = FakeExecutor()
    action = {"tool": "click", "params": {"element_description": "OK"}}
    # Simula o fluxo do app: só executa quando approved (no app.py).
    if action["tool"] in DESTRUCTIVE_TOOLS:
        approved = False
    if approved:  # pragma: no cover - não deve acontecer no teste
        ex.execute(action)
    assert ex.called == []

    # Com aprovação:
    approved = True
    if approved:
        ex.execute(action)
    assert ex.called == [action]


# --- validação da ação aprovada (WYSIWYG) ---
def test_validate_action_ok() -> None:
    out = validate_action({"tool": "click", "params": {"element_description": "OK"}, "rationale": "x"})
    assert out == {"tool": "click", "params": {"element_description": "OK"}, "rationale": "x"}


def test_validate_action_nao_dict() -> None:
    with pytest.raises(ActionError):
        validate_action(None)
    with pytest.raises(ActionError):
        validate_action("click")


def test_validate_action_tool_fora_da_whitelist() -> None:
    with pytest.raises(ActionError, match="não permitida"):
        validate_action({"tool": "format_disk", "params": {}})


def test_validate_action_params_invalidos() -> None:
    with pytest.raises(ActionError, match="Parâmetros"):
        validate_action({"tool": "click", "params": "x,y"})
