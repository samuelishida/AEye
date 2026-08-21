# MiniCPM Orquestrador + LightOnOCR

## Context

O AEye precisa de um orquestrador local que seja o **principal** no fluxo de ação
(`/api/act` → `aeye/agent.py::parse_command`), com capacidade de **escalar para a
API (gemini/cerebras) ou para o Claude** quando necessário. Isso substitui o
pipeline de dois estágios que o plano anterior introduziu com o **Needle**
(`aeye/needle_parser.py`) — o usuário pediu para **remover o Needle do projeto**.

Além disso, o modelo de OCR local muda de `glm-ocr` para
`aipib/LightOnOCR-2-1B:Q8_0` (via Ollama), **removendo o glm**.

Intenção do usuário (confirmada):
1. **MiniCPM5-1B** (`jewelzufo/MiniCPM5-1B:latest` via Ollama) é o **primeiro
   provedor da cadeia por padrão** e orquestra as ações.
2. Escalada para **Claude** (ou API) **somente quando**: o modelo julgar que não
   consegue executar, o usuário pedir explicitamente o modelo forte, ou a tarefa
   exigir escrever/executar código além da capacidade do modelo de 1B.
3. **OCR**: `aipib/LightOnOCR-2-1B:Q8_0` é o principal; remover o `glm-ocr`.

## Architectural decisions

- **Decision: MiniCPM é o orquestrador e produz `{tool, params}` diretamente**
  (single-step). Rationale: com o Needle removido, não há segundo estágio; o
  MiniCPM é um LLM capaz de tool-calling e gera a ação diretamente, como o
  pipeline original fazia. Alternatives rejected: manter o two-stage (orquestrador
  NL → tool-call) — desnecessário sem o Needle, adiciona latência e complexidade.
- **Decision: escalada é por sinal explícito `tool: "escalate"` emitido pelo
  orquestrador**, não apenas por falha dura. Rationale: o usuário quer escalada
  por *julgamento* (incapacidade, pedido, código), o que exige que o modelo sinalize.
  O Router já cobre a falha dura (MiniCPM offline → próximo provedor da cadeia).
- **Decision: escalada re-executa o mesmo comando com um `escalation_router`**
  que espelha a prioridade já definida em `app.py::_call_strong`:
  **Claude Code → API Anthropic (chave própria) → `gemini,cerebras`**. Rationale: o
  app já define "modelo forte" assim; usar só `claudecode,senão gemini,cerebras`
  degradaria silenciosamente quem tem `ANTHROPIC_API_KEY` mas não o CLI `claude`.
  Reusa o mesmo `_system_prompt()` e a infra de `Router`; o escalador produz o mesmo
  formato `{tool, params}`. Alternativa rejeitada: chamar `claude` como tool do MCP —
  o executor MCP não tem `run_code` e a escalada é de interpretação, não de execução.
- **Decision: MiniCPM é o primeiro provedor de um `orchestration_router` DEDICADO ao
  fluxo de ação (`/api/act`); a cadeia global (`AI_FALLBACK_CHAIN`, default
  `gemini,cerebras`) fica intacta para `/api/chat` e OCR.**
  Rationale: o `Router()` global de `app.py` é compartilhado por `/api/act`,
  `/api/chat` e OCR L2 (`_call_llm`/`_call_strong`) — tornar um 1B o primeiro de
  TODOS esses caminhos seria regressão de qualidade. O usuário pediu MiniCPM
  "primeiro na cadeia" **no fluxo de ação**, que é justamente o `parse_command`/
  `/api/act`. Assim, o orquestrador dedica-se ao controle do PC e chat/OCR não
  degradam. Confirmado pelo usuário; scoped por revisão.
- **Decision: `orchestration_router` chain default = `minicpm,gemini,cerebras`**
  (via nova env `AEYE_ORCH_CHAIN`), construído em `app.py::lifespan` e passado a
  `parse_command`. Se o MiniCPM estiver offline, o Router escala para a API
  gratuita. Rationale: escalada automática em falha dura já coberta pelo Router.
