<#
.SYNOPSIS
    AEye — instalador automático para Windows (setup fácil).

.DESCRIPTION
    Instala/verifica tudo o que o AEye precisa no PC (Windows 10/11):
      * Python 3.10–3.12 (se faltar) + ambiente virtual + dependências pip
      * Ollama + modelo glm-ocr (OCR de manuscrito via Vulkan na Vega 8)
      * [opcional] Node.js + computer-control-mcp-server (controle por voz)
      * [opcional] Claude Code (toggle "modelo forte")
      * Cria o arquivo .env a partir do .env.example
      * Libera a porta 8080 no firewall (rede privada)

    Custo: US$ 0 (Gemini free + Cerebras free + OCR local).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -InstallMCP -InstallClaudeCode -Launch

.PARAMETER SkipPython
    Não verifica/instala o Python.
.PARAMETER SkipOllama
    Não instala o Ollama nem baixa modelos.
.PARAMETER SkipNode
    Não instala o Node.js.
.PARAMETER InstallMCP
    Instala Node.js + computer-control-mcp-server (controle do PC por voz).
.PARAMETER InstallClaudeCode
    Instala o Claude Code (usa a assinatura do usuário; sem API key).
.PARAMETER IncludeDeepSeek
    Baixa também o deepseek-ocr (~6,7GB) além do glm-ocr (~2,2GB).
.PARAMETER SkipFirewall
    Não tenta liberar a porta 8080 no firewall.
.PARAMETER Launch
    Inicia o AEye ao final do instalador.
#>
[CmdletBinding()]
param(
    [switch]$SkipPython,
    [switch]$SkipOllama,
    [switch]$SkipNode,
    [switch]$InstallMCP,
    [switch]$InstallClaudeCode,
    [switch]$IncludeDeepSeek,
    [switch]$SkipFirewall,
    [switch]$Launch
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'

function Write-Step { param($m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "    OK   $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "    !    $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "    ERRO $m" -ForegroundColor Red }

function Test-PortOpen {
    param([int]$Port)
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
        return $iar.AsyncWaitHandle.WaitOne(500, $false) -and $c.Connected
    } catch { return $false }
    finally { $c.Dispose() }
}

function Get-Winget {
    $w = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}

# --------------------------------------------------------------------------- #
Write-Step "AEye — instalador automático (custo zero)"
Write-Host "    Pasta do projeto: $Root"

if (-not $env:OS -match 'Windows') {
    Write-Fail "Este instalador é só para Windows. (No Linux: pip install -r requirements.txt)"
    exit 1
}

# --------------------------------------------------------------------------- #
# 1) Python
# --------------------------------------------------------------------------- #
function Find-Python {
    $c = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($c) {
        $v = & $c.Source -c "import sys;print(sys.version_info.major, sys.version_info.minor)" 2>$null
        if ($v -match '^3 (1[0-2])$') { return $c.Source }
    }
    $c = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($c) {
        $out = & py -3 -c "import sys;print(sys.executable)" 2>$null
        foreach ($line in @($out)) {
            if ($line -and (Test-Path $line)) { return $line }
        }
    }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python*")) {
        $f = Get-ChildItem $base -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1
        if ($f) { return $f.FullName }
    }
    return $null
}

if (-not $SkipPython) {
    Write-Step "Verificando o Python (3.10–3.12)"
    $Py = Find-Python
    if ($Py) {
        Write-OK "Python encontrado: $Py"
    } else {
        $winget = Get-Winget
        if ($winget) {
            Write-Host "    Instalando Python via winget..."
            & $winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) { Write-Warn "winget falhou; tentando download direto..." }
        }
        if (-not $Py) {
            $Py = Find-Python
        }
        if (-not $Py) {
            Write-Host "    Baixando o instalador oficial do Python 3.12..."
            $exe = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
            Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $exe
            Start-Process -FilePath $exe -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1' -Wait
            $Py = Find-Python
        }
        if (-not $Py) {
            Write-Fail "Python não foi instalado. Instale em https://www.python.org (marque 'Add to PATH') e rode de novo."
            exit 1
        }
        Write-OK "Python instalado: $Py"
    }

    Write-Step "Criando ambiente virtual e instalando dependências"
    & $Py -m venv (Join-Path $Root '.venv')
    if (-not (Test-Path $VenvPy)) {
        Write-Fail "Falha ao criar o ambiente virtual."
        exit 1
    }
    & $VenvPy -m pip install --upgrade pip --quiet
    & $VenvPy -m pip install -r (Join-Path $Root 'requirements.txt')
    Write-OK "Dependências instaladas no .venv"
} else {
    if (-not (Test-Path $VenvPy)) {
        Write-Warn "-SkipPython usado, mas não há .venv — o app não vai rodar sem ele."
    }
}

