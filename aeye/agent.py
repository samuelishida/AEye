"""Agente de controle do computador por voz/texto.

Fluxo: comando ("clica no botão X", "abre o Word e digita olá") -> LLM converte
para JSON {tool, params} -> execução via MCP (computer-control-mcp-server do
wshobson/agents, que usa a árvore de acessibilidade/UI Automation do Windows).

Segurança: toda ação só é executada após aprovação explícita na UI; há
whitelist de ferramentas e kill switch (segurar Esc cancela a ação em curso).
"""
from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from .llm import LLMError
from .router import Router, RouterExhausted

# Cap de tokens do caminho JSON do orquestrador/escalada (thinking models 1B
# precisam de orçamento para o bloco thinking; _run usa max_tokens or 1024).
_ORCH_MAX_TOKENS = int(os.getenv("AEYE_ORCH_MAX_TOKENS", "2048"))

# Ferramentas expostas pelo computer-control-mcp-server (wshobson/agents).
TOOL_WHITELIST = {
    "click",
    "double_click",
    "right_click",
    "drag",
    "type_text",
    "press_key",
    "press_key_combination",
    "scroll",
    "open",
    "close_app",
    "focus_window",
    "get_text_from_screen",
    "get_accessibility_tree",
    "get_element_at_cursor",
    "get_active_window_info",
    "list_open_applications",
    "get_clipboard_content",
    "set_clipboard_content",
    "move_window",
    "resize_window",
    "toggle_maximize_window",
    "minimize_window",
    "restore_window",
}

# Ações consideradas destrutivas: exigem aprovação SEMPRE.
DESTRUCTIVE_TOOLS = {
    "click",
    "double_click",
    "right_click",
    "drag",
    "type_text",
    "press_key",
    "press_key_combination",
    "scroll",
    "open",
    "close_app",
    "set_clipboard_content",
    "move_window",
    "resize_window",
    "toggle_maximize_window",
    "minimize_window",
    "restore_window",
}


class ActionError(Exception):
    """Comando não pôde ser convertido em ação válida."""


def validate_action(action: Any) -> dict[str, Any]:
    """Valida uma ação vinda da UI na aprovação (WYSIWYG).

    Garante que só ferramentas da whitelist com parâmetros em formato de dicionário
    cheguem ao executor. Levanta ActionError se a ação for inválida/perigosa.
    """
    if not isinstance(action, dict):
        raise ActionError("Ação aprovada ausente ou inválida.")
    tool = str(action.get("tool", "")).strip()
    if tool not in TOOL_WHITELIST:
        raise ActionError(f"Ferramenta não permitida: {tool}")
    params = action.get("params")
    if not isinstance(params, dict):
        raise ActionError("Parâmetros da ação inválidos.")
    return {
        "tool": tool,
        "params": params,
        "rationale": str(action.get("rationale", "")),
    }


def _system_prompt() -> str:
    tools = ", ".join(sorted(TOOL_WHITELIST))
    return (
        "Você converte comandos de voz/texto do usuário em ações de computador. "
        "Responda APENAS com JSON válido no formato: "
        '{"tool": "<nome_da_ferramenta>", "params": {<parâmetros>}, "rationale": "<curto motivo>"}. '
        f"Ferramentas permitidas: {tools}. "
        "Exemplos: "
        '{"tool": "click", "params": {"element_description": "botão OK"}}, '
        '{"tool": "type_text", "params": {"text": "olá mundo"}}, '
        '{"tool": "open", "params": {"app": "notepad"}}. '
        "Use o contexto da tela (árvore de acessibilidade) quando fornecido para "
        "descrever o elemento alvo (element_description, x, y quando houver). "
        "Se o comando não pedir nenhuma ação de computador, use "
        '{"tool": "none", "params": {}, "rationale": "..."}. '
        "Se você NÃO consegue executar com as ferramentas disponíveis, se o usuário "
        'pedir explicitamente o modelo forte, ou se a tarefa exigir escrever ou '
        'executar código além da sua capacidade, responda exatamente: '
        '{"tool": "escalate", "params": {}, "rationale": "<motivo>", '
        '"escalate_reason": "<por que é necessário escalar>"}.'
    )


def _normalize_action(action: Any) -> dict[str, Any]:
    """Valida e normaliza uma ação {tool, params, rationale} (fonte única)."""
    if not isinstance(action, dict):
        raise ActionError("Resposta do agente não é um objeto JSON válido")

    tool = str(action.get("tool", "")).strip().lower()
    if tool == "none":
        raise ActionError("O comando não pediu nenhuma ação de computador.")
    if tool not in TOOL_WHITELIST:
        raise ActionError(f"Ferramenta desconhecida ou não permitida: {tool}")

    params = action.get("params")
    if not isinstance(params, dict):
        raise ActionError("Parâmetros da ação inválidos.")
    return {"tool": tool, "params": params, "rationale": str(action.get("rationale", ""))}


def _is_escalation(action: Any) -> bool:
    return isinstance(action, dict) and str(action.get("tool", "")).strip().lower() == "escalate"


