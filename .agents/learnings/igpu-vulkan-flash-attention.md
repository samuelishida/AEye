# iGPU Vulkan — flash attention corrompe OCR (validado 2026-09-27)

## Sintoma
LightOnOCR-2-1B na iGPU Intel UHD 770 (llama.cpp Vulkan) com flash attention
ligado (padrão) produz OCR como mojibake multilíngue
(" is aეეეЕкО\n виЗ ТСИЕ..."), 0/9 marcadores, com latência normal.

## Causa raiz
Flash attention no backend Vulkan corrompe as embeddings de visão (vision KV).
A/B validado: FA on = garbage; `OLLAMA_FLASH_ATTENTION=0` = saída correta,
em dois binários diferentes e processos frios — não é cache shader nem driver
flutuante. O encode de imagem (mtmd) passa; a falha está nos kernels FA do
decode no KV de visão.

## Correção (config production do AEye)
```
OLLAMA_FLASH_ATTENTION=0      # obrigatório na iGPU para OCR correto
OLLAMA_KV_CACHE_K_TYPE=q8_0   # opcional, ~40% menos RAM p/ KV, sem perda medida
```
V cache fica f16: cache V quantizado exige flash attention (llama.cpp),
que está off. Conflito descoberto em runtime: "quantized V cache requires
flash_attn to be enabled" — por isso o split K/V (novos envs
`OLLAMA_KV_CACHE_K_TYPE` / `OLLAMA_KV_CACHE_V_TYPE` no repo `Code/ollama`,
patch em `llm/llama_server.go` + `envconfig/config.go`).

## Benchmark (iGPU UHD 770, Q8_0, config corrigida, 2026-09-27)
| doc            | total | ttft | gen tok/s | qualidade |
|---|---|---|---|---|
| curto (925 in)   |  2.9s |  0.2s | 17.2 | 2/2 |
| fatura (2190 in) | 31.6s |  0.2s | 11.7 | 4/4 |
| memorando (2740 in)| 29.7s | 0.2s |  9.6 | 4/4 |
Média de geração 12.8 tok/s; warmup/cold-load ~26.5s; com prompt cache,
TTFT ~0.2s em todos os docs.

## Gotchas
- `local u="$1" v="${u##*:}"` num statement único de `local` expande os RHS
  antes de qualquer atribuição (bash 5.2) → `v` vazio. Declarar em linhas
  separadas.
- `pkill -f "OLLAMA_HOST=..."` auto-match no shell que invoca — usar
  `pgrep -x ollama` + `/proc/$p/environ`.
- Native `/api/chat` com campo `images` é quebrado neste build (imagem
  descarta, EVAL=22, alucina transcrição) — sempre usar `/v1/chat/completions`
  com `image_url` no content.
