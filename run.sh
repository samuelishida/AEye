#!/usr/bin/env bash
# AEye — inicia o servidor local (usa o .venv criado pelo install.sh).
# Uso: ./run.sh [porta]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"
VENV_PY="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
    echo "Ambiente virtual não encontrado. Rode primeiro: ./install.sh" >&2
    exit 1
fi

# --------------------------------------------------------------------------- #
# Garante os dois servidores Ollama de pé (subindo em background se necessário).
#   11434 -> orquestrador (MiniCPM)   |   11435 -> OCR/VLM (LightOnOCR)
# --------------------------------------------------------------------------- #
ensure_ollama() {
    local port="$1"
    if OLLAMA_HOST="127.0.0.1:${port}" ollama list >/dev/null 2>&1; then
        echo "Ollama já está de pé na porta $port"
        return 0
    fi
    echo "Iniciando Ollama na porta $port (background)..."
    OLLAMA_HOST="127.0.0.1:${port}" nohup ollama serve >/dev/null 2>&1 &
    disown
    for _ in $(seq 1 30); do
        if OLLAMA_HOST="127.0.0.1:${port}" ollama list >/dev/null 2>&1; then
            echo "Ollama na porta $port está de pé."
            return 0
        fi
        sleep 0.5
    done
    echo "Aviso: Ollama na porta $port não respondeu a tempo (ainda pode estar iniciando)." >&2
    return 0
}

ensure_ollama 11434   # orquestrador (MiniCPM)
ensure_ollama 11435   # OCR/VLM (LightOnOCR)

export AEYE_PORT="$PORT"
echo "Iniciando o AEye em http://localhost:$PORT ..."

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -n "$IP" ]]; then
    echo "No celular (mesma rede Wi-Fi): http://${IP}:$PORT"
fi

cd "$ROOT"
exec "$VENV_PY" app.py
