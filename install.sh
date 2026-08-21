#!/usr/bin/env bash
# AEye — instalador para Linux (Ubuntu/Debian, também funciona em outros).
# Instala/verifica tudo o que o AEye precisa:
#   * Python 3.10+ + ambiente virtual + dependências pip
#   * Ollama + aipib/LightOnOCR-2-1B:Q8_0 (OCR local)
#   * Ollama + jewelzufo/MiniCPM5-1B:latest (orquestrador local de ações)
#   * [opcional] --mcp: Node.js + computer-control-mcp-server (controle do PC)
#   * [opcional] --claude: Claude Code (toggle "modelo forte")
#   * Cria o .env a partir do .env.example
#   * Custo: US$ 0 (Gemini free + Cerebras free + OCR local)
#
# Uso:
#   ./install.sh
#   ./install.sh --mcp --claude --launch
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$ROOT/.venv/bin/python"

# Flags
DO_MCP=0
DO_CLAUDE=0
DO_LAUNCH=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mcp)    DO_MCP=1 ;;
        --claude) DO_CLAUDE=1 ;;
        --launch) DO_LAUNCH=1 ;;
        -h|--help)
            echo "Uso: $0 [--mcp] [--claude] [--launch]"
            exit 0 ;;
        *) echo "Opção desconhecida: $1" >&2; exit 1 ;;
    esac
    shift
done

step() { echo; echo "==> $1" ; }
ok()   { echo "    OK   $1"; }
warn() { echo "    !    $1"; }
fail() { echo "    ERRO $1"; }

# --------------------------------------------------------------------------- #
step "AEye — instalador Linux (custo zero)"
echo "    Pasta do projeto: $ROOT"

command -v python3 >/dev/null 2>&1 || { fail "python3 não encontrado. Instale: sudo apt install python3 python3-venv python3-pip"; exit 1; }

# --------------------------------------------------------------------------- #
# 1) Python + venv
# --------------------------------------------------------------------------- #
step "Criando ambiente virtual e instalando dependências"
if [[ ! -x "$VENV_PY" ]]; then
    python3 -m venv "$ROOT/.venv"
fi
"$VENV_PY" -m pip install --upgrade pip --quiet
"$VENV_PY" -m pip install -r "$ROOT/requirements.txt"
ok "Dependências instaladas no .venv"

# --------------------------------------------------------------------------- #
# 2) Ollama + modelos (dois servidores: 11434 orquestrador, 11435 OCR/VLM)
# --------------------------------------------------------------------------- #
command -v ollama >/dev/null 2>&1 || {
    step "Instalando Ollama (Linux)"
    curl -fsSL https://ollama.com/install.sh | sh
}

# Garante um servidor Ollama de pé na porta dada (sobe em background se preciso).
ensure_ollama() {
    local port="$1"
    if OLLAMA_HOST="127.0.0.1:${port}" ollama list >/dev/null 2>&1; then
        ok "Ollama de pé na porta $port"
        return 0
    fi
    echo "    Iniciando Ollama na porta $port (background)..."
    OLLAMA_HOST="127.0.0.1:${port}" nohup ollama serve >/dev/null 2>&1 &
    disown
    for _ in $(seq 1 60); do
        if OLLAMA_HOST="127.0.0.1:${port}" ollama list >/dev/null 2>&1; then
            ok "Ollama na porta $port está de pé."
            return 0
        fi
        sleep 0.5
    done
    warn "Ollama na porta $port não respondeu a tempo (ainda pode estar iniciando)."
    return 0
}

# Baixa o modelo no servidor correto e só confirma "pronto" se o pull sucedeu.
pull_model() {
    local name="$1" size="$2" desc="$3" port="$4"
    step "Baixando o modelo $desc: $name ($size) na porta $port"
    if OLLAMA_HOST="127.0.0.1:${port}" ollama pull "$name"; then
        ok "$name pronto (porta $port)"
    else
        warn "Falha ao baixar $name na porta $port. Tente: OLLAMA_HOST=127.0.0.1:${port} ollama pull $name"
    fi
}

ensure_ollama 11434   # orquestrador (MiniCPM)
ensure_ollama 11435   # OCR/VLM (LightOnOCR)

pull_model aipib/LightOnOCR-2-1B:Q8_0 "~1GB" "de OCR local" 11435
pull_model jewelzufo/MiniCPM5-1B:latest "~1GB" "orquestrador local de ações" 11434

# --------------------------------------------------------------------------- #
# 3) Node.js (opcional: MCP e Claude Code)
# --------------------------------------------------------------------------- #
if [[ "$DO_MCP" == "1" || "$DO_CLAUDE" == "1" ]]; then
    command -v node >/dev/null 2>&1 || {
        step "Instalando Node.js LTS (via NodeSource)"
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    }
    ok "Node.js pronto"
fi

if [[ "$DO_MCP" == "1" ]]; then
    step "Instalando o computer-control-mcp-server (controle do PC)"
    npm install -g @wshobson/mcp-server-computer-control || warn "Falha no npm install."
fi

if [[ "$DO_CLAUDE" == "1" ]]; then
    step "Instalando o Claude Code (modelo forte — usa a assinatura do usuário)"
    npm install -g @anthropic-ai/claude-code || warn "Falha no npm install do Claude Code."
fi

# --------------------------------------------------------------------------- #
# 4) Arquivo .env
# --------------------------------------------------------------------------- #
step "Configurando o .env"
if [[ ! -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    if [[ "$DO_MCP" != "1" ]]; then
        sed -i 's/^AEYE_MCP=1/AEYE_MCP=0/' "$ROOT/.env"
    fi
    warn "Crie as 2 chaves gratuitas e cole no .env:"
    warn "  * Gemini (AI Studio): https://aistudio.google.com/apikey"
    warn "  * Cerebras:           https://cloud.cerebras.ai (menu API Keys)"
else
    ok ".env já existe (mantido)"
fi

# --------------------------------------------------------------------------- #
step "Instalação concluída!"
echo "    Para rodar:   $ROOT/run.sh        (ou: .venv/bin/python app.py)"

if [[ "$DO_LAUNCH" == "1" ]]; then
    step "Iniciando o AEye"
    "$VENV_PY" "$ROOT/app.py" &
    sleep 2
    echo "    Abrindo http://localhost:8080 ..."
    xdg-open "http://localhost:8080" >/dev/null 2>&1 || true
fi
