#!/usr/bin/env bash
# AEye — inicia o servidor local (usa o .venv criado pelo install.sh).
# Uso: ./run.sh [porta]
#
# Modos:
#   - padrão (dGPU): Ollama padrão nas portas 11434 (orch) / 11435 (OCR)
#   - iGPU (.env: AEYE_GPU=igpu): Ollama fixado na iGPU Intel via Vulkan,
#     portas lidas do .env (OLLAMA_URL_ORCH / OLLAMA_URL), binário e ICD
#     do .env (AEYE_OLLAMA_BIN / AEYE_VK_ICD_FILENAMES / AEYE_OLLAMA_MODELS).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"
VENV_PY="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
     echo "Ambiente virtual não encontrado. Rode primeiro: ./install.sh" >&2
     exit 1
fi

# Lê KEY do .env (linha KEY=valor) sem carregar o .env inteiro.
_env_get() {
     local k="$1"
     grep -E "^${k}=" "$ROOT/.env" 2>/dev/null | cut -d= -f2-
     return 0
}

AEYE_GPU="$(_env_get AEYE_GPU)"

if [[ "$AEYE_GPU" == "igpu" ]]; then
     # --- Modo iGPU (Intel Vulkan) ---
     _bin="$(_env_get AEYE_OLLAMA_BIN)"
     _models="$(_env_get AEYE_OLLAMA_MODELS)"
     _icd="$(_env_get AEYE_VK_ICD_FILENAMES)"

     if [[ -z "$_bin" || ! -x "$_bin" ]]; then
          echo "AEYE_GPU=igpu mas AEYE_OLLAMA_BIN ausente sem +x no .env: ${_bin:-<vazio>}" >&2
          exit 1
     fi
     if [[ -z "$_icd" || ! -f "$_icd" ]]; then
          echo "AEYE_GPU=igpu mas AEYE_VK_ICD_FILENAMES ausente no .env: ${_icd:-<vazio>}" >&2
          exit 1
     fi
     if [[ -z "$_models" ]]; then
          echo "AEYE_GPU=igpu mas AEYE_OLLAMA_MODELS ausente no .env" >&2
          exit 1
     fi

     OLLAMA_BIN="$_bin"
     export HIP_VISIBLE_DEVICES=99          # ROCm/dGPU visível => 99 = nenhum
     export OLLAMA_IGPU_ENABLE=1
     export OLLAMA_VULKAN_DEVICE=0          # GPU0 = iGPU Intel (Vulkan device 0)
     export VK_ICD_FILENAMES="$_icd"
     export OLLAMA_MODELS="$_models"
     # FA=0 é OBRIGATÓRIO na iGPU: flash attention (Vulkan) corrompe as
     # embeddings de visão e o OCR sai como mojibake multilíngue.
     # K cache q8_0 economiza ~40% de RAM; V fica f16 (V quantizado exige FA).
     export OLLAMA_FLASH_ATTENTION=0
     export OLLAMA_KV_CACHE_K_TYPE=q8_0
     echo "Modo iGPU ativo: $(basename "$_bin") | ICD=$(basename "$_icd") | FA=0 K=q8_0"
else
     OLLAMA_BIN="ollama"
fi

# Portas: modo iGPU lê do .env; modo padrão usa 11434/11435.
_ollama_ports() {
     if [[ "$AEYE_GPU" == "igpu" ]]; then
          local orch ocr
          orch="$(_env_get OLLAMA_URL_ORCH)"
          ocr="$(_env_get OLLAMA_URL)"
          echo "${orch##*:}" "${ocr##*:}"
     else
          echo "11434 11435"
     fi
}
read -r ORCH_PORT OCR_PORT <<< "$(_ollama_ports)"
ORCH_PORT="${ORCH_PORT:-11434}"
OCR_PORT="${OCR_PORT:-11435}"

# Garante os servidores Ollama de pé (subindo em background se necessário).
ensure_ollama() {
     local port="$1"
     if OLLAMA_HOST="127.0.0.1:${port}" "$OLLAMA_BIN" list >/dev/null 2>&1; then
          echo "Ollama já está de pé na porta $port"
          return 0
     fi
     echo "Iniciando Ollama na porta $port (background)..."
     OLLAMA_HOST="127.0.0.1:${port}" nohup "$OLLAMA_BIN" serve >/dev/null 2>&1 &
     disown
     for _ in $(seq 1 60); do
          if OLLAMA_HOST="127.0.0.1:${port}" "$OLLAMA_BIN" list >/dev/null 2>&1; then
               echo "Ollama na porta $port está de pé."
               return 0
          fi
          sleep 0.5
     done
     echo "Aviso: Ollama na porta $port não respondeu a tempo (ainda pode estar iniciando)." >&2
     return 0
}

ensure_ollama "$ORCH_PORT"   # orquestrador (MiniCPM)
ensure_ollama "$OCR_PORT"    # OCR/VLM (LightOnOCR)

export AEYE_PORT="$PORT"
echo "Iniciando o AEye em http://localhost:$PORT ..."

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [[ -n "$IP" ]]; then
     echo "No celular (mesma rede Wi-Fi): http://${IP}:$PORT"
fi

cd "$ROOT"
exec "$VENV_PY" app.py