- **Decision: Claude NÃO entra na cadeia do orquestrador** — só no
  `escalation_router`. Rationale: evitar acionar o CLI `claude` (lento, timeout
  180s) em todo comando. Confirmado pelo usuário.
- **Decision: novo provedor `minicpm` em `default_providers()`.**
  Rationale: modelo/config explícitos; o provedor `ollama` genérico permanece para
  backward-compat.
- **Decision: modelo OCR padrão vira `aipib/LightOnOCR-2-1B:Q8_0`; glm é removido.**
  Rationale: confirmado pelo usuário. `deepseek-ocr` continua como opcional
  (`IncludeDeepSeek`).

## Assumptions and answers from code

- **Decision: `Router` escala automaticamente em falha** (MiniCPM offline → API).
  Source: code @ `aeye/router.py:113` (`run` itera a chain; `RouterExhausted` só
  após esgotar).
- **Decision: `OpenAICompatClient` não exige chave para Ollama** (`api_key="ollama"`),
  então o provedor `minicpm` sempre constrói e falha só em runtime (offline → LLMError
  → o Router escala). Source: code @ `aeye/llm.py:402` (provedor `ollama`).
- **Decision: `extract_json` tolera prefixo de thinking/JSON aninhado** — o cap de
  tokens é o ponto sensível (thinking model), não o parse. Source: code @
  `aeye/router.py:66`.
- **Decision: `model_ready()` compara `name.split(":")[0]`**, então
  `aipib/LightOnOCR-2-1B:Q8_0` casa com o nome de tag. Source: code @ `aeye/vlm.py:56`.
- **Decision: `parse_command` atual tem params `needle`/`offline_client`** — serão
  removidos junto do Needle. Source: code @ `aeye/agent.py`.
- **Decision: default user-confirmed** (usuário indisponível; decisões recomendadas).

## Risks accepted

- **MiniCPM `:latest` pode ser thinking model / quant de baixa precisão** → resposta
  vazia ou JSON truncado. Mitigação: `parse_command` passa `max_tokens` EXPLÍCITO ao
  `router.run(..., json_mode=True)` nos dois caminhos (orquestração e escalada), porque
  `_run_json` em `aeye/router.py` capa em `max_tokens or 1024` e `parse_command` hoje
  NÃO envia `max_tokens` — sem isso um thinking model 1B queima o orçamento e devolve
  `content` vazio → LLMError → fallback silencioso para Gemini em todo comando.
  `extract_json` tolera o prefixo de thinking. Revisitar: preferir tag Q4/Q8 se
  `:latest` falhar.
- **MiniCPM offline/inexistente no startup** → o `orchestration_router` constrói com
  o `minicpm` primeiro; falha em runtime e o Router escala para a API, mas adiciona
  ~um timeout de latência por comando até escalar. Aceitável.
- **Latência da escalada** (Claude Code CLI, timeout 180s) → só dispara no sinal de
  escalada, não em todo comando. Aceitável.
- **Loop de escalada** (Claude também emite `escalate`) → não há loop; `_normalize_action`
  rejeita `"escalate"` (fora da whitelist) com `ActionError`. Aceitável.

## Increment DAG

- Inc 1 — Remove Needle (S) — depends on: none — unblocks: 2, 3
- Inc 2 — MiniCPM como orquestrador dedicado (S) — depends on: 1 — unblocks: 3, 5
- Inc 3 — Escalada por julgamento p/ Claude/API (M) — depends on: 1, 2 — unblocks: 5
- Inc 4 — OCR LightOnOCR (S) — depends on: none — unblocks: 5
- Inc 5 — Docs + .env.example (S) — depends on: 2, 3, 4

## Increments

### Inc 1 — Remove Needle (S)
**Status: done** ✅ (50 passed)
**Depends on:** none
**Unblocks:** 2, 3
**Done criteria:** `aeye/needle_parser.py` e `tests/test_needle_parser.py` deletados;
`parse_command` sem params de needle/offline_client; nenhuma referência a needle no
repo (exceto histórico); pytest verde.

#### Files to touch

