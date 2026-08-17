"""AEye — servidor local (FastAPI) para OCR + roteador gratuito + controle por voz.

Uso:  python app.py
Acesse pelo celular na mesma rede Wi-Fi:  http://<IP-DO-PC>:8080
"""
from __future__ import annotations

import hmac
import logging
import os
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from aeye import killswitch, ocr, vlm
from aeye.agent import ActionError, MCPToolExecutor, ToolExecutor, parse_command, validate_action
from aeye.clipboard_watcher import ClipboardWatcher
from aeye.llm import LLMError, key_ok
from aeye.router import Router, RouterExhausted
from aeye.tts import TTSEngine

load_dotenv()

# Make application-level warnings surface to stderr when run directly.
logging.basicConfig(level=logging.WARNING)

MAX_UPLOAD = 20 * 1024 * 1024  # 20MB

_IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "BMP": "image/bmp", "GIF": "image/gif"}


def _register_heif() -> None:
    """Habilita fotos HEIC (iPhone) se pillow-heif estiver instalado."""
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover
        pass


def _normalize_image(data: bytes) -> tuple[bytes, str]:
    """Identifica o formato e devolve (bytes, mime). HEIC/desconhecidos viram PNG."""
    import io

    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
        mime = _IMAGE_MIMES.get(fmt)
        if mime:
            return data, mime
        # HEIC ou formato desconhecido: converte para PNG.
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Imagem não reconhecida ({exc}). Use JPG/PNG (fotos HEIC do iPhone são convertidas automaticamente).",
        ) from exc


def require_pin(x_aeye_pin: str | None = Header(default=None)) -> None:
    """Autenticação opcional: se AEYE_PIN estiver no .env, exige o header X-AEYE-PIN.

    Sem PIN configurado, tudo funciona como antes (LAN doméstica).
    A comparação é de tempo constante (hmac.compare_digest) para evitar ataques
    de timing que revelem um PIN válido byte a byte.
    """
    pin = os.getenv("AEYE_PIN", "")
    if not pin:
        return
    candidate = x_aeye_pin or ""
    if not hmac.compare_digest(candidate, pin):
        raise HTTPException(status_code=401, detail="PIN incorreto. Configure AEYE_PIN no .env do PC.")

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

SYSTEM_FORMAT = (
    "Você é o assistente de acessibilidade AEye. Formate e corrija o texto "
    "extraído por OCR preservando o sentido e a estrutura (listas, números, "
    "endereços, parágrafos). Responda em português, a menos que o texto "
    "original esteja em outro idioma. Não invente informações que não estejam "
    "no texto."
)
PROMPT_EXTRACT = "Extraia TODO o texto exatamente como está, preservando linhas e estrutura."

# --------------------------------------------------------------------------- #
# Estado global
# --------------------------------------------------------------------------- #
router: Router | None = None
vlm_local: vlm.OllamaVLM
tts: TTSEngine
executor: ToolExecutor | None = None
cancel_event = threading.Event()

_pipeline_lock = threading.Lock()  # serializa o pipeline (OCR/LLM são pesados)


