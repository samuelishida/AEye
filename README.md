# AEye — Assistente de Acessibilidade (OCR + IA gratuita + controle por voz)

O **AEye** transforma um PC (Windows 10/11, AMD Vega 8, 16GB de RAM) em um
assistente de acessibilidade **com custo zero**:

- **Lê qualquer coisa**: capturas de tela (PrtScn), fotos de documentos e manuscritos.
- **Formata e explica com IA gratuita**: Google Gemini 2.5 Flash (principal) com
  **fallback automático para Cerebras** (Llama 3.3 70B).
- **Controlado pelo celular**: abra `http://<IP-do-PC>:8080` no celular (mesma
  rede Wi-Fi) e use o microfone do teclado para falar.
- **Controla o computador por voz** (opcional): *"abre o Bloco de Notas e digita
  olá"* — sempre com **aprovação antes de cada ação**.

---

## Como funciona (em resumo)

O AEye é orquestrado por dois modelos locais: o **MiniCPM** é o **cérebro** que
interpreta o que você pede, e o **LightOnOCR** faz a leitura de imagens. Ambos
rodam localmente, com APIs gratuitas como suporte:

| Camada                     | Local? | Função                                        |
| -------------------------- | ------ | --------------------------------------------- |
| **MiniCPM** (`5-1B`)       | local  | **Principal** — interpreta comandos → ações    |
| **LightOnOCR** (`1B Q8`)   | local  | OCR de manuscrito (Vulkan na Vega 8)           |
| RapidOCR                   | local  | OCR de texto impresso (rápido, CPU)            |
| Gemini 2.5 Flash           | nuvem  | Formata/explica texto (principal na nuvem)     |
| Cerebras (Llama 3.3 70B)   | nuvem  | Fallback automático                            |
| Claude Code (opcional)     | local  | Toggle "⭐ Forçar modelo forte"                |

**Dois servidores Ollama** para não disputarem memória na Vega 8:

- **porta 11434** → orquestrador **MiniCPM** (`OLLAMA_URL_ORCH`) — o cérebro
- **porta 11435** → OCR/VLM **LightOnOCR** (`OLLAMA_URL`)

Os scripts `run.sh`/`run.ps1` sobem os dois automaticamente se estiverem fora do
ar.

---

## Instalação

### Windows (recomendado)

No PC (Windows 10/11), abra o **PowerShell** na pasta do projeto e rode:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

O script instala/verifica tudo: Python, dependências, **dois servidores Ollama +
os modelos LightOnOCR e MiniCPM**, cria o `.env`, libera o firewall e mostra o IP
para o celular.

Opções úteis:

```powershell
# Tudo, incluindo controle do PC por voz e Claude Code:
.\install.ps1 -InstallMCP -InstallClaudeCode

# Também baixa o deepseek-ocr (6,7GB, mais preciso em documentos):
.\install.ps1 -IncludeDeepSeek

# Já inicia o AEye ao final:
.\install.ps1 -InstallMCP -Launch
```

### Linux (Ubuntu/Debian)

```bash
chmod +x install.sh run.sh
./install.sh                 # base
./install.sh --mcp --claude  # controle do PC por voz + Claude Code
./run.sh                     # inicia o servidor
```

### Rodar o servidor

```powershell
.\run.ps1      # Windows
./run.sh       # Linux
```

Os dois servidores Ollama sobem sozinhos; o AEye fica em
`http://localhost:8080` e mostra o IP para usar no celular.

> **Na primeira vez**, o Windows pergunta sobre o firewall: **marque "Redes
> privadas"** e permita. Sem isso o celular não consegue abrir a página.

---

## Chaves gratuitas (criar e colar no `.env`)

1. Copie `.env.example` e renomeie para **`.env`**.
2. Crie as duas chaves gratuitas e cole no arquivo:

| Serviço       | Onde criar                                   | Chave                  |
| ------------- | --------------------------------------------- | ---------------------- |
| **Gemini**    | https://aistudio.google.com/apikey            | `GEMINI_API_KEY=AIza...` |
| **Cerebras**  | https://cloud.cerebras.ai → **API Keys**      | `CEREBRAS_API_KEY=...`   |

Exemplo:

```
GEMINI_API_KEY=AIza...
CEREBRAS_API_KEY=...
```

---

## Como usar

### Ler texto (screenshot, foto, documento)

