"""Agente de controle do computador por voz/texto.

Fluxo: comando ("clica no botão X", "abre o Word e digita olá") -> LLM converte
para JSON {tool, params} -> execução via MCP (computer-control-mcp-server do
wshobson/agents, que usa a árvore de acessibilidade/UI Automation do Windows).

Segurança: toda ação só é executada após aprovação explícita na UI; há
whitelist de ferramentas e kill switch (segurar Esc cancela a ação em curso).
"""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any

from .llm import LLMError
from .router import Router, RouterExhausted

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
        '{"tool": "none", "params": {}, "rationale": "..."}.'
    )


def parse_command(router: Router, command: str, screen_context: str = "") -> dict[str, Any]:
    """Converte o comando em uma ação estruturada usando a cadeia gratuita."""
    user = f"Comando: {command}"
    if screen_context:
        user += f"\n\nContexto da tela (árvore de acessibilidade):\n{screen_context[:4000]}"
    try:
        action = router.run(
            [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": user}],
            json_mode=True,
            temperature=0.0,
        )[0]
    except (RouterExhausted, LLMError) as exc:
        raise ActionError(f"Não consegui interpretar o comando: {exc}") from exc

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
