# Cria (ou atualiza) a tarefa que sobe o dashboard na rede de casa quando voce entra no Windows.
# Roda com o seu usuario, sem janela, sem limite de tempo; se cair, tenta de novo (3x, a cada 1 min).
# Requer ter rodado uma vez, como administrador, scripts\allow_dashboard_lan.ps1 (firewall).
#
# Uso:      powershell -ExecutionPolicy Bypass -File scripts\install_dashboard_task.ps1 [-Port 8765]
# Iniciar:  Start-ScheduledTask -TaskName vagas-pj-bot-dashboard
# Parar:    Stop-ScheduledTask -TaskName vagas-pj-bot-dashboard
# Remover:  Unregister-ScheduledTask -TaskName vagas-pj-bot-dashboard -Confirm:$false

param(
    [int]$Port = 8765,
    [string]$TaskName = "vagas-pj-bot-dashboard"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\run_dashboard.ps1"
$User = "$env:USERDOMAIN\$env:USERNAME"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`" -Port $Port" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $User `
    -Description "Dashboard do vagas-pj-bot na rede de casa (porta $Port), ao fazer logon." -Force | Out-Null

Write-Host "Tarefa '$TaskName' registrada: sobe o dashboard (porta $Port) ao fazer logon."
Write-Host "Iniciar agora:  Start-ScheduledTask -TaskName $TaskName"