1. **No PC**: aperte **PrtScn** ou **Win+Shift+S** → o AEye detecta sozinho,
   extrai, formata com a IA gratuita e **cola o resultado pronto no clipboard**
   (Ctrl+V em qualquer aplicativo).
2. **No celular**: botão **"Escolher imagem / câmera"** → fotografe → escolha o
   modo:
   - **📄 Texto impresso** — rápido, OCR local (RapidOCR).
   - **✍️ Manuscrito** — usa o modelo local LightOnOCR (Vulkan).
   - **❓ Perguntar** — faça uma pergunta sobre a imagem
     (ex.: "o que está escrito no topo?").
3. Toque em **Processar**. Marque **🔊 Ler em voz alta** para ouvir no PC.

### Controlar o computador por voz (opcional)

1. Instale o **Node.js** e, na primeira vez, o servidor de controle:
   ```
   npm install -g @wshobson/mcp-server-computer-control
   ```
2. No `.env`, deixe `AEYE_MCP=1`.
3. Na página, digite (ou fale) ex.: *"abre o Bloco de Notas e digita olá"* →
   **Executar com aprovação** → o AEye mostra a ação que vai fazer → **Aprovar**.
4. **Cancelar**: segure a tecla **Esc** no PC (o AEye monitora de verdade) ou
   toque em "Cancelar" na página.

#### Como o comando é interpretado (orquestrador + escalada)

1. O comando vai primeiro para o **MiniCPM 5-1B** (local, via Ollama) — rápido e
   privado. Se ele estiver offline, o AEye escala sozinho para a API gratuita
   (Gemini → Cerebras).
2. Se o MiniCPM não conseguir executar, o usuário marcar **"⭐ Forçar modelo
   forte"**, ou a tarefa exigir escrever/executar código além da capacidade, o
   AEye **escala** para o **Claude Code** (se instalado) → API Anthropic → cadeia
   gratuita.

---

## Configuração (variáveis do `.env`)

| Variável               | Padrão                                   | Controle                                   |
| ---------------------- | ---------------------------------------- | ------------------------------------------ |
| `GEMINI_API_KEY`       | — (obrigatória)                          | Gemini 2.5 Flash (chat/OCR principal)      |
| `CEREBRAS_API_KEY`     | — (obrigatória)                          | Cerebras Llama 3.3 70B (fallback)          |
| `AI_FALLBACK_CHAIN`    | `gemini,cerebras`                        | Ordem da cadeia de chat/OCR                |
| `OLLAMA_URL`           | `http://localhost:11435`                 | Servidor Ollama de OCR/VLM (LightOnOCR)    |
| `OLLAMA_MODEL`         | `aipib/LightOnOCR-2-1B:Q8_0`             | Modelo de manuscrito                       |
| `OLLAMA_MODEL_TEXT`    | `qwen3:4b`                               | Texto offline (fallback extra, opcional)   |
| `OLLAMA_URL_ORCH`      | `http://localhost:11434`                 | Servidor Ollama do orquestrador (MiniCPM)  |
| `AEYE_ORCH_MODEL`      | `jewelzufo/MiniCPM5-1B:latest`           | Modelo do orquestrador                     |
| `AEYE_ORCH_CHAIN`      | `minicpm,gemini,cerebras`                | Ordem da cadeia do orquestrador            |
| `AEYE_ORCH_MAX_TOKENS` | `2048`                                   | Cap de tokens do caminho JSON do orquestrador |
| `AEYE_MCP`             | `0`                                      | `1` = habilita controle do PC por voz      |
| `AEYE_PIN`             | (vazio)                                  | PIN de acesso pelo celular (recomendado)   |

> **Para desligar o MiniCPM** (usar só API no orquestrador):
> `AEYE_ORCH_CHAIN=gemini,cerebras`.

### Puxando os modelos (se o instalador não o fez)

```
# OCR/manuscrito → servidor 11435
OLLAMA_HOST=127.0.0.1:11435 ollama pull aipib/LightOnOCR-2-1B:Q8_0

# Orquestrador → servidor 11434
OLLAMA_HOST=127.0.0.1:11434 ollama pull jewelzufo/MiniCPM5-1B:latest
```

> **deepseek-ocr** (opcional, ~6,7GB, mais preciso em documentos longos):
> `OLLAMA_HOST=127.0.0.1:11435 ollama pull deepseek-ocr` e troque `OLLAMA_MODEL`.