##### aeye/needle_parser.py (delete)
- Remover o arquivo.

##### tests/test_needle_parser.py (delete)
- Remover o arquivo.

##### aeye/agent.py
- What changes: remover import do needle e os helpers do two-stage.
- Function(s): `parse_command(router, command, screen_context="") -> dict[str, Any]`
  (sem `needle`/`offline_client`); remover `_orchestrate`, `_single_step`,
  `_ORCH_SYSTEM_PROMPT`. Manter `_normalize_action`.
- Integration points: `app.py::api_act` chama `parse_command` — atualizar a chamada.
- Error paths: `RouterExhausted`/`LLMError` → `ActionError` (como o original).

##### app.py
- What changes: remover `needle_parser`/`offline_client` globals,
  `build_needle_parser`, `build_offline_client`, import de `NeedleParser` e
  `OpenAICompatClient` (se só usado p/ offline_client — conferir).
- Function(s): `api_act` chama `run_in_threadpool(parse_command, router, command)`.
- Integration points: `lifespan` deixa de setar `needle_parser`/`offline_client`.

##### requirements.txt
- Remover a linha `cactus-needle>=2.0`.

##### .env.example
- Remover bloco de vars do Needle (`AEYE_NEEDLE`, `AEYE_NEEDLE_CONFIDENCE`,
  `AEYE_NEEDLE_WEIGHTS`, `AEYE_ORCH_OFFLINE`, `AEYE_ORCH_OFFLINE_MODEL`).
- **Nota**: as vars `AEYE_ORCH_OFFLINE*` pertencem ao antigo fallback qwen do
  two-stage; removê-las junto do Needle. O novo orquestrador usa `AEYE_ORCH_MODEL`/
  `AEYE_ORCH_CHAIN` (Inc 2), que são diferentes.

#### Edge cases
- Nenhum arquivo pode importar `aeye.needle_parser` após a remoção.

#### Verification
- Run: `python3 -m pytest tests/ -q` (deve passar; baseline menos os testes do needle).
- Tests to add/update: nenhum novo; garantir que `tests/test_agent.py` passa sem needle.
- Done: pytest verde sem os arquivos do needle.

### Inc 2 — MiniCPM como orquestrador dedicado (S)
**Status: done** ✅ (55 passed)
**Depends on:** 1
**Unblocks:** 3
**Done criteria:** `parse_command` usa um `orchestration_router` com `minicpm`
primeiro (chain `minicpm,gemini,cerebras`) só no fluxo de ação; a cadeia global
(`/api/chat`, OCR) continua `gemini,cerebras`; `test_llm.py` cobre o provedor
`minicpm` e `test_agent.py` cobre o orquestrador.

#### Files to touch

##### aeye/llm.py
- What changes: adicionar provedor `minicpm` em `default_providers()`. **NÃO** mudar
  o default de `AI_FALLBACK_CHAIN` (`gemini,cerebras`) — a cadeia global fica intacta.
- Function(s): em `default_providers()`:
  ```python
  "minicpm": lambda: OpenAICompatClient(
      name="minicpm",
      base_url=os.getenv("OLLAMA_URL", "http://localhost:11434") + "/v1",
      api_key="ollama",
      model=os.getenv("AEYE_ORCH_MODEL", "jewelzufo/MiniCPM5-1B:latest"),
  ),
  ```
- Data shapes: `default_providers() -> dict[str, Any]` (inalterado).
- Integration points: `build_chain` (usado por `build_orchestration_router`).
- Error paths: `OpenAICompatClient` para Ollama não exige chave → nunca levanta na
  construção; falha em runtime (offline) → LLMError → Router escala.

##### app.py
- What changes: nova `build_orchestration_router()`; global `orchestration_router`;
  `lifespan` constrói; `api_act` passa o `orchestration_router` a `parse_command`.
