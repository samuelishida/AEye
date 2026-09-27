# AGENTS.md — Guia para agentes de IA (Claude Code / Codex) trabalhando no AEye

> **Leitura essencial antes de modificar qualquer coisa neste repositório.**
> Este projeto é o **AEye** — um assistente de acessibilidade local, todo em
> português, feito para ser usado por **usuários cegos**. Os consumidores
> finais interagem por voz e por áudio; os agentes (você) interagem por código.
> Se um agente errar aqui, o efeito é direto: uma pessoa cega fica sem
> conseguir ler a tela. Trate os caminhos críticos (OCR, roteamento, TTS)
> como código de missão.

---

## 1. O que é o AEye (em 10 segundos)

- Servidor **FastAPI** local (`app.py`, porta padrão **8080**) + UI web
  acessível em `web/` (HTML+JS puro, sem build step, sem dependências npm).
- **Dois cérebros locais via Ollama**:
  - **Orquestrador** — `jewelzufo/MiniCPM5-1B:latest` (interpreta comandos
     de voz → ações).
  - **OCR** — `aipib/LightOnOCR-2-1B:Q8_0` (lê imagens: PrtScn, fotos,
     manuscritos).
- **Fallback na nuvem** (quando configurado no `.env`): Gemini 2.5 Flash,
   Cerebras, Claude Code — nunca obrigatórios; o AEye funciona 100% offline.
- **Portas dos servidores Ollama:** lidas do `.env` (`OLLAMA_URL_ORCH` para
   o orquestrador, `OLLAMA_URL` para o OCR); nos padrões do projeto são
   11434/11435. Em modo iGPU o `.env` define as portas reais.

### Fluxo de uma imagem

```
PrtScn/foto   →   /api/upload (app.py)   →   aeye/ocr.py
                                        →    Ollama /v1/chat/completions (OCR)
                                        →    texto   → aeye/router.py (orquestrador,
                                        →            ou cadeia na nuvem)
                                        →    resposta formatada  →  TTS (aeye/tts.py)
                                                               →   áudio no celular
```

> **Nota de ambiente:** detalhes de máquina específica (GPU local, portas em
> uso, binário custom, store de modelos, processos "mãos ao longe") ficam no
> **`LOCAL.md`** — arquivo local, **não versionado**. Cada desenvolvedor
> mantém o seu próprio `LOCAL.md`.

---

## 2. Comandos do dia a dia

```bash
./install.sh                 # cria .venv + dependências (primeiro uso)
./run.sh                     # sobe Ollama(s) se preciso + app em :8080
./doctor.sh                  # checagem completa: venv, GPU, portas, modelos, OCR real, pytest
.venv/bin/python -m pytest   # suíte de testes (66 testes; passa em ~2s)
```

`doctor.sh` é o seu **verificador de regressão principal**. Roda um OCR real
de ponta a ponta numa imagem de teste e compara a saída exata (`AEYE DOC OK
42`). Se o doctor passa, o sistema está sadio. Se o OCR sai com letra
estranha/repetida, é o bug de Flash Attention (§4.1) — pare e verifique o
env antes de mexer em código.

### Modelo de teste rápido de OCR (sem subir o app)

```python
# com o servidor OCR no ar (porta lida do .env; veja LOCAL.md):
import base64, json, urllib.request
png = open("qualquer.png","rb").read()
body = json.dumps({"model":"aipib/LightOnOCR-2-1B:Q8_0","messages":[{"role":"user",
       "content":[{"type":"image_url","image_url":{"url":"data:image/png;base64,"+base64.b64encode(png).decode()}},
                  {"type":"text","text":"Descreva o texto da imagem."}]}]}).encode()
req = urllib.request.Request("http://127.0.0.1:11437/v1/chat/completions", body,
       headers={"Content-Type":"application/json"})
print(json.load(urllib.request.urlopen(req, timeout=300))["choices"][0]["message"]["content"])
```

**Nota:** use SEMPRE o endpoint **`/v1/chat/completions`** com `image_url`
para OCR. O endpoint nativo `/api/chat` com campo `images` **descarta a
imagem silenciosamente** nesta build do Ollama — o modelo alucina. Não
"corrija" `aeye/ocr.py` para voltar ao endpoint nativo.

---

## 3. Arquitetura (mapa dos arquivos)

```
app.py                     # FastAPI: upload, TTS, killswitch, CORS, auth local
run.sh / run.ps1           # bootstrap: sobem Ollama + app. run.sh tem modo iGPU
doctor.sh                  # diagnóstico de 6 seções (venv, GPU, portas, modelos, OCR, pytest)
install.sh / install.ps1   # setup do venv
.env / .env.example        # configuração (o .env é local, não versionado)
LOCAL.md                   # estado da máquina local (NÃO versionado — cada dev o seu)
web/                       # UI acessível: index.html + app.js + style.css (sem build)

aeye/
   ocr.py                  # cliente OCR (LightOnOCR via Ollama /v1) + RapidOCR local p/ impresso
   llm.py                  # cadeia de LLMs locais + nuvem, fallbacks, client Claude Code
   router.py               # o "cérebro": decide OCR-vs-LLM-vs-nuvem; RouterExhausted se esgota
   vlm.py                  # visão+linguagem (fotos de documentos, manuscrito)
   agent.py                # ações por voz (parse_command/validate_action) — SEMPRE com aprovação
   tts.py                  # motor de TTS (pthreads; guarda com counter de geração)
   clipboard_watcher.py    # escuta de clipboard (poll floor 0.1s, fallback 0.5s)
   killswitch.py           # parada de emergência por voz

tests/                     # pytest puro; conftest mocka rede/ollama — NUNCA precisa de GPU
```

