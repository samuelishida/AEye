# CODE REVIEW — AEye (validação iGPU Intel UHD 770)

Data: 2026-09-27 · HEAD `ef9ef17` + diff não-commitado (11 arquivos, +207/−53)
Escopo: `app.py`, `aeye/*` (agent, llm, router, ocr, vlm, tts, clipboard_watcher,
killswitch), `web/*`, `run.sh`, `install.sh`, `tests/*`, `.env*`.
Restrição honrada em toda a validação: **nenhum workload em dGPU** — todos os
serviços de teste rodam na iGPU (Vulkan0) em portas próprias (11436/11437).

---

## 1. Testes

```
65 passed in 2.21s
```
Totalmente offline/mocked (sem rede, sem Ollama). Cobrem o smoke do app,
rotas de fallback de LLM, TTS, clipboard watcher e killswitch.

## 2. Validação real na iGPU (path local, sem chaves)

- **OCR — LightOnOCR-2-1B:Q8_0** na 11437 (29/29 camadas offload Vulkan0 iGPU):
  saída correta via `POST /api/ocr` do app e direto em `/v1`.
- **Orquestrador — MiniCPM5-1B** na 11436 (25/25 camadas Vulkan0): resposta
  gerada; o `/api/act` completo, porém, atinge o timeout de 60 s (ver §4/4).
- **Benchmarks (config corrigida, 2026-09-27)** — log `/tmp/aeye-bench/run-2.log`:

  | doc | in/out tok | total | TTFT (warm) | gen. | qualidade |
  |---|---|---|---|---|---|
  | curto | 925/47 | 2.9 s | 0.18 s | 17.2 tok/s | 2/2 |
  | fatura | 2190/338 | 31.6 s | 0.14 s | 11.7 tok/s | 4/4 |
  | memorando | 2740/274 | 29.7 s | 0.16 s | 9.6 tok/s | 4/4 |

  Média de geração **12.8 tok/s**; cold-load ~26.5 s. Todos os 10 marcadores
  extraídos (`QUALIDADE: OK`).

## 3. Bug principal encontrado: Flash Attention corrompe OCR na iGPU

**Sintoma:** LightOnOCR na iGPU (llama.cpp Vulkan) com flash attention ligado
(padrão) produz **mojibake multilíngue** (" is aეეეЕкО\n виЗ ТСИЕ..."), 0/9
marcadores, latência normal.

**Causa raiz:** os kernels de flash attention do backend Vulkan corrompem o KV
de visão. A/B validado:
- FA on (2 binários diferentes, processos frios) → garbage;
- `OLLAMA_FLASH_ATTENTION=0` → saída correta;
- `GGML_VK_DISABLE_F16=1` não altera → F16 está de fora.

**Correção production (já aplicada a `run.sh`/`.env`/`.env.example`):**
```
OLLAMA_FLASH_ATTENTION=0      # obrigatório na iGPU p/ OCR correto
OLLAMA_KV_CACHE_K_TYPE=q8_0   # ~40% menos RAM de KV, sem perda medida
```
**Conflito descoberto:** cache **V** quantizado exige flash attention
(`quantized V cache requires flash_attn to be enabled`) — como FA está off,
V fica f16. Para permitir K≠V foi feito patch no repo `Code/ollama`
(`envconfig/config.go` + `llm/llama_server.go`) adicionando
`OLLAMA_KV_CACHE_K_TYPE` / `OLLAMA_KV_CACHE_V_TYPE`; binário rebuildado em
`build/ollama-ngram2` (docker `golang:1.26`, `-buildvcs=false`) e em uso pelos
servidores 11436/11437. **Instalação system-wide** (`/usr/local/bin/ollama`)
exige root — pendente de `sudo` do usuário.

**Gotcha relacionada:** neste build o `/api/chat` nativo com campo `images`
**descarta a imagem silenciosamente** (EVAL=22, transcrição alucinada). Sempre
usar `/v1/chat/completions` com `image_url` no content — `aeye/vlm.py` já usa o
caminho correto, então o app não é afetado; benchmark/diagnósticos precisam.

## 4. Achados de correctness

### 4.1 (Médio) Timeout de 60 s em `/api/act` vs. MiniCPM thinking na iGPU
`OpenAICompatClient(timeout=60)` em `aeye/llm.py:191` é menor que o tempo de
thinking do MiniCPM5-1B na iGPU (90–140 s p/ saída curta) → `/api/act` falha
com timeout no caminho local. (O path VLM já usa 180 s em `aeye/vlm.py:91`.)
**Sugestão:** `AEYE_ORCH_TIMEOUT` (default 180 s) lido do `.env`, como já
ocorre com `CLAUDE_CODE_TIMEOUT`.