- Function(s):
  ```python
  def build_orchestration_router() -> Router | None:
      """MiniCPM primeiro no fluxo de ação; escala p/ API gratuita se offline."""
      chain_env = os.getenv("AEYE_ORCH_CHAIN", "minicpm,gemini,cerebras")
      try:
          return Router(chain=build_chain(chain_env))
      except LLMError:
          return None
  ```
  - `parse_command` passa `orchestration_router` como `router`. A cadeia global
    (`router` original de `lifespan`) continua para `/api/chat`/OCR.
- Integration points: `parse_command(router, command)` — o `router` aqui é o
  `orchestration_router`. Global `router` continua em `lifespan` para chat/OCR.
  (O param `escalation_router`/`force_strong` só entra no Inc 3; aqui a chamada é
  `parse_command(router, command)`, sem eles.)
- Error paths: se `build_orchestration_router()` retorna `None` (nenhum provedor),
  `api_act` devolve 503 (como o `router is None` atual).

##### .env.example
- What changes: adicionar `AEYE_ORCH_MODEL=jewelzufo/MiniCPM5-1B:latest` e
  `AEYE_ORCH_CHAIN=minicpm,gemini,cerebras`. `AI_FALLBACK_CHAIN` permanece
  `gemini,cerebras` (chat/OCR).
- **Nota**: adicionar `AEYE_ORCH_MAX_TOKENS=2048` (cap de tokens para o caminho
  json do orquestrador; usado pelo `parse_command` no Inc 3).

##### tests/test_llm.py
- What changes: teste de que `build_chain("minicpm,...")` inclui `minicpm` como
  `OpenAICompatClient` com o modelo configurado. Não alterar testes do default global.

##### tests/test_agent.py
- What changes: `parse_command` usa orquestrador com `minicpm` fake como primeiro
  provedor → produz a ação; `minicpm` falha → escala para gemini/cerebras fake.

#### Edge cases
- Ollama sem o modelo baixado: `minicpm` constrói, falha em runtime, Router escala.
- `AEYE_ORCH_CHAIN` sem `minicpm` → orquestrador usa só a chain dada (ex.: só API).

#### Verification
- Run: `python3 -m pytest tests/ -q`.
- Tests to add/update: `test_llm.py`, `test_agent.py`.
- Done: `/api/act` usa MiniCPM; `/api/chat` e OCR não mudam de provedor.

### Inc 3 — Escalada por julgamento para Claude/API (M)
**Status: done** ✅ (62 passed)
**Depends on:** 1, 2
**Unblocks:** 5
**Done criteria:** `tool: "escalate"` do orquestrador re-executa com
`escalation_router`; app.py constrói e passa o `escalation_router`; testes cobrem
sinal de escalada e ausência de escalador.

#### Files to touch

##### aeye/agent.py
- What changes: (a) `_system_prompt()` passa a instruir o sinal `escalate` —
  adicionar a ferramenta especial `"escalate"` à lista de formatos permitidos e
  explicar quando usá-la (modelo julgar que não consegue, usuário pedir modelo
  forte, ou tarefa exigir escrever/executar código além da capacidade); (b) nova
  função `_is_escalation(action)`; (c) `parse_command` ganha `escalation_router:
  Router | None` e `force_strong: bool = False`; (d) o ponto de interceptação é
  ANTES de `_normalize_action`.
- Function(s):
  ```python
  def _is_escalation(action: Any) -> bool:
      return isinstance(action, dict) and str(action.get("tool", "")).strip().lower() == "escalate"

  def parse_command(
      router: Router,
      command: str,
      screen_context: str = "",
      escalation_router: Router | None = None,
      force_strong: bool = False,
  ) -> dict[str, Any]:
  ```
  - Lógica (interceptação explícita): monta `messages` (`_system_prompt()` + user).
    1. **TODAS as chamadas a `router.run`/`escalation_router.run` no caminho json
       passam `max_tokens=2048`** (p.ex. `router.run(messages, json_mode=True,
       temperature=0.0, max_tokens=2048)`), porque `_run_json` capa em `max_tokens
       or 1024` — sem isso um thinking model 1B devolve `content` vazio → fallback
       silencioso. Usar `max_tokens=2048` direto (ou uma constante `_ORCH_MAX_TOKENS`).
    2. Se `force_strong`: se `escalation_router is None` → `ActionError`; senão roda
       direto `escalation_router.run(messages, json_mode=True, max_tokens=2048)` e
       termina em `_normalize_action`.
    3. Senão, roda `router.run(messages, json_mode=True, max_tokens=2048)`.
    4. Se `_is_escalation(action)`: se `escalation_router is None` → `ActionError`
       (escalada indisponível); senão re-roda com `escalation_router.run(messages,
       json_mode=True, max_tokens=2048)`.
    5. Sempre termina em `_normalize_action(action)` — que rejeita `"escalate"`
       (fora da whitelist) com `ActionError`, então o escalador não pode re-escalar.
  - O `escalate_reason` (opcional) é preservado no `rationale` da ação final se o
    escalador não o preencher — ver Edge cases.