def build_executor() -> ToolExecutor | None:
    if os.getenv("AEYE_MCP", "0").lower() in ("1", "true", "yes"):
        return MCPToolExecutor()
    return None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Inicialização: cadeia de LLMs, VLM local, TTS, executor MCP e watcher."""
    global router, vlm_local, tts, executor
    _register_heif()
    try:
        router = Router()
    except LLMError as exc:
        # Sem chaves configuradas o servidor ainda sobe; /api/chat devolve erro claro.
        router = None  # type: ignore[assignment]
        print(f"[AVISO] {exc}")
    vlm_local = vlm.OllamaVLM()
    tts = TTSEngine()
    executor = build_executor()
    killswitch.start_escape_watcher(cancel_event)

    if os.getenv("AEYE_CLIPBOARD", "1").lower() in ("1", "true", "yes"):
        watcher = ClipboardWatcher(on_image=lambda data, _h: _handle_clipboard_image(data))
        watcher.start()

    print(f"AEye rodando em http://{_lan_ip()}:8080  (no PC) e http://localhost:8080")
    if router is not None:
        print(f"Cadeia de LLMs: {', '.join(router.names)}")
    try:
        yield
    finally:
        pass


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


# --------------------------------------------------------------------------- #
# Pipeline de OCR -> LLM
# --------------------------------------------------------------------------- #
def _call_llm(messages: list[dict[str, str]]) -> tuple[str, str, bool]:
    if router is None:
        raise RouterExhausted(LLMError("Nenhum provedor de LLM configurado (veja .env.example)"))
    text, provider, escalated = router.run(messages)
    return text, provider, escalated


def _call_strong(messages: Sequence[dict[str, str]]) -> tuple[str, str, str | None]:
    """L3 manual ("modelo forte"): Claude Code local do usuário.

    Ordem: 1) Claude Code CLI (conta/assinatura dele, sem API key)
           2) API da Anthropic (só com chave PRÓPRIA — sem suporte a terceiros)
           3) fallback: cadeia gratuita Gemini → Cerebras.

    Devolve (texto, provedor_utilizado, aviso|None). O aviso NUNCA vai dentro
    do texto entregue ao usuário. As falhas são logadas como diagnóstico para
    não deixar o usuário no escuro sobre por que o forte caiu no gratuito.
    """
    from aeye.llm import AnthropicClient, ClaudeCodeClient, LLMError

    errors: list[str] = []
    if ClaudeCodeClient.available():
        try:
            return ClaudeCodeClient().chat(messages), "claude_code", None
        except LLMError as exc:
            logging.warning("Claude Code falhou: %s", exc)
            errors.append(f"Claude Code: {exc}")
    else:
        errors.append("Claude Code não instalado")

    if key_ok(os.getenv("ANTHROPIC_API_KEY")):
        try:
            return AnthropicClient().chat(messages), "anthropic", None
        except LLMError as exc:
            logging.warning("API Anthropic falhou: %s", exc)
            errors.append(f"API Anthropic: {exc}")

    text, provider, _escalated = _call_llm(messages)
    return text, provider, "modelo forte indisponível (" + "; ".join(errors) + ") — usado o provedor gratuito"


def _extract_with_vlm(image_bytes: bytes, prompt: str, mime: str = "image/png") -> str:
    try:
        return vlm_local.describe(image_bytes, prompt, mime=mime)
    except vlm.VLMUnavailable as exc:
        raise RuntimeError(str(exc)) from exc


def pipeline_image(image_bytes: bytes, mode: str, instruction: str, strong: bool = False, mime: str = "image/png") -> dict[str, Any]:
    """Modos: 'texto' | 'manuscrito' | 'perguntar'."""
    source = "ocr"
    warning: str | None = None
    raw_text = ""

    with _pipeline_lock:
        if mode == "perguntar":
            question = instruction.strip() or "O que tem nesta imagem? Descreva com detalhes."
            try:
                raw_text = _extract_with_vlm(image_bytes, question, mime)
                source = "vlm"
            except RuntimeError:
                raw_text = _gemini_vision_fallback(image_bytes, question, mime)
                if raw_text:
                    source = "gemini_vision"
                else:
                    raise HTTPException(
                        status_code=503,
                        detail="Ollama fora do ar e sem fallback de visão configurado. "
                        "Rode: ollama pull glm-ocr",
                    )
            final_text = raw_text
            provider = source
        else:
            # L0: OCR clássico rápido
            try:
                raw_text = ocr.extract_text(image_bytes)
            except ocr.OCRUnavailable as exc:
                warning = str(exc)
                raw_text = ""

            # L1: pouco texto -> manuscrito/imagem complexa -> VLM local
            if mode == "manuscrito" or ocr.needs_vlm(raw_text):
                try:
                    raw_text = _extract_with_vlm(image_bytes, PROMPT_EXTRACT, mime)
                    source = "vlm"
                except RuntimeError as exc:
                    warning = (warning or "") + f" VLM local indisponível: {exc}"

            if not raw_text.strip():
                raise HTTPException(
                    status_code=422, detail="Nenhum texto detectado na imagem. Tente uma foto mais nítida."
                )

            # L2: LLM gratuito formata/corrige
            user = f"Texto extraído:\n{raw_text}\n\nInstrução: {instruction or 'Formate o texto.'}"
            try:
                if strong:
                    final_text, provider, strong_warning = _call_strong(
                        [{"role": "system", "content": SYSTEM_FORMAT}, {"role": "user", "content": user}]
                    )
                    if strong_warning:
                        warning = (warning or "") + f" {strong_warning}"
                else:
                    final_text, provider, escalated = _call_llm(
                        [{"role": "system", "content": SYSTEM_FORMAT}, {"role": "user", "content": user}]
                    )
                    if escalated:
                        warning = (warning or "") + " (provedor principal indisponível; usado fallback)"
            except RouterExhausted as exc:
                final_text = raw_text
                provider = "ocr_local"
                warning = (warning or "") + f" LLM indisponível ({exc}); devolvido o texto cru do OCR."

    return {
        "ok": True,
        "text": final_text,
        "source": source,
        "provider": provider,
        "warning": (warning or "").strip() or None,
    }


def _gemini_vision_fallback(image_bytes: bytes, question: str, mime: str = "image/png") -> str:
    """Visão de backup via Gemini (se estiver na cadeia e tiver chave)."""
    try:
        from aeye.llm import GeminiClient

        client = GeminiClient()
        return client.describe_image(image_bytes, question, mime=mime)
    except Exception:  # noqa: BLE001 - sem chave ou falha: segue sem
        return ""


def _handle_clipboard_image(data: bytes) -> None:
    """Disparado pelo watcher: processa a captura e cola o resultado de volta."""
    try:
        result = pipeline_image(data, "texto", "")
        if os.name == "nt":
            import subprocess

            # Devolve o resultado formatado para o clipboard (cola em qualquer app).
            # Via stdin: sem limite de 32K chars e sem problemas de aspas/emoji.
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=result["text"],
                capture_output=True,
                timeout=15,
            )
        print(f"[clipboard] Captura processada via {result['provider']}: {len(result['text'])} chars")
    except Exception as exc:  # noqa: BLE001
        print(f"[clipboard] Erro ao processar captura: {exc}")


# --------------------------------------------------------------------------- #
# Aplicação
# --------------------------------------------------------------------------- #
app = FastAPI(title="AEye", version="0.1.0", lifespan=lifespan)

# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/")
def _index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/health")
def _health() -> dict[str, Any]:
    return {
        "ok": True,
        "chain": router.names if router is not None else [],
        "ollama": vlm_local.available() if "vlm_local" in globals() else False,
        "mcp": executor is not None,
    }


@app.post("/api/ocr", dependencies=[Depends(require_pin)])
async def api_ocr(
    file: UploadFile = File(...),
    mode: str = Form("texto"),
    instruction: str = Form(""),
    strong: str = Form("false"),
) -> dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Imagem vazia")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máximo 20MB).")
    mode = mode if mode in ("texto", "manuscrito", "perguntar") else "texto"
    data, mime = _normalize_image(data)
    # OCR/LLM são bloqueantes: roda fora do event loop para não travar a UI.
    return await run_in_threadpool(pipeline_image, data, mode, instruction, strong.lower() == "true", mime)


@app.post("/api/chat", dependencies=[Depends(require_pin)])
async def api_chat(message: dict[str, str]) -> dict[str, Any]:
    text = (message.get("message") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    if router is None:
        raise HTTPException(status_code=503, detail="Nenhum provedor de LLM configurado (.env)")
    try:
        # run() tem parâmetros keyword-only: usa lambda (não passar dict posicional).
        answer, provider, escalated = await run_in_threadpool(
            lambda: router.run(
                [{"role": "user", "content": text}], temperature=0.3, max_tokens=2048
            )
        )
    except RouterExhausted as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "text": answer, "provider": provider, "escalated": escalated}


@app.post("/api/act", dependencies=[Depends(require_pin)])
async def api_act(payload: dict[str, Any]) -> dict[str, Any]:
    """Comandos de ação por voz.

    Fluxo seguro (WYSIWYG):
      1) approved=false -> interpreta o comando e devolve a ação para confirmação;
      2) approved=true  -> executa EXATAMENTE a ação que o usuário aprovou
         (recebida de volta no payload e validada no servidor — o comando não é
         re-interpretado, evitando que o LLM gere uma ação diferente na 2ª chamada).
    """
    command = (payload.get("command") or "").strip()
    if not command:
        raise HTTPException(status_code=400, detail="Comando vazio")
    if executor is None:
        raise HTTPException(
            status_code=503,
            detail="Controle do PC não habilitado. Configure AEYE_MCP=1 no .env e instale o "
            "computer-control-mcp-server (veja README).",
        )
    if router is None:
        raise HTTPException(
            status_code=503, detail="Nenhum provedor de LLM configurado (.env) para interpretar o comando."
        )

    approved = payload.get("approved") is True

    if not approved:
        try:
            # parse (chamada de LLM, bloqueante) fora do event loop
            action = await run_in_threadpool(parse_command, router, command)
        except ActionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Sempre exige aprovação explícita na UI antes de executar.
        return {"status": "needs_approval", "action": action}

    # --- Aprovação: valida e executa a ação aprovada (não re-interpreta) ---
    try:
        action = validate_action(payload.get("action"))
    except ActionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Kill switch: arma o cancelamento só durante a execução (um Esc antigo
    # não cancela uma ação nova).
    cancel_event.clear()
    result = await run_in_threadpool(executor.execute, action)
    if cancel_event.is_set():
        cancel_event.clear()
        return {"status": "cancelled", "action": action, "result": result}
    return {"status": "done", "action": action, "result": result}


@app.post("/api/cancel", dependencies=[Depends(require_pin)])
async def api_cancel() -> dict[str, bool]:
    cancel_event.set()
    return {"ok": True}


@app.post("/api/read", dependencies=[Depends(require_pin)])
async def api_read(payload: dict[str, str]) -> dict[str, bool]:
    text = (payload.get("text") or "").strip()
    if text:
        tts.speak(text)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# UI estática
# --------------------------------------------------------------------------- #
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("AEYE_PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
