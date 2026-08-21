# Needle como camada de tool-call + orquestrador online (qwen offline)

## Context
O fluxo de controle (`/api/act` → `aeye/agent.py::parse_command`) hoje converte
comando → `{tool, params}` em **um único passo** via cadeia gratuita
(Gemini/Cerebras). O usuário quer separar em **dois papéis**:

- **Orquestrador** (decide a ação): API online free tier (Gemini/Cerebras) como
  **principal**; **qwen3.5:0.8b** (Ollama local) como **fallback offline** quando
  não há acesso online.
- **Tool-call** (produz o `{tool, params}` concreto): **Needle, sempre** — modelo
  de tool-calling de 14MB, 100% offline, saída JSON restrita por gramática e com
  `confidence` calibrado.

Ponto-chave da API do Needle: `agent.complete(text)` devolve a chamada **sem
executar** (`{type:"call", function_calls:[{name,arguments}], reasoning,
confidence}`), preservando o fluxo WYSIWYG de aprovação do AEye. Não usamos
`agent.run()` (que executa).

## Assumptions and decisions
- Decision: **Pipeline em 2 estágios** em `parse_command`:
  1. **Orquestrador** → intent curto (instrução de ação em pt-BR, ex.: "Clique no
     botão OK.").
  2. **Needle** → `{tool, params, rationale}` a partir do intent.
  *Source: user directive (orquestrador online + needle na tool-call).*
- Decision: **Orquestrador = free tier (principal)**, com **qwen3.5:0.8b (Ollama)
  como fallback offline** quando o free tier estoura (`RouterExhausted`). *Source:
  user directive.*
- Decision: **Tool-call = Needle, sempre** (quando `AEYE_NEEDLE=1` e disponível).
  *Source: user directive ("needle eh sempre usado na api de tool call").*
- Decision: **Opt-in** via `AEYE_NEEDLE=1`. Quando desligado, o fluxo mantém o
  comportamento atual de passo único (backward compat). *Source: padrão
  `AEYE_MCP` @ app.py:build_executor.*
- Decision: **Módulo dedicado** `aeye/needle_parser.py` (tool-call), NÃO forçado na
  interface `LLMClient`/`Router` (interface incompatível). *Source: code @
  aeye/llm.py:LLMClient, aeye/router.py:Router.*
- Decision: **Import lazy** de `cactus-needle` com guarda de disponibilidade
  (`NeedleParser.available()`), igual a `mcp`/`anthropic`/`pyttsx3`. *Source:
  .agents/common-mistakes/python.md.*
- Decision: **Subconjunto inicial (~10 ferramentas)** da `TOOL_WHITELIST`;
  descrições em pt-BR; nomes = `TOOL_WHITELIST`. *Source: user-unavailable →
  default pragmático.*
- Decision: **Confidence gate** (`AEYE_NEEDLE_CONFIDENCE`, default `0.5`); abaixo
  → `NeedleLowConfidence` → `ActionError`. *Source: needle doc/apis.md
  "Confidence".*
- Decision: **`reset()` entre parses** — cada comando é stateless; `parse` chama
  `agent.reset()` (mantém tools carregadas) antes de cada `complete()`. *Source:
  revisão do plano (estado de sessão).*
- Decision: **Lock em `parse`** — `/api/act` roda em `run_in_threadpool` sem lock;
  o agente do Needle guarda estado mutável, então `parse` serializa com um
  `threading.Lock`. *Source: revisão do plano (thread-safety).*
- Decision: **Orçamento de tokens**: com o design em 2 estágios, o input do Needle
  é o **intent curto** do orquestrador (não o comando cru + contexto). Schemas de
  ferramenta são **pinados como KV sinks** (não contam na janela de 256 tokens) —
  verificar o pinning no playground; orçar apenas o intent. *Source: needle
  README ("tools pinned as KV sinks"); revisão do plano.*
- Decision: **qwen3.5:0.8b** via Ollama (`OpenAICompatClient`, `OLLAMA_URL`),
  configurável via `AEYE_ORCH_OFFLINE_MODEL`. *Source: user directive; code @
  aeye/llm.py:default_providers (ollama).*
- Assumption: `cactus-needle` entra como dependência **opcional** (comentada) no
  `requirements.txt`. *Source: code @ requirements.txt.*

## Files to touch

### aeye/needle_parser.py (novo) — camada de tool-call
- What changes: converte um intent (instrução de ação) em `{tool, params}` via
  Needle (offline), com schemas, confidence gate, reset e lock.
- Function(s):
  - `NEEDLE_TOOL_SCHEMAS: list[dict[str, Any]]` — schemas JSON puros (~10 tools).
  - `class NeedleUnavailable(Exception)`
  - `class NeedleLowConfidence(Exception)`
  - `class NeedleParser`:
    - `__init__(self, confidence_threshold: float | None = None, weights: str | None = None, agent: Any | None = None)`
    - `@staticmethod available() -> bool`
    - `_agent_instance(self) -> Any` (lazy import + build; `agent` injetável p/ teste)
    - `parse(self, intent: str) -> dict[str, Any]` (com `threading.Lock` + `reset()`)
- Data shapes:
  - Entrada: `intent: str` (instrução curta de ação).
  - Saída: chamada crua do Needle: `{"tool": str, "params": dict, "rationale": str}`
    (mapeia `reasoning` → `rationale`). A validação de whitelist/`"none"`/params
    acontece em `parse_command` (fonte única), não aqui.
  - Erros: `NeedleUnavailable` (não instalado/init falhou), `NeedleLowConfidence`
    (confidence < limiar). Off-topic (`function_calls: []`) → devolve `None`
    (sinaliza ao chamador) — a mensagem de "nenhuma ação" fica em `parse_command`.
- Integration points: chamado por `aeye/agent.py::parse_command` (estágio 2).
- Error paths: import falho → `NeedleUnavailable`; `complete()` lança →
  `NeedleUnavailable`; `confidence < limiar` → `NeedleLowConfidence`;
  `function_calls` vazio → retorna `None`.

### aeye/agent.py
- What changes: `parse_command` vira pipeline em 2 estágios; novo `_orchestrate` e
  `_single_step` (extrai a lógica atual de passo único).
- Function(s):
  - `_ORCH_SYSTEM_PROMPT` — pede ao orquestrador um intent curto e autocontido
    (pt-BR), NÃO o JSON `{tool, params}` (isso é do Needle). Deve instruir a
    preservar o alvo da ação (ex.: "Clique no botão OK") para o Needle preencher
    os params.
  - `_orchestrate(router, command, screen_context="", offline_client=None) -> str`
    — free tier via `router.run(..., json_mode=False, temperature=0.0)` (intent NL,
    NÃO JSON); em `RouterExhausted`, tenta `offline_client` (qwen Ollama); se o
    intent vier vazio → `ActionError`; senão levanta `ActionError`.
  - `_single_step(router, command, screen_context="", offline_client=None) -> dict`
    — lógica atual (free tier `json_mode=True` → `{tool, params}`), com fallback
    qwen offline em `RouterExhausted`.
  - `parse_command(router, command, screen_context="", needle=None, offline_client=None)`
    — se `needle` e `not screen_context`: `intent = _orchestrate(...)` →
    `needle.parse(intent)`; se o Needle falhar em runtime (`NeedleUnavailable`/
    `NeedleLowConfidence`), **degrada para `_single_step`** (não falha o comando);
    senão: `_single_step(...)`.
- Data shapes: inalterado (retorna `{tool, params, rationale}` ou levanta
  `ActionError`).
- Integration points: `app.py::api_act` passa `needle_parser` e `offline_client`.
- Error paths: free tier estoura → qwen offline; qwen falha → `ActionError`;
  Needle falha em runtime → degrada para `_single_step` (robusto). **Validação com
  fonte única**: `NeedleParser.parse` devolve a chamada crua; `parse_command`
  aplica TODA a normalização/validação (lowercase do `tool`, `"none"`, whitelist,
  `params`-é-dict) — evita dupla validação divergente.
- Import: adicionar `LLMClient` ao `from .llm import ...` em `agent.py` (hoje só
  importa `LLMError`).

### app.py
- What changes: constrói `NeedleParser` e o orquestrador offline (qwen) no
  lifespan (opt-in) e injeta no `parse_command`.
- Function(s):
  - `needle_parser: NeedleParser | None = None` (global)
  - `offline_client: LLMClient | None = None` (global) — qwen3.5:0.8b via Ollama
  - no `lifespan`: se `AEYE_NEEDLE=1` e `NeedleParser.available()` → instancia
    `NeedleParser`; constrói `offline_client` (qwen) se `AEYE_ORCH_OFFLINE=1`;
    senão loga aviso.
  - em `api_act`: `run_in_threadpool(parse_command, router, command, "", needle_parser, offline_client)`
    — mantém a chamada bloqueante fora do event loop.
- Data shapes: inalterado.
- Integration points: `aeye/needle_parser.NeedleParser`, `aeye/agent.parse_command`,
  `aeye.llm.OpenAICompatClient`.
- Error paths: `cactus-needle` ausente com `AEYE_NEEDLE=1` → loga aviso, segue sem
  tool-call Needle (passo único); Ollama fora do ar → `offline_client` falha →
  `ActionError` (não quebra o servidor).

### requirements.txt
- What changes: adiciona `cactus-needle` como dependência opcional comentada.

### .env.example
- What changes: documenta `AEYE_NEEDLE`, `AEYE_NEEDLE_CONFIDENCE`,
  `AEYE_ORCH_OFFLINE`, `AEYE_ORCH_OFFLINE_MODEL`.

### tests/test_needle_parser.py (novo)
- What changes: testes herméticos do parser (tool-call) e do pipeline 2 estágios
  (sem Needle real).
- Function(s): testes com `NeedleParser(agent=<fake>)` injetado.
- Data shapes: fake agent devolve dicts no shape de `complete()`.
- Integration points: `aeye.needle_parser`, `aeye.agent.parse_command`.
- Error paths: low-confidence, off-topic, tool fora da whitelist, fallback qwen
  quando router estoura, passo único quando Needle ausente.

## Edge cases
- `cactus-needle` não instalado com `AEYE_NEEDLE=1` → aviso no log, servidor sobe
  em passo único (`_single_step`, não quebra).
- Free tier estoura (offline) → orquestrador cai para qwen3.5:0.8b (Ollama); se
  Ollama também falhar → `ActionError`.
- Needle falha em runtime (`NeedleUnavailable`/`NeedleLowConfidence`) → degrada
  para `_single_step` (não falha o comando).
- Comando off-topic → Needle devolve `None` → `parse_command` levanta `ActionError`
  ("O comando não pediu nenhuma ação de computador.").
- Comando com contexto de tela (futuro) → Needle é pulado (janela 256 tokens);
  usa `_single_step` (orquestrador com contexto).
- Tool fora da whitelist / params não-dict → `ActionError` (validação em
  `parse_command`).
- `complete()` lança (engine/init) → `NeedleUnavailable` → degrada para
  `_single_step`.
- Concorrência: dois `/api/act` simultâneos → lock serializa o `parse` do Needle.
- Intent vazio do orquestrador → `ActionError`.

## Verification
- Run: `python3 -m pytest tests/ -q` (baseline 50 pass; esperado 50 + novos).
- Tests to add/update (`tests/test_needle_parser.py`):
  - `test_parse_valido` — fake agent devolve call válido → `{tool, params, rationale}`.
  - `test_parse_baixa_confianca` — confidence < limiar → `NeedleLowConfidence`.
  - `test_parse_off_topic` — `function_calls: []` → devolve `None`.
  - `test_parse_chama_reset` — `reset()` é chamado antes de cada `complete()`.
  - `test_parse_command_2_estagios` — Router ok + fake Needle → orquestrador gera
    intent NL, Needle gera a ação, `parse_command` valida.
  - `test_parse_command_fallback_qwen` — Router estoura + fake offline_client →
    usa qwen como orquestrador, depois Needle.
  - `test_parse_command_needle_falha_degrada` — Needle levanta
    `NeedleUnavailable` → degrada para `_single_step` (não falha).
  - `test_parse_command_passo_unico_sem_needle` — Needle ausente → `_single_step`
    (comportamento atual).
  - `test_parse_command_off_topic` — Needle devolve `None` → `ActionError`.
  - `test_orchestrate_intent_vazio` — intent vazio → `ActionError`.
  - `test_available_sem_pacote` — `NeedleParser.available()` False sem o pacote.
- Manual: com `AEYE_NEEDLE=1` e `pip install cactus-needle`, rodar o servidor e
  disparar um comando de controle → orquestrador (free tier) decide, Needle produz
  o `{tool, params}`, modal de aprovação mostra a ação. Derrubar a rede → qwen
  assume o orquestrador, Needle segue na tool-call.
- Done criteria: com `AEYE_NEEDLE=1`, um comando de controle é orquestrado pelo
  free tier (ou qwen offline) e o `{tool, params}` é produzido pelo Needle, passando
  pelo fluxo de aprovação normal.

## Standards / common-mistakes referenced
- `.agents/standards/python.md` — Python 3.10+, funções curtas, `Sequence[T]`,
  `run_in_threadpool` para trabalho bloqueante.
- `.agents/common-mistakes/python.md` — lazy 3rd-party imports com guards
  (cactus-needle); não engolir exceções sem causa (exceções específicas).

## Estimated scope
M (single PR; novo módulo + pipeline 2 estágios em `agent.py` + orquestrador
offline qwen + wiring em `app.py` + `.env.example` + testes; zero mudança de
comportamento quando `AEYE_NEEDLE` não está setado).

## Open questions (CONSIDER from review)
- **Contrato orquestrador→Needle**: o orquestrador emite um intent NL curto e o
  Needle mapeia para `{tool, params}`. Validar empiricamente (playground) se o
  intent NL preserva informação suficiente (ex.: alvo do clique) para o Needle
  preencher os params corretamente. O `_ORCH_SYSTEM_PROMPT` deve ser explícito
  sobre preservar o alvo.
- **Pinning dos schemas**: confirmar no playground que os schemas de ferramenta
  são pinados (KV sinks) e não contam na janela de 256 tokens; se contarem, o
  subconjunto de ~10 tools pode estourar e a feature fica inviável.
- **Idioma**: descrições em pt-BR vs treinamento em inglês do Needle — validar
  qualidade antes de escrever os 10 schemas.
- **Multi-call**: `function_calls` pode trazer várias chamadas; o plano usa
  `calls[0]` (ação única WYSIWYG) — explícito.
- **`confidence: None`** (weights afinados) → tratado como aceitável; só importa
  com weights afinados, que o AEye não usará de início.
- **README**: documentar o fallback offline e o modo 2 estágios.
- **Latência**: o modo 2 estágios adiciona uma chamada LLM extra (orquestrador) +
  Needle por comando de controle. Aceitável para o volume, mas vale mensurar.
- **qwen offline no `_single_step`**: o fallback qwen é aplicado no `_orchestrate`
  (modo 2 estágios) e no `_single_step`. Confirmar que ambos usam qwen quando
  `AEYE_ORCH_OFFLINE=1`, para consistência offline.

## Status: IMPLEMENTADO ✅
- `aeye/needle_parser.py` (novo): `NEEDLE_TOOL_SCHEMAS` (10 tools), `NeedleUnavailable`,
  `NeedleLowConfidence`, `NeedleParser` (lazy import, `available()`, agent injetável,
  `threading.Lock`, `reset()` antes de cada `complete()`, `parse` → `{tool, params,
  rationale}` ou `None`).
- `aeye/agent.py`: `_ORCH_SYSTEM_PROMPT`, `_normalize_action` (fonte única de
  validação), `_orchestrate` (free tier → qwen offline), `_single_step` (legado +
  fallback qwen), `parse_command` com pipeline de 2 estágios e degradação.
- `app.py`: globals `needle_parser`/`offline_client`, `build_needle_parser()`,
  `build_offline_client()` (qwen via Ollama), wiring em `lifespan` e `api_act`.
- `requirements.txt` + `.env.example`: `cactus-needle`, `AEYE_NEEDLE`,
  `AEYE_NEEDLE_CONFIDENCE`, `AEYE_NEEDLE_WEIGHTS`, `AEYE_ORCH_OFFLINE`,
  `AEYE_ORCH_OFFLINE_MODEL`.
- `tests/test_needle_parser.py` (novo): 12 testes (parse, off-topic, baixa
  confiança, unavailable, reset, 2 estágios, degradação, passo único, off-topic→
  ActionError, available).
- Verificação: `python3 -m pytest tests/ -q` → **62 passed** (50 baseline + 12
  novos); `node --check web/app.js` → OK. Zero mudança de comportamento quando
  `AEYE_NEEDLE` não está setado.