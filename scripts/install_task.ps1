# Cria (ou atualiza) a tarefa agendada do vagas-pj-bot: dias uteis, 11h.
# "StartWhenAvailable" = "Executar a tarefa assim que possivel apos uma inicializacao
# agendada ter sido perdida": se o PC estava desligado as 11h, roda quando ligar.
#
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 [-Time 11:00] [-TaskName vagas-pj-bot]
# Remover:  Unregister-ScheduledTask -TaskName vagas-pj-bot -Confirm:$false

param(
    [string]$Time = "11:00",
    [string]$TaskName = "vagas-pj-bot"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root "scripts\run_daily.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Script`"" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Bot de vagas PJ: coleta, pontua e envia email (dias uteis)." -Force | Out-Null

Write-Host "Tarefa '$TaskName' registrada: dias uteis as $Time, roda ao ligar o PC se a hora foi perdida."
Write-Host "Testar agora:  Start-ScheduledTask -TaskName $TaskName"
