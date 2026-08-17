# AEye — Assistente de Acessibilidade (OCR + IA gratuita + controle por voz)

O AEye transforma o PC do seu amigo (Windows 10/11, AMD Vega 8, 16GB) em um
assistente de acessibilidade **com custo zero**:

- **Lê qualquer coisa**: capturas de tela (PrtScn), fotos de documentos, manuscritos.
- **Formata e explica com IA gratuita**: Google Gemini 2.5 Flash (principal) com
  **fallback automático para Cerebras** (Llama 3.3 70B). Claude é opcional e pago.
- **Controlado pelo celular**: abre a página `http://<IP-do-PC>:8080` no celular
  (mesma rede Wi-Fi) e usa o microfone do teclado para falar.
- **Controla o computador por voz** (opcional): "abre o Word e digita olá" — com
  aprovação antes de cada ação.

---

## Instalação automática (recomendado)

No PC do amigo (Windows 10/11), abra o **Prompt de Comando** ou **PowerShell**
na pasta do projeto e rode:

```
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

O script instala/verifica tudo: Python, dependências, Ollama + `glm-ocr`,
cria o `.env`, libera o firewall e mostra o IP para o celular.

Opções úteis:

```
# Tudo, incluindo controle do PC por voz e Claude Code:
.\install.ps1 -InstallMCP -InstallClaudeCode

# Também baixa o deepseek-ocr (6,7GB, mais preciso em documentos):
.\install.ps1 -IncludeDeepSeek

# Já inicia o AEye ao final:
.\install.ps1 -InstallMCP -Launch
```

Depois de instalar, edite o `.env` (o script abre o Bloco de Notas) e cole as
duas chaves gratuitas. Para rodar o app:

```
.\run.ps1
```

---

## O que precisa instalar no PC do amigo

| Item | Onde | Custo |
|---|---|---|
| Python 3.10–3.12 | https://www.python.org/downloads/ | grátis |
| Google AI Studio (chave Gemini) | https://aistudio.google.com/apikey | grátis (~1.500 req/dia) |
| Cerebras (chave) | https://cloud.cerebras.ai → API Keys | grátis (14.400 req/dia) |
| Ollama (+ modelo `glm-ocr`) | https://ollama.com/download | grátis |
| Node.js (só para controle por voz) | https://nodejs.org | grátis |
| Claude Code (só para o toggle "modelo forte") | `npm install -g @anthropic-ai/claude-code` | usa a assinatura dele |

---

## Passo a passo

### 1. Instalar o Python
Baixe o instalador em https://www.python.org/downloads/ (versão 3.10, 3.11 ou
3.12). **Marque a opção "Add Python to PATH"** antes de clicar em instalar.

### 2. Criar as chaves gratuitas
1. **Gemini**: entre em https://aistudio.google.com/apikey, clique em "Create
   API key" e copie a chave (começa com `AIza...`).
2. **Cerebras**: crie conta em https://cloud.cerebras.ai, menu **API Keys**,
   copie a chave.

### 3. Preparar o projeto
1. Copie a pasta `AEye` para o PC (ex.: `C:\AEye`).
2. Dentro dela, copie o arquivo `.env.example` e renomeie para **`.env`**.
3. Abra o `.env` com o Bloco de Notas e cole as duas chaves:
   ```
   GEMINI_API_KEY=AIza...
   CEREBRAS_API_KEY=...
   ```

### 4. Instalar as dependências
Abra o **Prompt de Comando** (menu Iniciar → digite `cmd`) e rode:

```
cd C:\AEye
pip install -r requirements.txt
```

### 5. Instalar o Ollama + modelo de OCR local (manuscrito)
1. Baixe e instale o **Ollama**: https://ollama.com/download (não precisa de admin).
2. No Prompt de Comando:
   ```
   ollama pull glm-ocr
   ```
   (≈2,2GB. Para mais precisão em documentos longos, opcional: `ollama pull deepseek-ocr` ≈6,7GB.)
3. A Vega 8 usa o backend **Vulkan** (automático no Ollama atual do Windows).
   Para conferir se a GPU está ativa, rode `ollama ps` enquanto o modelo processa
   algo. Se o Ollama escolher a GPU errada (iGPU+dGPU), defina a variável
   `GGML_VK_VISIBLE_DEVICES=0` e reinicie o Ollama.

### 6. Rodar o AEye
No Prompt de Comando:

```
cd C:\AEye
python app.py
```

Você verá algo como `AEye rodando em http://192.168.1.50:8080`.

### 7. Liberar o Firewall (primeira vez)
Quando o Windows perguntar sobre o firewall, **marque "Redes privadas"** e
permita. Sem isso o celular não consegue abrir a página.

### 8. Usar pelo celular
1. Celular e PC na **mesma rede Wi-Fi**.
2. No navegador do celular, abra `http://192.168.1.50:8080` (o IP que apareceu
   no passo 6; se mudar, descubra com `ipconfig` no PC — procure "IPv4").
3. Para falar: toque no campo de texto e use o **microfone do teclado** do celular.

---

## Como usar

### Ler texto (screenshot, foto, documento)
1. No PC: aperte **PrtScn** ou **Win+Shift+S** → o AEye detecta sozinho, extrai,
   formata com a IA gratuita e **cola o resultado pronto no clipboard** (Ctrl+V em
   qualquer app).
2. Ou no celular: botão "Escolher imagem / câmera" → fotografe → escolha o modo:
   - **📄 Texto impresso** — rápido, OCR local (RapidOCR).
   - **✍️ Manuscrito** — usa o modelo local `glm-ocr` (Vulkan).
   - **❓ Perguntar** — pergunta sobre a imagem (ex.: "o que está escrito no topo?").
