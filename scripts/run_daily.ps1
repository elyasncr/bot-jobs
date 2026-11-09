# vagas-pj-bot - execucao diaria (Agendador de Tarefas do Windows).
# Garante o Ollama no ar, roda o bot e grava a saida em logs\YYYY-MM-DD.log.
# Argumentos extras sao repassados ao "run" (ex.: -File run_daily.ps1 --force).
# Arquivo mantido em ASCII: o PowerShell 5.1 le scripts sem BOM como ANSI.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$LogFile = Join-Path $Root ("logs\" + (Get-Date -Format "yyyy-MM-dd") + ".log")
$OllamaUrl = "http://localhost:11434"

function Write-Log([string]$Message) {
    $line = "{0} [run_daily] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    [System.IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding $false))
}

function Test-Ollama {
    try {
        Invoke-WebRequest -Uri "$OllamaUrl/api/version" -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Find-Exe([string]$Name, [string[]]$Fallbacks) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in $Fallbacks) { if (Test-Path $path) { return $path } }
    throw "Executavel '$Name' nao encontrado."
}

try {
    if (-not (Test-Ollama)) {
        Write-Log "Ollama nao responde em $OllamaUrl; iniciando 'ollama serve'..."
        $ollama = Find-Exe "ollama" @("$env:LOCALAPPDATA\Programs\Ollama\ollama.exe")
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden
        $deadline = (Get-Date).AddSeconds(30)
        while (-not (Test-Ollama) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
        if (Test-Ollama) { Write-Log "Ollama no ar." }
        else { Write-Log "AVISO: Ollama nao respondeu em 30 s; o bot tenta mesmo assim." }
    }

    $uv = Find-Exe "uv" @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")
    $env:PYTHONIOENCODING = "utf-8"
    $env:COLUMNS = "200"   # evita quebra de linha do rich no arquivo de log
    $extra = $args -join " "
    Write-Log "Iniciando: uv run python -m vagas_bot run $extra"

    # cmd.exe redireciona os bytes UTF-8 sem conversao (o pipe do PowerShell 5.1 corromperia os acentos).
    $cmdline = "/d /s /c `"`"$uv`" run python -m vagas_bot run $extra >> `"$LogFile`" 2>&1`""
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList $cmdline -NoNewWindow -PassThru
    $null = $proc.Handle   # sem isto o ExitCode volta vazio (o handle precisa ser guardado antes do fim)
    $proc.WaitForExit()
    $code = $proc.ExitCode
    Write-Log "Fim (codigo de saida $code)."
    exit $code
} catch {
    Write-Log "ERRO: $($_.Exception.Message)"
    exit 1
}
