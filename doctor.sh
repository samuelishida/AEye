#!/usr/bin/env bash
# AEye — autoteste de prontidão (doctor.sh).
# Uso:
#      ./doctor.sh           # checagem completa (inclui teste real de OCR, ~30-60s)
# O que faz, nesta ordem:
#   1) .venv + dependências
#   2) modo GPU (dGPU padrão ou iGPU via AEYE_GPU=igpu no .env)
#   3) sobe os dois Ollama (orquestrador + OCR) se estiverem fora do ar
#   4) confere que os dois modelos estão baixados
#   5) gera uma imagem de teste e lê o resultado do OCR (qualidade real)
#   6) roda a suíte de testes (pytest)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
VENV_PY="$ROOT/.venv/bin/python"

PASS=0; FAIL=0; WARN=0
ok()    { echo "   OK  $1"; PASS=$((PASS+1)); }
warn()  { echo "   !   $1"; WARN=$((WARN+1)); }
fail()  { echo "   X   $1"; FAIL=$((FAIL+1)); }

env_get() {
      local k="$1"
      grep -E "^${k}=" "$ROOT/.env" 2>/dev/null | cut -d= -f2-
      return 0
    }

OCR_PYT=/tmp/aeye-ocr-check.py
cat > "$OCR_PYT" <<'PYEOF'
import base64, io, json, os, sys, time, urllib.request
from PIL import Image, ImageDraw, ImageFont

img = Image.new("RGB", (480, 140), "white")
d = ImageDraw.Draw(img)
try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 26)
except Exception:
        f = ImageFont.load_default()
d.text((20, 30), "AEYE DOC OK 42", fill="black", font=f)
buf = io.BytesIO()
img.save(buf, format="PNG")
b64 = base64.b64encode(buf.getvalue()).decode()

