<#
.SYNOPSIS
    Registra (o desregistra) la Task Scheduler que dispara backup.py diario.

.DESCRIPTION
    Tarea: "Binance P2P Backup".
    Trigger: diario 04:00 hora local (configurable con -Time).
    Action: Git Bash invoca `python scripts/backup.py db && snapshots && prune`
            en el directorio del repo.
    NO se ejecuta automáticamente: corré este script con el flag explícito.

.PARAMETER Action
    Register   → crea la tarea (idempotente: la sobrescribe si ya existe).
    Unregister → la borra.
    Status     → muestra el estado actual.
    Default    → muestra ayuda y la línea schtasks equivalente.

.PARAMETER Time
    Hora del trigger en HH:mm formato 24h. Default: "04:00".

.PARAMETER TaskName
    Nombre de la tarea. Default: "Binance P2P Backup".

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Register
    powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Status
    powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Unregister

.NOTES
    Requiere que `C:\Program Files\Git\bin\bash.exe` exista (Git for Windows).
    Si tu Git Bash está en otra ruta, editá $BashPath abajo o pasalo con -BashPath.
#>
param(
    [ValidateSet("Register", "Unregister", "Status", "Show")]
    [string]$Action = "Show",
    [string]$Time = "04:00",
    [string]$TaskName = "Binance P2P Backup",
    [string]$BashPath = "C:\Program Files\Git\bin\bash.exe"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path

# Convertir el path Windows del repo a un path POSIX para Git Bash:
# C:\Dev\binance_p2p_ingest -> /c/Dev/binance_p2p_ingest
$PosixRoot = "/" + $RepoRoot.Substring(0, 1).ToLower() + $RepoRoot.Substring(2).Replace("\", "/")

$BashCmd = "cd '$PosixRoot' && python scripts/backup.py db && python scripts/backup.py snapshots && python scripts/backup.py prune"
$BashArgs = "-lc `"$BashCmd`""

function Show-Plan {
    Write-Host ""
    Write-Host "=== Plan de registración ===" -ForegroundColor Cyan
    Write-Host "TaskName : $TaskName"
    Write-Host "Trigger  : diario a las $Time"
    Write-Host "Bash     : $BashPath"
    Write-Host "Repo     : $RepoRoot"
    Write-Host ""
    Write-Host "Comando equivalente con schtasks.exe:" -ForegroundColor Cyan
    Write-Host "schtasks /Create /TN `"$TaskName`" /TR `"`\`"$BashPath`\`" $BashArgs`" /SC DAILY /ST $Time /RL HIGHEST /F"
    Write-Host ""
    Write-Host "Para registrar, correr:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Register"
}

function Register-Task {
    if (-not (Test-Path $BashPath)) {
        Write-Error "Git Bash no encontrado en $BashPath. Instalá Git for Windows o pasá -BashPath."
        exit 1
    }
    $action = New-ScheduledTaskAction -Execute $BashPath -Argument $BashArgs -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $Time
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -DontStopIfGoingOnBatteries `
        -AllowStartIfOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Highest

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "[OK] Tarea '$TaskName' registrada (trigger diario a las $Time)" -ForegroundColor Green
    Write-Host "Para inspeccionar: Get-ScheduledTask -TaskName '$TaskName' | Format-List *"
}

function Unregister-Task {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[OK] Tarea '$TaskName' eliminada" -ForegroundColor Green
    } else {
        Write-Host "Tarea '$TaskName' no existe."
    }
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Tarea '$TaskName' no está registrada."
        return
    }
    $info = $task | Get-ScheduledTaskInfo
    Write-Host "=== '$TaskName' ===" -ForegroundColor Cyan
    Write-Host "Estado:           $($task.State)"
    Write-Host "Última ejecución: $($info.LastRunTime)"
    Write-Host "Última result:    $($info.LastTaskResult)"
    Write-Host "Próxima:          $($info.NextRunTime)"
    Write-Host ""
    Write-Host "Acción:"
    foreach ($a in $task.Actions) {
        Write-Host "  $($a.Execute) $($a.Arguments)"
    }
}

switch ($Action) {
    "Register"   { Register-Task }
    "Unregister" { Unregister-Task }
    "Status"     { Show-Status }
    "Show"       { Show-Plan }
}
