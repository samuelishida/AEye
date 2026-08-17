"""Provedores de LLM gratuitos para o AEye.

Cadeia padrão (100% gratuita, sem cartão):
  Gemini 2.5 Flash (free tier, AI Studio) -> Cerebras (Llama 3.3 70B, free)

Qualquer provedor OpenAI-compatível pode ser adicionado à cadeia trocando
``base_url`` e modelo (Groq, SambaNova, OpenRouter `:free`, Ollama local...).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Any, Sequence

from dotenv import load_dotenv

load_dotenv()


class LLMError(Exception):
    """Falha de chamada ao provedor: rate limit, rede, chave, API, resposta inválida."""


# Placeholders do .env.example — não podem ser aceitos como chave real
# (senão a cadeia "funciona" e todas as chamadas falham silenciosamente).
_PLACEHOLDER_MARKS = ("coloque_aqui", "your-", "xxxx", "sk-your", "put_your", "sua_chave")


def key_ok(key: str | None) -> bool:
    """Chave configurada de verdade? (não vazia e não placeholder do exemplo)."""
    k = (key or "").strip()
    if not k:
        return False
    low = k.lower()
    return not any(mark in low for mark in _PLACEHOLDER_MARKS)


class LLMClient(ABC):
    """Interface mínima de um provedor de LLM."""

    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Envia mensagens [{'role': ..., 'content': ...}] e devolve o texto da resposta.

        Levanta LLMError em qualquer falha (429, rede, chave, resposta vazia...).
        """


# --------------------------------------------------------------------------- #
# Gemini (principal)
# --------------------------------------------------------------------------- #
class GeminiClient(LLMClient):
    """Google Gemini 2.5 Flash no free tier (AI Studio, ~1.500 req/dia).

    SDK próprio ``google-genai``. Suporta modo JSON nativo e visão.
    """

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash") -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        if not key_ok(self.api_key):
            raise LLMError(
                "GEMINI_API_KEY não configurada (ou ainda é o placeholder do .env.example)"
            )
        self.model = model

    def _client(self) -> Any:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover
            raise LLMError("Pacote 'google-genai' não instalado (pip install google-genai)") from exc
        return genai.Client(api_key=self.api_key)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        client = self._client()
        config: dict[str, Any] = {"temperature": temperature}
        if json_mode:
            config["response_mime_type"] = "application/json"
        if max_tokens:
            config["max_output_tokens"] = max_tokens

        # System prompt vai em system_instruction (não como turno de usuário).
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        if system:
            config["system_instruction"] = system

        contents = []
        for m in messages:
            if m.get("role") == "system":
                continue
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        try:
            resp = client.models.generate_content(model=self.model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001 - 429/RESOURCE_EXHAUSTED, rede, etc.
            raise LLMError(f"Gemini falhou: {exc}") from exc

        text = getattr(resp, "text", None) or ""
        if not text.strip():
            raise LLMError("Gemini devolveu resposta vazia")
        return text

    def describe_image(self, image_bytes: bytes, prompt: str, mime: str = "image/png") -> str:
        """Visão de backup: descreve/extrai texto de uma imagem (usado se o Ollama estiver fora)."""
        client = self._client()
        contents = [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": mime, "data": image_bytes}},
                    {"text": prompt},
                ],
            }
        ]
        try:
            resp = client.models.generate_content(model=self.model, contents=contents)
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Gemini (visão) falhou: {exc}") from exc
        text = getattr(resp, "text", None) or ""
        if not text.strip():
            raise LLMError("Gemini (visão) devolveu resposta vazia")
        return text