---

## Custos e privacidade

- **Tudo é grátis**: OCR local + MiniCPM local + Gemini free + Cerebras free. Sem
  cartão de crédito.
- O orquestrador de ações roda **100% local** (MiniCPM 1B via Ollama) — seu
  comando de ação não sai do PC, a menos que você marque **"⭐ Forçar modelo
  forte"** ou o MiniCPM peça escalada (Claude/API).
- Se os limites gratuitos incomodarem, o Gemini pago custa ~US$0,30 por 1M de
  tokens de entrada — poucos centavos por mês.
- **Privacidade**: o *free tier* do Gemini pode usar o que você envia para treinar
  modelos, e o conteúdo da tela é sensível. Para preferir a Cerebras, troque a
  ordem:
  ```
  AI_FALLBACK_CHAIN=cerebras,gemini
  ```
- **Proteja com PIN (recomendado)**: defina `AEYE_PIN=1234` no `.env`. Sem PIN,
  qualquer dispositivo na sua rede Wi-Fi pode usar o AEye (inclusive controlar o
  PC). Com PIN, o navegador pede uma vez e guarda no próprio celular.
- **Claude Code** não depende de API: o toggle **"⭐ Forçar modelo forte"** usa o
  **Claude Code instalado no PC** (a conta/assinatura do usuário — a Anthropic não
  dá suporte a terceiros). Se não estiver disponível, o AEye cai sozinho para a
  cadeia gratuita. Instale (opcional) com:
  ```
  npm install -g @anthropic-ai/claude-code
  claude        # roda uma vez para logar
  ```

---

## Estrutura do projeto

```
AEye/
├── install.ps1 / install.sh   # instaladores (Windows / Linux)
├── run.ps1 / run.sh           # sobem os 2 Ollamas + o servidor
├── app.py                     # servidor FastAPI
├── aeye/
│   ├── llm.py                 # provedores: Gemini, Cerebras, Claude Code, Anthropic, MiniCPM
│   ├── router.py              # cadeia de fallback + escalada automática
│   ├── ocr.py                 # RapidOCR (CPU, texto impresso)
│   ├── vlm.py                 # LightOnOCR via Ollama (manuscrito, Vulkan)
│   ├── agent.py               # comandos → ações (orquestrador MiniCPM + escalada)
│   ├── clipboard_watcher.py   # detecta PrtScn e processa sozinho
│   ├── killswitch.py          # segurar Esc cancela a ação em andamento
│   └── tts.py                 # ler em voz alta
├── web/                       # interface (celular/PC)
├── tests/                     # testes com mocks (62)
├── .env.example               # modelo das chaves
└── requirements.txt
```

---

## Desenvolvimento (testes)

```
pip install pytest
pytest tests/ -q
```

---

## Problemas comuns

| Sintoma                                                  | Solução                                                                                             |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Celular não abre a página                               | Firewall: libere Python/uvicorn em "Redes privadas"; confira o IP (`ipconfig`); PC e celular na mesma rede. |
| "Nenhum provedor de LLM configurado"                      | Preencha `GEMINI_API_KEY` e `CEREBRAS_API_KEY` no `.env` e reinicie.                                     |
| "Ollama não está rodando"                                | Os scripts `run.sh`/`run.ps1` sobem os 2 sozinhos; se falhar, abra o app do Ollama na bandeja. |
| Modelo não baixado                                       | Rode os `ollama pull` da seção [Configuração](#configuração-variáveis-do-env).                          |
| "Nenhum texto detectado"                                  | Foto mais nítida/mais perto; ou mude para o modo "✍️ Manuscrito".                                          |
| "Controle do PC não habilitado"                          | `AEYE_MCP=1` no `.env` + `npm install -g @wshobson/mcp-server-computer-control` + Node.js. |
| Gemini estourou o limite (429)                            | Automático: o AEye cai para Cerebras. Se ocorrer muito, aumente para o Gemini pago. |
| "⭐ Forçar modelo forte" diz que o Claude Code está indisponível | Instale `npm install -g @anthropic-ai/claude-code` e rode `claude` uma vez. Enquanto isso, usa a cadeia gratuita. |
| O instalador parou no meio                                | Rode de novo — ele pula etapas já feitas (`-SkipPython`, `-SkipOllama`, `-SkipNode`). |