### Convenções de código

- **Idioma:** tudo em **pt-BR** — docstrings, comentários, nomes de funções
   quando naturais, mensagens de erro, UI. Não traduza para inglês.
- **Indentação nos testes:** os arquivos em `tests/` usam **indentação de 1
   espaço** (não 4). Ao editar, **preserve a indentação existente** — não
   "corrija" para 4 espaços.
- **Sem novas dependências** sem discussão explícita: o projeto roda em
   máquinas modestas (16 GB, iGPU).
- **Cada requisição** carrega um `request_id` via contextvar e aparece no
   log estruturado. Ao adicionar logs, use o logger já configurado
   (`logging.getLogger(__name__)`) — ele já injeta o `request_id`.
- **Ações do agente por voz** (`aeye/agent.py`) **nunca** executam sem o
   passo de aprovação. Não pule validação.

---

## 4. Armadilhas conhecidas (lições pagas a sangue)

### 4.1 Flash Attention na iGPU corrompe a visão (CRÍTICO)
Com `OLLAMA_FLASH_ATTENTION` ligado (padrão), a atenção flash sobre Vulkan
**corrompe as embeddings de visão** no iGPU Intel: o OCR sai como **mojibake
multilíngue** (palavras de idiomas que ninguém pediu, caracteres repetidos).
O flag de saída parece 200 OK — só a *qualidade* do texto está errada.
**Fix permanente: `OLLAMA_FLASH_ATTENTION=0`** — está hardcoded no modo
iGPU do `run.sh`. Se o OCR do doctor passar a falhar com letras estranhas,
a causa é 95% essa variável ter sido derrubada.

### 4.2 KV cache: K=q8_0, V=f16
Quanto KV cache para o AEye na iGPU significa **`OLLAMA_KV_CACHE_K_TYPE=q8_0`
com V em f16** (a quantização de V só é ativa com FA ligado, o que é
proibido por §4.1). Exige um binário custom do Ollama com patch local
(detalhes e build no `LOCAL.md`): `appendKVCacheArgs` em
`llm/llama_server.go` + testes em `llm/llama_server_test.go`. Não faça
upgrade do Ollama upstream sem reaplicar esse patch — e nunca substitua
`/usr/local/bin/ollama` (root-owned, serve a dGPU) sem aprovação explícita
do usuário. Raiz do problema e benchmark em `.agents/learnings/igpu-vulkan-flash-attention.md`.

### 4.3 Ollama nativo descarta imagens no endpoint /api/chat
Ver §2. Symptom: 200 OK, resposta plausível mas desalinhada com a imagem.

### 4.4 Endereços/estados voláteis
- Os processos "mãos ao longe" (Ollama principal, outros workloads do
  usuário) e as portas em uso são específicos de cada máquina — consulte o
  `LOCAL.md` antes de reiniciar, matar ou ocupar qualquer coisa.
- O binário do Ollama em modo iGPU é executado do **path de build do repo** —
  se esse repo for limpo/movido, o modo iGPU do AEye quebra com erro claro
  no `run.sh` (ele valida executabilidade).

### 4.5 Edição de shell-script via regex é perigosa neste ambiente
Uma substituição de regex num `run.sh` (havia `\$1` num grep) produziu
**corrupção em cascata de 16 mil linhas** num script de 51 linhas.
**Regra: edite scripts shell com strings exatas ou reescreva o arquivo
inteiro. Nunca regex multi-linha em .sh.**

---

## 5. Definição de pronto (quando o trabalho está feito)

1. `./doctor.sh` → **11 OK | 0 falhas** (inclui OCR real + pytest).
2. O usuário (pessoa cega) consegue: abrir `http://localhost:8080` no
   celular, enviar um PrtScn, ouvir a resposta — sem intervenção no PC.
3. Nenhum processo "mãos ao longe" (lista no `LOCAL.md`) foi tocado.
4. Sem novas dependências; `web/` continua sem build step; idioma pt-BR.

## 6. Checklist do agente antes de commitar

- [ ] `./doctor.sh` verde
- [ ] `.env.example` atualizado se houve nova chave
- [ ] `run.sh` e `doctor.sh` espelhados (mesmas variáveis GPU no modo iGPU)
- [ ] Acentuação correta em pt-BR (especialmente em `aeye/tts.py` — já foi
  corrigido no passado; `python3 -c "print('…')"` para conferir)
- [ ] Indentação de 1 espaço preservada nos testes
- [ ] Nenhum toque nos processos "mãos ao longe" do `LOCAL.md`, em
  `/usr/local/bin/ollama`, ou na dGPU
- [ ] Nada do `LOCAL.md` vazou para arquivos versionados