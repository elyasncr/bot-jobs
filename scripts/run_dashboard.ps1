# vagas-pj-bot - dashboard na rede de casa (tarefa "ao fazer logon").
# Sobe "dashboard --lan --no-browser" e grava a saida em logs\dashboard.log (sobrescrito a cada inicio).
# O log contem o link com o codigo de acesso, como data/.dashboard_token: fica so nesta maquina.
# Arquivo mantido em ASCII: o PowerShell 5.1 le scripts sem BOM como ANSI.

param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
$LogFile = Join-Path $Root "logs\dashboard.log"

function Find-Exe([string]$Name, [string[]]$Fallbacks) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($path in $Fallbacks) { if (Test-Path $path) { return $path } }
    throw "Executavel '$Name' nao encontrado."
}

try {
    $uv = Find-Exe "uv" @("$env:USERPROFILE\.local\bin\uv.exe", "$env:USERPROFILE\.cargo\bin\uv.exe")
    $env:PYTHONIOENCODING = "utf-8"
    $env:COLUMNS = "200"
    # cmd.exe redireciona os bytes UTF-8 sem conversao (o pipe do PowerShell 5.1 corromperia os acentos).
    $cmdline = "/d /s /c `"`"$uv`" run python -m vagas_bot dashboard --lan --no-browser --port $Port > `"$LogFile`" 2>&1`""
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList $cmdline -NoNewWindow -PassThru
    $null = $proc.Handle
    $proc.WaitForExit()
    exit $proc.ExitCode
} catch {
    $line = "{0} [run_dashboard] ERRO: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $_.Exception.Message
    [System.IO.File]::AppendAllText($LogFile, $line + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding $false))
    exit 1
}