def _run(target: Router, messages: list[dict[str, str]]) -> tuple[Any, str, bool]:
    """Executa a cadeia em json_mode e devolve (resposta, provedor, escalou).

    Aplica o cap de tokens (thinking models) e converte falhas de
    disponibilidade em ActionError. O provedor é reportado para observabilidade
    da escalada.
    """
    try:
        result, provider, escalated = target.run(
            messages, json_mode=True, temperature=0.0, max_tokens=_ORCH_MAX_TOKENS
        )
        return result, provider, escalated
    except RouterExhausted:
        raise ActionError("Não consegui interpretar o comando (cadeia indisponível).")
    except LLMError as exc:
        raise ActionError(f"Não consegui interpretar o comando: {exc}") from exc


def parse_command(
    router: Router,
    command: str,
    screen_context: str = "",
    escalation_router: Router | None = None,
    force_strong: bool = False,
) -> dict[str, Any]:
    """Converte o comando em uma ação estruturada {tool, params}.

    Orquestra na cadeia (MiniCPM → API). Se o orquestrador emitir o sinal
    `tool: "escalate"` (incapacidade, pedido de modelo forte, ou código além da
    capacidade), ou se `force_strong` for True, re-executa com o
    `escalation_router` (Claude Code → API Anthropic → cadeia gratuita).

    - `escalation_router` None + sinal/force_strong → ActionError (modelo forte
      indisponível).
    - O escalador NÃO pode re-escalar: `_normalize_action` rejeita `"escalate"`,
      e aqui detectamos o sinal do escalador com uma mensagem clara.
    """

    user = f"Comando: {command}"
    if screen_context:
        user += f"\n\nContexto da tela (árvore de acessibilidade):\n{screen_context[:4000]}"
    messages = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": user},
    ]

    def _resolve(target: Router, *, escalated: bool) -> dict[str, Any]:
        raw, provider, _was_escalated = _run(target, messages)
        if _is_escalation(raw):
            logging.warning("Modelo forte (%s) re-solicitou escalada — comando não resolvido", provider)
            raise ActionError("O modelo forte também não conseguiu resolver o comando (re-solicitou escalada).")
        if escalated:
            logging.warning("Escalada para modelo forte: provedor '%s'", provider)
        return _normalize_action(raw)

    if force_strong:
        if escalation_router is None:
            raise ActionError("Modelo forte indisponível (nenhum escalador configurado).")
        return _resolve(escalation_router, escalated=True)

    action, _provider, _was_escalated = _run(router, messages)
    if _is_escalation(action):
        if escalation_router is None:
            raise ActionError("O agente solicitou o modelo forte, mas ele está indisponível.")
        return _resolve(escalation_router, escalated=True)

    return _normalize_action(action)


class ToolExecutor(ABC):
    """Executa uma ação estruturada. (Abstração para testes e transporte.)"""

    @abstractmethod
    def execute(self, action: dict[str, Any]) -> str:
        """Executa {tool, params} e devolve o resultado como texto."""


class MCPToolExecutor(ToolExecutor):
    """Executor real: conecta ao computer-control-mcp-server via stdio (MCP SDK)."""

    def __init__(self, mcp_command: str | None = None, timeout: float | None = None) -> None:
        # Ex.: "npx -y @wshobson/mcp-server-computer-control"
        self.mcp_command = mcp_command or os.getenv(
            "COMPUTER_CONTROL_MCP_CMD", "npx -y @wshobson/mcp-server-computer-control"
        )
        self.timeout = timeout or float(os.getenv("MCP_TIMEOUT", "60"))

    def execute(self, action: dict[str, Any]) -> str:
        # Defesa em profundidade: revalida a whitelist aqui também (não confia
        # apenas na validação do endpoint).
        if not isinstance(action, dict) or str(action.get("tool", "")).strip().lower() not in TOOL_WHITELIST:
            return "Ação rejeitada: ferramenta fora da whitelist."
        try:
            return asyncio.run(self._execute(action))
        except Exception as exc:  # noqa: BLE001
            return f"Erro ao executar a ação: {exc}"

    async def _execute(self, action: dict[str, Any]) -> str:
        from mcp import ClientSession, StdioServerParameters  # pip install mcp
        from mcp.client.stdio import stdio_client

        parts = self.mcp_command.split()
        if os.name == "nt":
            # No Windows, CreateProcess não executa .cmd (npx.cmd) diretamente:
            # passa pelo cmd.exe.
            server_params = StdioServerParameters(command="cmd", args=["/c", *parts])
        else:
            server_params = StdioServerParameters(command=parts[0], args=parts[1:])

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tool = action["tool"]
                result = await asyncio.wait_for(
                    session.call_tool(tool, action.get("params") or {}), timeout=self.timeout
                )
                # Resultado MCP: lista de content blocks (TextContent etc.)
                blocks = getattr(result, "content", None) or []
                texts = [b.text for b in blocks if hasattr(b, "text")]
                return "\n".join(texts) if texts else str(result)