- Data shapes: resposta JSON do orquestrador `{tool, params, rationale, escalate_reason?}`.
- Integration points: `app.py::api_act` passa `escalation_router` e `force_strong`.

##### app.py
- What changes: nova `build_escalation_router()`; global `escalation_router`;
  `lifespan` constrói; `api_act` passa; novo campo `strong` no payload de `/api/act`.
- Function(s):
  ```python
  def build_escalation_router() -> Router | None:
      """Modelo forte da escalada: espelha _call_strong (Claude → API Anthropic → grátis)."""
      from aeye.llm import AnthropicClient, ClaudeCodeClient, build_chain
      names = []
      if ClaudeCodeClient.available():
          names.append("claudecode")
      if key_ok(os.getenv("ANTHROPIC_API_KEY")):
          names.append("anthropic")
      names.extend(["gemini", "cerebras"])
      try:
          return Router(chain=build_chain(",".join(names)))
      except LLMError:
          return None
  ```
  (Nota: `AnthropicClient` e `key_ok` já importados no topo de `app.py`.)
  - `api_act(payload)`: `force_strong = payload.get("strong") is True`; passa a
    `parse_command(router, command, "", escalation_router, force_strong)`.
- Integration points: `parse_command(router, command, "", escalation_router, force_strong)`.
- Error paths: se `escalation_router is None` (sem Claude e sem API) e houver sinal
  de escalada ou `force_strong` → `ActionError` claro ("modelo forte indisponível").

##### web/app.js + web/index.html
- What changes: botão "⭐ Usar modelo forte" no fluxo de ação (`/api/act`) envia
  `strong: true` no payload.
- **IMPORTANTE: usar um elemento NOVO (`actStrongToggle`) e NÃO reusar
  `strongToggle`** — `strongToggle` já é o toggle do OCR (`runOcrFlow` lê
  `$("strongToggle").checked`); reusá-lo acoplaria os dois fluxos.
- Integration points: `runActFlow(command)`/`_runAct` lê `$("actStrongToggle").checked`
  e inclui `strong` no payload de `/api/act`.
- Done: frontend permite forçar a escalada sem afetar o toggle do OCR.

##### tests/test_agent.py (e novo tests/test_escalation.py)
- What changes: testes de `parse_command` — (a) `tool: "escalate"` → re-executa com
  escalador fake; (b) `tool: "escalate"` sem escalador → `ActionError`;
  (c) `force_strong=True` → roda direto no escalador; (d) `force_strong=True` sem
  escalador → `ActionError`; (e) ação normal segue intacta; (f) escalador sinaliza
  `escalate` → `ActionError` (sem loop); (g) o orquestrador envia `max_tokens`
  explícito nas chamadas json (assert via `RecordingClient` ou spy no `router.run`).
- Done: cobertura do sinal de escalada, do `force_strong` e do cap de tokens.

#### Edge cases
- `escalate` sem `escalate_reason`: ok, segue a escalada mesmo assim.
- Escalador sinaliza `escalate` na re-executação → `_normalize_action` rejeita
  (fora da whitelist) → `ActionError`. Sem loop.
- `screen_context` presente: mantém no `user` para a escalada (mesmos messages).
- `force_strong` combinado com `tool: "escalate"` da chain: `force_strong` roda
  primeiro; não re-escala duas vezes.

