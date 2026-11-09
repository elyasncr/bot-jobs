# Libera o dashboard (porta 8765) para o celular na rede de casa. Rode UMA vez, como administrador:
#   powershell -ExecutionPolicy Bypass -File scripts\allow_dashboard_lan.ps1
#
# 1) Marca a rede atual como "Privada" (o Windows bloqueia conexoes de entrada em redes "Publicas").
#    So faca isso na rede de casa. Para desfazer: Set-NetConnectionProfile -NetworkCategory Public
# 2) Cria uma regra de firewall: porta TCP 8765, so perfil Privado, so a sub-rede local.
#    Para remover: Remove-NetFirewallRule -DisplayName "vagas-pj-bot dashboard (8765)"
# Arquivo mantido em ASCII: o PowerShell 5.1 le scripts sem BOM como ANSI.

param([int]$Port = 8765)

$ErrorActionPreference = "Stop"
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Rode este script como administrador (PowerShell > Executar como administrador)." -ForegroundColor Red
    exit 1
}

$profiles = Get-NetConnectionProfile | Where-Object { $_.IPv4Connectivity -eq "Internet" }
foreach ($p in $profiles) {
    if ($p.NetworkCategory -ne "Private") {
        Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
        Write-Host "Rede '$($p.Name)' ($($p.InterfaceAlias)) agora e Privada."
    } else {
        Write-Host "Rede '$($p.Name)' ($($p.InterfaceAlias)) ja era Privada."
    }
}

$name = "vagas-pj-bot dashboard ($Port)"
Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $name -Direction Inbound -Protocol TCP -LocalPort $Port `
    -Action Allow -Profile Private -RemoteAddress LocalSubnet | Out-Null
Write-Host "Regra de firewall '$name' criada (TCP $Port, perfil Privado, so rede local)."
Write-Host "Agora rode: uv run python -m vagas_bot dashboard --lan"