### 4.2 (Baixo) `run.sh` — `local` multi-declaração
`local u="$1" v="${u##*:}"` num único statement: em bash 5.2 os RHS são
expandidos **antes** de qualquer atribuição (v saía vazio). Corrigido no diff
atual (linhas separadas). Mantido como anti-padrão documentado.

### 4.3 (Baixo) `aeye/ocr.py` e `aeye/vlm.py` — duplicação de prompt
O prompt de OCR se repete em dois módulos; unificar numa constante para
evitar drift (o benchmark usa uma terceira cópia).

### 4.4 (OK) `web/app.js` — saída de modelo renderizada com `textContent`
Não há `innerHTML` com texto de backend (verificado: `div.textContent = text` e
co.); a saída de OCR/LLM vai para o DOM como texto puro. Nenhum risco de XSS
reflexivo do modelo — **nada a fazer**.

## 5. Achados de segurança

- **`AEYE_PIN` vazio = sem auth de rede**: qualquer dispositivo da Wi-Fi alcança
  `/api/*` (inclusive `/api/act`, que executa ações no computador via MCP).
  Documentado no `.env.example`, mas sem aviso logado em boot quando vazio.
  **Sugestão:** log `WARNING` explícito em `app.py` quando `AEYE_PIN` está vazio.
- **Bind em 0.0.0.0**: necessário p/ celular na rede; combinado com PIN vazio,
  é a maior superfície do app. Sem changes sugeridas além do aviso.
- Chaves de nuvem (Gemini/Cerebras) só trafegam em chamadas saídas do próprio
  processo; nenhuma loga o header de auth (verificado em `aeye/llm.py`).
- MCP (`AEYE_MCP=1`) executa `npx -y` do comando configurável — o comando do
  `.env` é efetivamente código local confiável; aceitável para app local, mas
  o campo `COMPUTER_CONTROL_MCP_CMD` deveria ser validado contra injeção
  (hoje é usado literalmente pelo subprocess).
- **Segredos não estão no repo**: `.env` está em `.gitignore`; `.env.example`
  só tem placeholders. OK.

## 6. Maintainability

- Estrutura limpa: `aeye/` separa concerns (router/llm/vlm/tts/killswitch),
  `app.py` fina, injeção de dependência por parâmetro nos testes → 65 testes
  rápidos e offline.
- Logging estruturado (middleware + `request_id` via `contextvars`) é bom e
  testável (aprendizado em `.agents/learnings/aeye-robustness.md`).
- `run.sh` agora: parses portas do `.env`, exporta a config iGPU validada.
  `run.ps1` **não recebeu a mesma atualização** (Windows/AMD Vega 8 não têm o
  bug FA-Vulkan, mas a divergência de comportamento entre sh/ps1 deve ser
  documentada no README).
- `install.sh` OK; sugere aviso prévio quando `OLLAMA_FLASH_ATTENTION` não
  estiver definido em máquina com Vulkan iGPU.
- Duplicação prompt OCR (§4.3) e as três cópias de prompt de OCR entre
  `aeye/ocr.py`, `aeye/vlm.py` e o benchmark são o item mais fácil de
  consolidar.
- Arquivos não rastreados no root (`ctx.txt`, `.vscode/`, `.pi/`) — candidato a
  `.gitignore`.

## 7. Estado final da validação

| Item | Estado |
|---|---|
| Testes (offline) | ✅ 65 passed |
| OCR real na iGPU | ✅ correto (config FA=0 + K=q8_0) |
| Orquestrador na iGPU | ✅ responde; ⚠️ timeout 60 s no §4.1 |
| Benchmark válido | ✅ 12.8 tok/s, 10/10 marcadores |
| `run.sh`/`.env` persistidos | ✅ com config validada |
| Binário ollama com K/V split | ✅ rebuildado (`build/ollama-ngram2`); install system-wide pendente de sudo |
| dGPU | ✅ nunca tocada (11434/Qwen do usuário intacto) |

## 8. Pendências sugeridas (ordem de valor)
1. `AEYE_ORCH_TIMEOUT` (180 s) para `/api/act` com MiniCPM local (§4.1).
2. Aviso logado quando `AEYE_PIN` vazio (§5).
3. Unificar prompt de OCR (§4.3).
4. Instalar `ollama-ngram2` system-wide com sudo + espelhar config no `run.ps1`.