port = os.environ.get("AEYE_DOCTOR_OCR_PORT", "11435")
model = os.environ.get("AEYE_DOCTOR_OCR_MODEL", "aipib/LightOnOCR-2-1B:Q8_0")
try:
        req = urllib.request.Request(
             f"http://127.0.0.1:{port}/v1/chat/completions",
             data=json.dumps({"model": model,
                  "messages": [{"role": "user", "content": [
                       {"type": "text", "text": "Transcreva o documento."},
                       {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]}],
                  "max_tokens": 64, "temperature": 0}).encode(),
             headers={"Content-Type": "application/json"})
        t0 = time.time()
        out = json.load(urllib.request.urlopen(req, timeout=180))
        text = out["choices"][0]["message"]["content"]
        print(f"       OCR em {time.time()-t0:.1f}s -> {text!r}")
        sys.exit(0 if ("42" in text and "AEYE" in text.upper()) else 1)
except Exception as e:     # noqa: BLE001
        print(f"       erro no teste de OCR: {e}")
        sys.exit(2)
PYEOF

echo "== 1) Ambiente Python =="
if [[ -x "$VENV_PY" ]]; then
        ok ".venv presente"
        if "$VENV_PY" -c "import fastapi, httpx, pyttsx3, PIL" 2>/dev/null; then
            ok "dependências instaladas"
        else
            fail "dependência faltando — rode: ./install.sh"
        fi
else
        fail ".venv ausente — rode: ./install.sh"
fi
[[ -f "$ROOT/.env" ]] || warn ".env ausente (usando portas/modelos padrão)"

echo
echo "== 2) Modo GPU e portas =="
AEYE_GPU="$(env_get AEYE_GPU)"
_raw_orch="$(env_get OLLAMA_URL_ORCH)"
_raw_ocr="$(env_get OLLAMA_URL)"
PORT_ORCH="${_raw_orch##*:}";   [[ -z "$PORT_ORCH" || "$PORT_ORCH" == "$_raw_orch" ]] && PORT_ORCH=11434
PORT_OCR="${_raw_ocr##*:}";     [[ -z "$PORT_OCR"   || "$PORT_OCR"   == "$_raw_ocr"   ]] && PORT_OCR=11435
echo "   orquestrador (MiniCPM) na porta $PORT_ORCH | OCR (LightOnOCR) na porta $PORT_OCR"

OLLAMA_BIN="ollama"
IGPU=()
if [[ "$AEYE_GPU" == "igpu" ]]; then
        _bin="$(env_get AEYE_OLLAMA_BIN)"
        [[ -z "${_bin:-}" ]] && _bin="$ROOT/../ollama/build/ollama-ngram3"
        if [[ -n "${_bin:-}" && -x "${_bin:-/nonexistent}" ]]; then
            OLLAMA_BIN="$_bin"
            ok "modo iGPU | binário: $OLLAMA_BIN"
        else
            fail "modo iGPU ativo, mas binário não encontrado — preencha AEYE_OLLAMA_BIN no .env"
        fi
        _icd="$(env_get AEYE_VK_ICD_FILENAMES)"
        if [[ -n "${_icd:-}" && -f "${_icd:-/nonexistent}" ]]; then
            ok "ICD Vulkan Intel: $_icd"
            IGPU+=(VK_ICD_FILENAMES="$_icd")
        else
            warn "AEYE_VK_ICD_FILENAMES ausente/inacessível (usa ICD do sistema)"
        fi
        _models="$(env_get AEYE_OLLAMA_MODELS)"
        [[ -n "${_models:-}" ]] && IGPU+=(OLLAMA_MODELS="$_models")
        IGPU+=(HIP_VISIBLE_DEVICES=99 OLLAMA_IGPU_ENABLE=1 OLLAMA_VULKAN_DEVICE=0
               OLLAMA_FLASH_ATTENTION=0 OLLAMA_KV_CACHE_K_TYPE=q8_0)
        if command -v vulkaninfo >/dev/null 2>&1; then
            if vulkaninfo --summary 2>/dev/null | grep -qi intel; then
                ok "Vulkan: dispositivo Intel na lista"
            else
                warn "Vulkan: dispositivo Intel não listado"
            fi
        else
            warn "vulkaninfo ausente (verificação de GPU ignorada)"
        fi
else
        echo "   modo padrão (Ollama da dGPU / instância principal)"
fi

echo
echo "== 3) Servidores Ollama =="
up() { OLLAMA_HOST="127.0.0.1:$1" "$OLLAMA_BIN" list >/dev/null 2>&1; }
start_srv() {
        local port="$1"
        env "${IGPU[@]}" OLLAMA_HOST="127.0.0.1:$port" nohup "$OLLAMA_BIN" serve \
            > "/tmp/aeye-ollama-$port.log" 2>&1 &
        disown
        local i
        for i in $(seq 1 60); do
            if up "$port"; then
                return 0
            fi
            sleep 0.5
        done
        return 1
}
for role in "orquestrador:$PORT_ORCH" "OCR:$PORT_OCR"; do
        name="${role%%:*}"
        port="${role##*:}"
        if up "$port"; then
            ok "Ollama $name de pé na porta $port"
        elif start_srv "$port" && up "$port"; then
            ok "Ollama $name subido agora na porta $port (log: /tmp/aeye-ollama-$port.log)"
        else
            fail "Ollama $name não sobe na porta $port — veja /tmp/aeye-ollama-$port.log"
        fi
done

echo
echo "== 4) Modelos baixados =="
MODEL_OCR="$(env_get OLLAMA_MODEL)"
MODEL_ORCH="$(env_get AEYE_ORCH_MODEL)"
[[ -z "${MODEL_OCR:-}"   ]] && MODEL_OCR="aipib/LightOnOCR-2-1B:Q8_0"
[[ -z "${MODEL_ORCH:-}" ]] && MODEL_ORCH="jewelzufo/MiniCPM5-1B:latest"
if OLLAMA_HOST="127.0.0.1:$PORT_OCR" "$OLLAMA_BIN" list 2>/dev/null | grep -qF "$MODEL_OCR"; then
        ok "OCR: $MODEL_OCR"
else
        fail "OCR: $MODEL_OCR ausente (baixe: OLLAMA_HOST=127.0.0.1:$PORT_OCR \"$OLLAMA_BIN\" pull $MODEL_OCR)"
fi
if OLLAMA_HOST="127.0.0.1:$PORT_ORCH" "$OLLAMA_BIN" list 2>/dev/null | grep -qF "$MODEL_ORCH"; then
        ok "orquestrador: $MODEL_ORCH"
else
        fail "orquestrador: $MODEL_ORCH ausente (baixe: OLLAMA_HOST=127.0.0.1:$PORT_ORCH \"$OLLAMA_BIN\" pull $MODEL_ORCH)"
fi

echo
echo "== 5) Qualidade do OCR (imagem real, endpoint /v1) =="
AEYE_DOCTOR_OCR_PORT="$PORT_OCR" AEYE_DOCTOR_OCR_MODEL="$MODEL_OCR" "$VENV_PY" "$OCR_PYT"
rc=$?
if [[ $rc -eq 0 ]]; then
        ok "OCR legível e correto na porta $PORT_OCR"
elif [[ $rc -eq 2 ]]; then
        fail "OCR sem resposta (timeout/conexão) na porta $PORT_OCR"
else
        fail "OCR ilegível (mojibake?) — em iGPU confira OLLAMA_FLASH_ATTENTION=0 e K=q8_0"
fi

echo
echo "== 6) Suíte de testes (pytest) =="
pt="$("$VENV_PY" -m pytest -q 2>&1 | tail -1)"
echo "   $pt"
if echo "$pt" | grep -q "passed"; then
        ok "pytest"
else
        fail "pytest falhou"
fi

echo
echo "================================================="
echo "doctor: $PASS OK | $WARN aviso(s) | $FAIL falha(s)"
if [[ "$FAIL" -eq 0 ]]; then
        _port="$(env_get AEYE_PORT)"
        [[ -z "${_port:-}" ]] && _port=8080
        echo "AEye pronto. Para usar:   ./run.sh   e abrir http://localhost:$_port"
        exit 0
fi
echo "Corrija os itens marcados com X e rode ./doctor.sh de novo."
exit 1