# --------------------------------------------------------------------------- #
# Cerebras e outros OpenAI-compatíveis (fallback)
# --------------------------------------------------------------------------- #
class OpenAICompatClient(LLMClient):
    """Qualquer provedor com API OpenAI-compatível (Cerebras, Groq, SambaNova, OpenRouter, Ollama...).

    Uma classe só, diferenciada por ``base_url``/modelo/chave.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        model: str = "llama-3.3-70b",
    ) -> None:
        self.name = name
        self.base_url = base_url
        self.model = model
        key = api_key or (os.getenv(api_key_env, "") if api_key_env else "")
        if api_key_env and not key_ok(key):
            raise LLMError(
                f"{api_key_env} não configurada (ou ainda é o placeholder do .env.example)"
            )
        self.api_key = key or "not-needed"

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError("Pacote 'openai' não instalado (pip install openai)") from exc

        kwargs: dict[str, Any] = {}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        client = OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=60)
        try:
            if json_mode:
                try:
                    kwargs["response_format"] = {"type": "json_object"}
                    resp = client.chat.completions.create(
                        model=self.model, messages=list(messages), temperature=temperature, **kwargs
                    )
                except Exception as json_exc:
                    # Alguns provedores não aceitam response_format: tenta de novo sem.
                    kwargs.pop("response_format", None)
                    try:
                        resp = client.chat.completions.create(
                            model=self.model, messages=list(messages), temperature=temperature, **kwargs
                        )
                    except Exception as exc:
                        raise LLMError(f"{self.name} (json) falhou: {json_exc}; sem json_object: {exc}") from exc
            else:
                resp = client.chat.completions.create(
                    model=self.model, messages=list(messages), temperature=temperature, **kwargs
                )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - 429, rede, etc.
            raise LLMError(f"{self.name} falhou: {exc}") from exc

        content = ""
        if getattr(resp, "choices", None):
            content = getattr(resp.choices[0].message, "content", None) or ""
        if not content.strip():
            raise LLMError(f"{self.name} devolveu resposta vazia")
        return content


# --------------------------------------------------------------------------- #
# Claude Code local (L3 — "modelo forte" sem depender da API da Anthropic)
# --------------------------------------------------------------------------- #
class ClaudeCodeClient(LLMClient):
    """Aciona o Claude Code instalado no PC do usuário (CLI local, modo print).

    Usa a conta/assinatura do próprio usuário (OAuth do Claude Code) — NÃO
    depende de chave de API da Anthropic nem de terceiros. Útil quando o
    provedor de API da Anthropic não está acessível.

    Comando: claude -p --output-format json --no-session-persistence [--model X] "prompt"
    """

    name = "claude_code"

    def __init__(self, model: str | None = None, timeout: float | None = None, max_turns: int | None = None) -> None:
        self.model = model or os.getenv("CLAUDE_CODE_MODEL", "")  # ex.: "sonnet" | "opus" | "haiku"
        self.timeout = timeout or float(os.getenv("CLAUDE_CODE_TIMEOUT", "180"))
        self.max_turns = max_turns or int(os.getenv("CLAUDE_CODE_MAX_TURNS", "3"))

    @staticmethod
    def available() -> bool:
        """O binário `claude` existe no PATH? (não garante login)."""
        return shutil.which("claude") is not None

    @staticmethod
    def install_hint() -> str:
        return "Instale com: npm install -g @anthropic-ai/claude-code  e rode `claude` uma vez para logar."

    def _build_prompt(self, messages: Sequence[dict[str, str]]) -> str:
        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        conversation = "\n\n".join(
            f"{'Usuário' if m.get('role') == 'user' else 'Assistente'}: {m.get('content', '')}"
            for m in messages
            if m.get("role") != "system"
        )
        return (system + "\n\n" if system else "") + conversation

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        if not self.available():
            raise LLMError(f"Claude Code não encontrado no PATH. {self.install_hint()}")

        cmd = ["claude", "-p", "--output-format", "json", "--no-session-persistence"]
        if self.model:
            cmd += ["--model", self.model]
        if self.max_turns:
            cmd += ["--max-turns", str(self.max_turns)]

        try:
            proc = subprocess.run(
                cmd + [self._build_prompt(messages)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Claude Code excedeu o tempo limite ({self.timeout}s)") from exc
        except Exception as exc:  # noqa: BLE001 - FileNotFoundError (binário deletado entre a verificação de disponibilidade e a execução), etc.
            raise LLMError(f"Claude Code falhou: {exc}") from exc

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise LLMError(f"Claude Code falhou (código {proc.returncode}): {detail}")

        try:
            data = json.loads(proc.stdout or "")
            text = data.get("result") or ""
        except json.JSONDecodeError:
            text = (proc.stdout or "").strip()

        if not text.strip():
            raise LLMError("Claude Code devolveu resposta vazia")
        return text


# --------------------------------------------------------------------------- #
# Anthropic (L3 — opcional, paga; só com chave PRÓPRIA da Anthropic)
# --------------------------------------------------------------------------- #
class AnthropicClient(LLMClient):
    """Claude via API da Anthropic. Opcional e pago — só usado se ANTHROPIC_API_KEY
    estiver configurada E o usuário ativar o toggle "modelo forte" na UI."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key_ok(self.api_key):
            raise LLMError(
                "ANTHROPIC_API_KEY não configurada (ou ainda é o placeholder do .env.example)"
            )
        self.model = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("Pacote 'anthropic' não instalado (pip install anthropic)") from exc

        system = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        conversation = [
            {"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")}
            for m in messages
            if m.get("role") != "system"
        ]
        client = Anthropic(api_key=self.api_key, timeout=60)
        try:
            resp = client.messages.create(
                model=self.model,
                system=system or None,
                messages=conversation,
                max_tokens=max_tokens or 2048,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001 - 429, rede, etc.
            raise LLMError(f"Anthropic falhou: {exc}") from exc

        text = "".join(
            getattr(block, "text", "") for block in getattr(resp, "content", []) if getattr(block, "type", "") == "text"
        )
        if not text.strip():
            raise LLMError("Anthropic devolveu resposta vazia")
        return text


# --------------------------------------------------------------------------- #
# Fábrica da cadeia
# --------------------------------------------------------------------------- #
def default_providers() -> dict[str, Any]:
    """Provedores disponíveis. Cada entrada é um callable que devolve um LLMClient.

    Provedores sem chave configurada levantam LLMError na construção e são pulados.
    """
    return {
        "gemini": lambda: GeminiClient(),
        "cerebras": lambda: OpenAICompatClient(
            name="cerebras",
            base_url="https://api.cerebras.ai/v1",
            api_key_env="CEREBRAS_API_KEY",
            model=os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"),
        ),
        # Opcionais / documentados (basta incluir na AI_FALLBACK_CHAIN):
        "groq": lambda: OpenAICompatClient(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key_env="GROQ_API_KEY",
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        ),
        "samba": lambda: OpenAICompatClient(
            name="samba",
            base_url="https://api.sambanova.ai/v1",
            api_key_env="SAMBA_API_KEY",
            model=os.getenv("SAMBA_MODEL", "Meta-Llama-3.3-70B-Instruct"),
        ),
        "openrouter": lambda: OpenAICompatClient(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        ),
        "ollama": lambda: OpenAICompatClient(
            name="ollama",
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434") + "/v1",
            api_key="ollama",
            model=os.getenv("OLLAMA_MODEL_TEXT", "qwen3:4b"),
        ),
        # Claude Code local (L3). Só entra na cadeia se listado explicitamente.
        "claudecode": lambda: ClaudeCodeClient(),
    }


def build_chain(chain: str | None = None) -> list[tuple[str, LLMClient]]:
    """Constrói a lista ordenada [(nome, cliente)] a partir de AI_FALLBACK_CHAIN.

    Provedores sem chave são pulados silenciosamente (ex.: só GEMINI_API_KEY
    configurada usa apenas Gemini).
    """
    order = (chain or os.getenv("AI_FALLBACK_CHAIN", "gemini,cerebras")).split(",")
    providers = default_providers()
    built: list[tuple[str, LLMClient]] = []
    for raw in order:
        name = raw.strip().lower()
        if not name or name not in providers:
            continue
        try:
            built.append((name, providers[name]()))
        except LLMError:
            continue  # sem chave -> pula
    if not built:
        raise LLMError("Nenhum provedor de LLM configurado. Crie o .env (veja .env.example).")
    return built
