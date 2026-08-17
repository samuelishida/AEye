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
