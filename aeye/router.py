"""Roteador de LLMs: cadeia de fallback gratuita com escalada automática.

Fluxo: tenta o primeiro provedor (Gemini); em erro 429/rate limit, timeout,
resposta vazia, recusa ou JSON inválido, tenta o próximo (Cerebras) e assim
por diante. Se todos falharem, levanta ``RouterExhausted`` com a última causa.
"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Any, Sequence

from .llm import LLMClient, LLMError, build_chain

# Sinais de recusa (pt + en) — escalada para o próximo provedor.
# Cuidado com falso-positivo: "as an AI" NÃO entra (Gemini/Claude começam
# respostas normais com "As an AI...").
DEFAULT_REFUSAL_PATTERNS = re.compile(
    r"não posso|nao posso|não consigo|nao consigo|não posso ajudar|nao posso ajudar|"
    r"não sou capaz|nao sou capaz|desculpe, não|desculpe, nao|"
    r"i can'?t|i cannot|unable to|i'?m sorry|refusing|refuse to",
    re.IGNORECASE,
)


class RouterExhausted(Exception):
    """Todos os provedores da cadeia falharam. Carrega a última causa."""

    def __init__(self, last_error: Exception) -> None:
        super().__init__(f"Todos os provedores falharam: {last_error}")
        self.last_error = last_error


def _find_all(text: str, ch: str) -> list[int]:
    return [i for i, c in enumerate(text) if c == ch]


def _match_brace(text: str, start: int, open_ch: str, close_ch: str) -> int | None:
    """Devolve o índice do fechamento correspondente, ou None se não fechar."""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return None


def extract_json(text: str) -> Any:
    """Extrai o primeiro JSON válido (objeto ou lista) de um texto.

    Tenta cada '{'/'[' como início candidato e aceita o primeiro que parsear —
    prosa com chaves (ex.: "o valor {x} era...") não quebra mais o parse.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    for candidate in (cleaned, text):
        starts = [(i, "{", "}") for i in _find_all(candidate, "{")]
        starts += [(i, "[", "]") for i in _find_all(candidate, "[")]
        starts.sort(key=lambda t: t[0])
        for start, open_ch, close_ch in starts:
            end = _match_brace(candidate, start, open_ch, close_ch)
            if end is None:
                continue
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue  # prosa com chaves: tenta o próximo candidato
    raise ValueError("JSON não encontrado na resposta")


class Router:
    """Roteador da cadeia gratuita com escalada automática."""

    def __init__(
        self,
        chain: list[tuple[str, LLMClient]] | None = None,
        refusal_patterns: re.Pattern[str] | None = None,
        backoff_base: float = 1.0,
        backoff_cap: float = 8.0,
    ) -> None:
        self.chain = chain if chain is not None else build_chain()
        self.refusal = refusal_patterns or DEFAULT_REFUSAL_PATTERNS
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.chain]

    def _backoff(self, index: int) -> None:
        if index >= len(self.chain) - 1:
            return
        delay = min(self.backoff_base * (2 ** index), self.backoff_cap) + random.uniform(0, 0.5)
        time.sleep(delay)

    def run(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_retries: int = 2,
    ) -> tuple[Any, str, bool]:
        """Executa a cadeia. Devolve (resposta, provedor_usado, escalou_bool).

        - json_mode=False: resposta é str.
        - json_mode=True: resposta é o objeto JSON já parseado.
        """
        last_error: Exception | None = None
        for index, (name, client) in enumerate(self.chain):
            escalated = index > 0
            try:
                if json_mode:
                    result = self._run_json(
                        client, messages, temperature=temperature, max_tokens=max_tokens, retries=json_retries
                    )
                else:
                    result = self._run_text(client, messages, temperature=temperature, max_tokens=max_tokens)
                return result, name, escalated
            except LLMError as exc:
                last_error = exc
                self._backoff(index)
        raise RouterExhausted(last_error or LLMError("cadeia vazia"))

    def _run_text(self, client: LLMClient, messages, *, temperature, max_tokens) -> str:
        text = client.chat(messages, json_mode=False, temperature=temperature, max_tokens=max_tokens)
        if not text.strip():
            raise LLMError(f"{client.name} devolveu resposta vazia")
        if self.refusal.search(text):
            raise LLMError(f"{client.name} recusou a tarefa")
        return text

    def _run_json(self, client: LLMClient, messages, *, temperature, max_tokens, retries: int) -> Any:
        for attempt in range(retries + 1):
            text = client.chat(
                messages,
                json_mode=True,
                temperature=temperature,
                max_tokens=max_tokens or 1024,
            )
            try:
                return extract_json(text)
            except (ValueError, json.JSONDecodeError) as exc:
                if attempt >= retries:
                    raise LLMError(f"{client.name} devolveu JSON inválido: {exc}") from exc
        # The for-loop always raises on the final attempt when no parse succeeds;
        # this loop body is therefore exhaustive and returns only on success.