#### Verification
- Run: `python3 -m pytest tests/ -q`.
- Tests to add/update: `tests/test_agent.py` + `tests/test_escalation.py`.
- Done: escalada por sinal e por `force_strong` cobertas por teste; app.py passa o
  escalador; frontend envia `strong`.

### Inc 4 — OCR LightOnOCR (S)
**Status: done** ✅ (62 passed)
**Depends on:** none
**Unblocks:** 5
**Done criteria:** `OLLAMA_MODEL` padrão = `aipib/LightOnOCR-2-1B:Q8_0`; glm removido
de vlm.py, .env.example e install.ps1; `deepseek-ocr` segue opcional.

#### Files to touch

##### aeye/vlm.py
- What changes: default de `OLLAMA_MODEL` vira `aipib/LightOnOCR-2-1B:Q8_0`;
  docstring atualizada (remove glm).
- Function(s): `OllamaVLM.__init__` — `self.model = model or os.getenv("OLLAMA_MODEL", "aipib/LightOnOCR-2-1B:Q8_0")`.
- Integration points: `describe()`/`model_ready()` (matching por `split(":")[0]` já ok).

##### app.py
- What changes: string de erro `"Rode: ollama pull {model}"` já usa `self.model`
  dinamicamente; conferir se há `glm-ocr` hardcoded na mensagem (em `describe`/
  OCRUnavailable) e trocar para o modelo dinâmico/novo default.
- Integration points: qualquer mensagem de erro que cite `glm-ocr` no fluxo OCR.

##### .env.example
- What changes: `OLLAMA_MODEL=aipib/LightOnOCR-2-1B:Q8_0`; comentário atualizado
  (`deepseek-ocr` como opcional).

##### install.ps1
- What changes: `.SYNOPSIS`/`.DESCRIPTION` e passo de pull usam LightOnOCR; remover
  glm; manter `IncludeDeepSeek`.
- Function(s): `& $OllamaExe pull aipib/LightOnOCR-2-1B:Q8_0`; texto "Baixando o
  modelo de OCR local: aipib/LightOnOCR-2-1B:Q8_0".

#### Edge cases
- `deepseek-ocr` continua disponível via `IncludeDeepSeek`/var manual.
- **Verificar que LightOnOCR funciona pelo caminho OpenAI-compat**: `describe()`
  envia `[{type:"image_url"},{type:"text"}]` via `/v1/chat/completions`. Se
  `aipib/LightOnOCR-2-1B:Q8_0` não for instruction/chat-tuned para esse shape de
  mensagem, o OCR degrada. Fazer um teste manual (enviar uma imagem e ver o texto)
  ANTES de cortar o default; se falhar, manter um caminho de fallback ou validar o
  formato de prompt esperado do modelo.

#### Verification
- Run: `python3 -m pytest tests/ -q` (se houver teste de vlm, ajustar default).
- Tests to add/update: conferir `tests/` por referência a `glm-ocr`.
- Manual: `ollama pull aipib/LightOnOCR-2-1B:Q8_0` e disparar OCR de uma imagem →
  texto extraído corretamente pelo caminho OpenAI-compat.
- Done: nenhuma referência a `glm-ocr` no código/instalador (exceto histórico);
  LightOnOCR comprovadamente extrai texto pelo `describe()`.

### Inc 5 — Docs + .env.example (S)
**Status: done** ✅ (62 passed, node check OK)
**Depends on:** 2, 3, 4
**Unblocks:** none
**Done criteria:** README descreve MiniCPM como orquestrador, escalada para
Claude/API e o novo OCR; `.env.example` completo e consistente.

#### Files to touch

##### README.md
- What changes: fluxo de controle usa MiniCPM local (orquestrador) → API → Claude;
  escalada por sinal; instruções de `ollama pull` do MiniCPM e do LightOnOCR;
  diagrama de arquivos (`llm.py`, `vlm.py`); tabela de troubleshooting.