# --------------------------------------------------------------------------- #
# 2) Ollama + modelos (Vulkan na Vega 8)
# --------------------------------------------------------------------------- #
function Find-Ollama {
    $c = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    # PATH pode não ter atualizado nesta sessão após a instalação:
    $known = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $known) { return $known }
    return $null
}

if (-not $SkipOllama) {
    Write-Step "Verificando o Ollama"
    $OllamaExe = Find-Ollama
    if (-not $OllamaExe) {
        $winget = Get-Winget
        if ($winget) {
            Write-Host "    Instalando Ollama via winget..."
            & $winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
        }
        $OllamaExe = Find-Ollama
        if (-not $OllamaExe) {
            Write-Host "    Baixando o OllamaSetup.exe..."
            $exe = Join-Path $env:TEMP 'OllamaSetup.exe'
            Invoke-WebRequest 'https://ollama.com/download/OllamaSetup.exe' -OutFile $exe
            Start-Process -FilePath $exe -Wait
            $OllamaExe = Find-Ollama
        }
        if (-not $OllamaExe) {
            Write-Fail "Ollama não instalado. Baixe em https://ollama.com/download e rode de novo."
            exit 1
        }
        Write-OK "Ollama instalado"
    } else {
        Write-OK "Ollama já instalado"
    }

    if (-not (Test-PortOpen 11434)) {
        Write-Host "    Iniciando o Ollama (aguarde)..."
        Start-Process -FilePath $OllamaExe -ArgumentList 'app' | Out-Null
        $ok = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 1
            if (Test-PortOpen 11434) { $ok = $true; break }
        }
        if (-not $ok) { Write-Warn "Ollama não respondeu na porta 11434 (abra o app do Ollama manualmente)." }
        else { Write-OK "Ollama no ar (http://localhost:11434)" }
    } else {
        Write-OK "Ollama já está no ar"
    }

    Write-Step "Baixando o modelo de OCR local: glm-ocr (~2,2GB)"
    & $OllamaExe pull glm-ocr
    if ($LASTEXITCODE -ne 0) { Write-Warn "Falha ao baixar glm-ocr. Tente: ollama pull glm-ocr" }
    else { Write-OK "glm-ocr pronto (use 'ollama ps' para confirmar a GPU Vulkan)" }

    if ($IncludeDeepSeek) {
        Write-Step "Baixando deepseek-ocr (~6,7GB, opcional)"
        & $OllamaExe pull deepseek-ocr
        if ($LASTEXITCODE -eq 0) { Write-OK "deepseek-ocr pronto" }
    }

    Write-Warn "Dica Vega 8: se 'ollama ps' mostrar CPU, defina a variável GGML_VK_VISIBLE_DEVICES=0 e reinicie o Ollama."
}

# --------------------------------------------------------------------------- #
# 3) Node.js (opcional: MCP e Claude Code)
# --------------------------------------------------------------------------- #
function Find-Node {
    $c = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    # PATH pode não ter atualizado nesta sessão após a instalação:
    $known = Join-Path $env:ProgramFiles 'nodejs\node.exe'
    if (Test-Path $known) { return $known }
    return $null
}

$NeedNode = $InstallMCP -or $InstallClaudeCode
if ($NeedNode -and -not $SkipNode) {
    Write-Step "Verificando o Node.js"
    $NodeExe = Find-Node
    if (-not $NodeExe) {
        $winget = Get-Winget
        if ($winget) {
            Write-Host "    Instalando Node.js LTS via winget..."
            & $winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
        }
        $NodeExe = Find-Node
        if (-not $NodeExe) {
            Write-Host "    Baixando o Node.js LTS (MSI)..."
            try {
                $idx = Invoke-RestMethod 'https://nodejs.org/dist/index.json' -TimeoutSec 30
                $lts = $idx | Where-Object { $_.lts } | Select-Object -First 1
                $msi = Join-Path $env:TEMP ("node-{0}-x64.msi" -f $lts.version)
                Invoke-WebRequest ("https://nodejs.org/dist/{0}/node-{0}-x64.msi" -f $lts.version) -OutFile $msi
                $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn" -Wait -PassThru
                if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
                    Write-Warn "Instalador do Node retornou código $($p.ExitCode)."
                }
                $NodeExe = Find-Node
            } catch {
                Write-Warn "Falha ao baixar o Node: $($_.Exception.Message)"
            }
        }
        if ($NodeExe) { Write-OK "Node.js instalado" } else { Write-Warn "Instale o Node.js em https://nodejs.org" }
    } else {
        Write-OK "Node.js já instalado"
    }
}