3. Toque em **Processar**. Marque **🔊 Ler em voz alta** para ouvir no PC.

### Controlar o computador por voz (opcional)
1. Instale o Node.js e, na primeira vez, o `computer-control-mcp-server`:
   ```
   npm install -g @wshobson/mcp-server-computer-control
   ```
2. No `.env`, deixe `AEYE_MCP=1`.
3. Na página, digite (ou fale) ex.: *"abre o Bloco de Notas e digita olá"* →
   **Executar com aprovação** → o AEye mostra a ação que vai fazer → **Aprovar**.
4. **Kill switch**: para cancelar, **segure a tecla Esc no PC** (funciona de
   verdade — o AEye monitora a tecla) ou toque em "Cancelar" na página.

---

## Custos e privacidade

- **Tudo é grátis**: OCR local + Gemini free + Cerebras free. Sem cartão de crédito.
- Se os limites gratuitos incomodarem (muito uso), o Gemini pago custa
  US$0,30 por 1M de tokens de entrada — poucos centavos por mês.
- **Atenção à privacidade**: o *free tier* do Gemini pode usar o que você envia
  para treinar modelos. O conteúdo da tela é sensível. Se preferir, troque a
  ordem no `.env`:
  ```
  AI_FALLBACK_CHAIN=cerebras,gemini
  ```
- **Proteja com PIN (recomendado)**: defina `AEYE_PIN=1234` no `.env`. Sem PIN,
  qualquer dispositivo na sua rede Wi-Fi pode usar o AEye (inclusive controlar o
  PC). Com PIN, o navegador pede uma vez e guarda no próprio celular.
- Claude **não depende de API**: o toggle "⭐ Usar modelo forte" aciona o
  **Claude Code instalado no PC** (usa a conta/assinatura do seu amigo, sem chave
  de API — a Anthropic não dá suporte a terceiros). Se o Claude Code não estiver
  disponível, o AEye cai sozinho para a cadeia gratuita (Gemini → Cerebras).
  Instale o Claude Code (opcional) com:
  ```
  npm install -g @anthropic-ai/claude-code
  claude        # roda uma vez para logar
  ```

---

## (Opcional) NVIDIA NeMo Switchyard

O Switchyard é um proxy em Rust que roteia chamadas de API entre provedores
(OpenAI, Anthropic, Ollama...). O AEye já funciona sem ele (modo direto);
o Switchyard serve para quem usa **Claude Code/API** no PC.

No Windows é preciso compilar (instalar Rust + Visual Studio Build Tools):
```
cargo install --locked switchyard-server
cd C:\AEye\switchyard
set GEMINI_API_KEY=...
set CEREBRAS_API_KEY=...
switchyard-server --config routes.toml --dry-run
switchyard-server --config routes.toml --host 127.0.0.1 --port 4000
```
Teste: `curl http://localhost:4000/health`. A configuração `routes.toml` usa o
schema oficial do projeto (verificado contra a documentação do NVIDIA-NeMo).

---

## Testes (para quem desenvolve)

```
pip install pytest
pytest tests/ -q
```

---

## Estrutura do projeto

```
AEye/
├── install.ps1               # instalador automático (Python, Ollama, .env, firewall)
├── run.ps1                   # inicia o servidor
├── app.py                    # servidor FastAPI (tudo junto)
├── aeye/
│   ├── llm.py                # provedores: Gemini, Cerebras, Claude Code, Anthropic (abstração)
│   ├── router.py             # cadeia de fallback + escalada automática
│   ├── ocr.py                # RapidOCR (CPU, texto impresso)
│   ├── vlm.py                # Ollama + glm-ocr (manuscrito, Vulkan)
│   ├── agent.py              # comandos de voz → ações + executor MCP
│   ├── clipboard_watcher.py  # detecta PrtScn e processa sozinho
│   ├── killswitch.py         # segurar Esc cancela a ação em andamento
│   └── tts.py                # ler em voz alta (Windows SAPI)
├── web/                      # interface (celular/PC)
├── switchyard/routes.toml    # config do Switchyard (opcional)
├── tests/                    # testes com mocks (35 testes)
├── .env.example              # modelo das chaves
└── requirements.txt
```

---

## Problemas comuns

| Sintoma | Solução |
|---|---|
| Celular não abre a página | Firewall: libere Python/uvicorn em "Redes privadas"; confira o IP (`ipconfig`); PC e celular na mesma rede. |
| "Nenhum provedor de LLM configurado" | Preencha `GEMINI_API_KEY` e `CEREBRAS_API_KEY` no `.env` e reinicie. |
| "Ollama não está rodando" | Abra o app do Ollama (bandeja) antes de usar o modo manuscrito. |
| "Modelo 'glm-ocr' não baixado" | Rode `ollama pull glm-ocr`. |
| "Nenhum texto detectado" | Foto mais nítida/mais perto; ou mude para o modo "✍️ Manuscrito". |
| "Controle do PC não habilitado" | `AEYE_MCP=1` no `.env` + `npm install -g @wshobson/mcp-server-computer-control` + Node.js instalado. |
| Gemini estourou o limite (429) | Automático: o AEye cai para Cerebras. Se acontecer muito, aumente para o Gemini pago. |
| "⭐ Modelo forte" avisa que o Claude Code está indisponível | Instale: `npm install -g @anthropic-ai/claude-code` e rode `claude` uma vez para logar. Enquanto isso, o AEye usa a cadeia gratuita. |
| O instalador parou no meio | Rode de novo — ele pula etapas já feitas (`-SkipPython`, `-SkipOllama`, `-SkipNode` ignoram partes específicas). |
