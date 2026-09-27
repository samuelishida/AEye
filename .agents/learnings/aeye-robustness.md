# AEye robustness plan — lições (golden questions)

## 1. O que funcionou
- `plan-large` + `review-plan` pegaram duas falhas antes da implementação:
  - Inc 4 tinha dependência falsa em Inc 3 (frontend puro, sem acoplamento) →
    corrigido para `depends on: none`, liberando paralelismo.
  - Inc 3 não especificava a mudança da string de formato do `basicConfig` →
    sem `%(request_id)s` no formato o filtro nunca seria renderizado.
- Padrão de logging estruturado (middleware + `contextvars` + `logging.Filter`
  anexado ao *handler* do root) é limpo, testável e propaga para o threadpool
  via `run_in_threadpool` (anyio copia o contexto).

## 2. O que não funcionou
- `replace_string_in_file` com newString multi-linha deslocou o corpo de
  `api_read` (o `if text:` ficou vazio e o `return` caiu depois do novo
  endpoint) e produziu um `$` solto em `web/app.js` (`$($("approveBtn"...`).
  **Correção:** sempre rodar o check do projeto (`pytest` + `node --check`)
  antes de marcar o incremento como done — pegou ambos em segundos.

## 3. O que reutilizar
- O fixture `client` em `tests/test_app_smoke.py` neutraliza `dotenv.load_dotenv`
  e faz `pop` das chaves de API: novos endpoints devem espelhar a paridade de
  `Depends(require_pin)` dos demais `/api/*`.
- Estado de TTS exposto via `TTSEngine.status() -> tuple[str, bool]` sob o
  lock existente (`_lock`), não via atributos públicos soltos.
- Variáveis de ambiente novas (`AEYE_CLIPBOARD_POLL`, `AEYE_LOG_LEVEL`) devem
  ir também no `.env.example` com comentário.