- Integration points: seções "Controlar o computador", "Custos e privacidade",
  "Arquitetura".

##### .env.example
- What changes: consolida `AEYE_ORCH_MODEL`, `AEYE_ORCH_CHAIN=minicpm,gemini,cerebras`,
  `OLLAMA_MODEL=aipib/LightOnOCR-2-1B:Q8_0`; remove as vars do Needle (Inc 1).
  `AI_FALLBACK_CHAIN` permanece `gemini,cerebras` (chat/OCR) — o MiniCPM entra via
  `AEYE_ORCH_CHAIN`, não via `AI_FALLBACK_CHAIN`.

#### Edge cases
- Documentar como desligar a escalada: `AEYE_ORCH_CHAIN=gemini,cerebras` (sem
  `minicpm`) e/ou remover o `force_strong` na UI.
- Documentar que a cadeia global (`AI_FALLBACK_CHAIN`) continua governando
  `/api/chat` e OCR, independente do orquestrador de ação.

#### Verification
- Run: `node --check web/app.js` (se frontend mexido no Inc 3) + leitura manual do README.
- Tests to add/update: nenhum.
- Done: README e .env.example consistentes entre si e com o código.

## Cross-cutting verification
- `python3 -m pytest tests/ -q` — toda a suíte verde após Inc 5.
- `node --check web/app.js` — frontend intacto.
- Manual (com `AEYE_MCP=1` e MiniCPM puxado): comando de ação → MiniCPM produz a
  ação; derrubar o Ollama → escala para API; comando que pede modelo forte / código →
  MiniCPM emite `escalate` → Claude (se instalado) ou API produz a ação. OCR de imagem →
  usa LightOnOCR.

## Standards / common-mistakes referenced
- `.agents/standards/python.md` — Python 3.10+, funções curtas, `run_in_threadpool`,
  `Sequence[T]`.
- `.agents/common-mistakes/python.md` — lazy imports com guards; não engolir exceções
  sem causa; strong-model failures logados (escalada deve logar o motivo).

## Open questions (CONSIDER from review)
- **Pensar modelo / quant do MiniCPM**: `:latest` pode ser low-bit (2-bit) e crashar
  em schemas de tool aninhados, ou ser thinking model que precisa de `num_predict`
  explícito. O `_run_json` usa `max_tokens or 1024`; considerar subir para 2048 e
  validar a tag no playground.
- **`escalate` no prompt compartilhado**: o sinal `escalate` está no `_system_prompt`
  usado por MiniCPM E pelo escalador (gemini/cerebras/Claude). Confirmar que os
  modelos de API/Claude não escalam em excesso (false positives).
- **Latência**: MiniCPM local deve ser rápido, mas um comando que escala adiciona 2
  chamadas LLM (MiniCPM + escalador) + aprovação. Mensurar no playground.
- **Backward-compat do orquestrador**: quem já tem `.env` sem `AEYE_ORCH_CHAIN`
  ganha `minicpm,gemini,cerebras` por default no `/api/act`. Para manter o MiniCPM
  desligado, definir `AEYE_ORCH_CHAIN=gemini,cerebras`. A cadeia global de chat/OCR
  (`AI_FALLBACK_CHAIN`) não é afetada.
- **Observabilidade da escalada**: o motivo (`escalate_reason`) e o provedor que
  realmente produziu a ação deveriam aparecer como warning na resposta de `/api/act`
  (como o `_call_strong` faz para o OCR) — fora do escopo atual, considerar depois.
- **Structured output do MiniCPM**: validar no playground que
  `jewelzufo/MiniCPM5-1B:latest` emite `{tool, params}` estrito (e o sinal
  `escalate`) via `response_format=json_object` no Ollama, antes de confiar nele
  como orquestrador padrão.

## Out of scope
- Não adicionar tool de `run_code` ao MCP; a escalada é de interpretação, não de execução.
- Não tocar no `pipeline_image`/toggle "modelo forte" do OCR (já usa Claude Code quando
  pedido) — exceto a troca do modelo de OCR.
- Não manter o Needle em nenhuma forma (removido por completo).
