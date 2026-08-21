<#
.SYNOPSIS
    AEye — inicia o servidor local (usa o .venv criado pelo install.ps1).

.EXAMPLE
    .\run.ps1
#>
[CmdletBinding()]
param([int]$Port = 8080)

$Root = $PSScriptRoot
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'

if (-not (Test-Path $VenvPy)) {
    Write-Host "Ambiente virtual não encontrado. Rode primeiro:" -ForegroundColor Yellow
    Write-Host "    powershell -ExecutionPolicy Bypass -File .\install.ps1" -ForegroundColor Cyan
    exit 1
}

# --------------------------------------------------------------------------- #
# Garante os dois servidores Ollama de pé (subindo em background se necessário).
#   11434 -> orquestrador (MiniCPM)   |   11435 -> OCR/VLM (LightOnOCR)
# --------------------------------------------------------------------------- #
function Test-OllamaPort {
    param([int]$Port)
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/version" -TimeoutSec 2 -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Start-OllamaServer {
    param([int]$Port)
    if (Test-OllamaPort -Port $Port) {
        Write-Host "Ollama já está de pé na porta $Port" -ForegroundColor Green
        return
    }
    # Usa o caminho descoberto (PATH pode não ter atualizado após a instalação):
    $OllamaExe = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if (-not $OllamaExe) {
        $known = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
        if (Test-Path $known) { $OllamaExe = Get-Item $known }
    }
    if (-not $OllamaExe) {
        Write-Host "Aviso: 'ollama' não encontrado no PATH. Rode install.ps1 primeiro." -ForegroundColor Yellow
        return
    }
    Write-Host "Iniciando Ollama na porta $Port (background)..." -ForegroundColor Cyan
    $env:OLLAMA_HOST = "127.0.0.1:$Port"
    Start-Process -FilePath $OllamaExe.Source -ArgumentList "serve" -WindowStyle Hidden
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-OllamaPort -Port $Port) {
            Write-Host "Ollama na porta $Port está de pé." -ForegroundColor Green
            return
        }
    }
    Write-Host "Aviso: Ollama na porta $Port não respondeu a tempo (ainda pode estar iniciando)." -ForegroundColor Yellow
}

Start-OllamaServer -Port 11434   # orquestrador (MiniCPM)
Start-OllamaServer -Port 11435   # OCR/VLM (LightOnOCR)

$env:AEYE_PORT = "$Port"
Write-Host "Iniciando o AEye em http://localhost:$Port ..." -ForegroundColor Cyan

$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254)' } |
    Select-Object -First 1 -ExpandProperty IPAddress
if ($ip) {
    Write-Host "No celular (mesma rede Wi-Fi): http://${ip}:$Port" -ForegroundColor Green
}

Set-Location $Root
& $VenvPy app.py