function Find-Npm {
    $c = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $known = Join-Path $env:ProgramFiles 'nodejs\npm.cmd'
    if (Test-Path $known) { return $known }
    return $null
}

if ($InstallMCP) {
    Write-Step "Instalando o computer-control-mcp-server (controle do PC por voz)"
    $Npm = Find-Npm
    if ($Npm) {
        & $Npm install -g @wshobson/mcp-server-computer-control
        if ($LASTEXITCODE -eq 0) { Write-OK "MCP instalado (AEYE_MCP=1 já ativo no .env)" }
        else { Write-Warn "Falha no npm install. Tente: npm install -g @wshobson/mcp-server-computer-control" }
    } else {
        Write-Warn "npm não encontrado — instale o Node.js primeiro."
    }
}

if ($InstallClaudeCode) {
    Write-Step "Instalando o Claude Code (modelo forte — usa a assinatura do usuário)"
    $Npm = Find-Npm
    if ($Npm) {
        & $Npm install -g @anthropic-ai/claude-code
        if ($LASTEXITCODE -eq 0) {
            Write-OK "Claude Code instalado. Rode 'claude' uma vez no terminal para logar."
        } else {
            Write-Warn "Falha no npm install do Claude Code."
        }
    } else {
        Write-Warn "npm não encontrado — instale o Node.js primeiro."
    }
}

# --------------------------------------------------------------------------- #
# 4) Arquivo .env
# --------------------------------------------------------------------------- #
Write-Step "Configurando o .env"
if (-not (Test-Path (Join-Path $Root '.env'))) {
    Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
    if (-not $InstallMCP) {
        (Get-Content (Join-Path $Root '.env')) -replace '^AEYE_MCP=1', 'AEYE_MCP=0' |
            Set-Content (Join-Path $Root '.env')
    }
    Write-Warn "Crie as 2 chaves gratuitas e cole no .env:"
    Write-Warn "  * Gemini (AI Studio): https://aistudio.google.com/apikey"
    Write-Warn "  * Cerebras:           https://cloud.cerebras.ai (menu API Keys)"
    try {
        Start-Process notepad.exe -ArgumentList (Join-Path $Root '.env')
        Write-Host "    (o Bloco de Notas abriu o .env — cole as chaves e salve)"
    } catch { }
} else {
    Write-OK ".env já existe (mantido)"
}

# --------------------------------------------------------------------------- #
# 5) Firewall (acesso pelo celular na rede Wi-Fi)
# --------------------------------------------------------------------------- #
if (-not $SkipFirewall) {
    Write-Step "Firewall (porta 8080)"
    try {
        New-NetFirewallRule -DisplayName 'AEye (TCP 8080)' -Direction Inbound -Protocol TCP `
            -LocalPort 8080 -Action Allow -Profile Any -ErrorAction Stop | Out-Null
        Write-OK "Porta 8080 liberada no firewall"
        Write-Warn "Se a rede Wi-Fi estiver marcada como 'Público', o celular ainda pode não conectar —"
        Write-Warn "nas Configurações do Windows, mude o perfil da rede para 'Privado'."
    } catch {
        Write-Warn "Sem permissão de administrador — na primeira execução do app, aceite o aviso do Windows."
    }
}

# --------------------------------------------------------------------------- #
# 6) Resumo
# --------------------------------------------------------------------------- #
Write-Step "Instalação concluída!"
Write-Host "    Para rodar:   .\run.ps1        (ou: .\.venv\Scripts\python.exe app.py)"
Write-Host "    No celular:   abra o navegador e digite o IP abaixo (mesma rede Wi-Fi):"

$ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254)' } |
    Select-Object -First 1 -ExpandProperty IPAddress
if ($ip) { Write-Host "        http://${ip}:8080" }

if ($Launch) {
    Write-Step "Iniciando o AEye"
    if (Test-Path $VenvPy) {
        Start-Process -FilePath $VenvPy -ArgumentList @('app.py') -WorkingDirectory $Root
        Start-Sleep -Seconds 3
        try { Start-Process "http://localhost:8080" } catch { }
    } else {
        Write-Fail ".venv não existe — rode o instalador sem -SkipPython."
        exit 1
    }
}
