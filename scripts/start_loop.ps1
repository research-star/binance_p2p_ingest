# start_loop.ps1 - Lanza ingest.py --loop como proceso desacoplado.
# Sobrevive al cierre de la terminal y de VS Code. Aborta si ya hay un loop corriendo.
# El watchdog (Task Scheduler) seguira vigilando; esto solo evita esperar 15min tras un reinicio manual.
#
# Uso:   .\scripts\start_loop.ps1
# Mata:  Stop-Process -Id <PID>

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

function Get-IngestProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*ingest.py*' } |
        Select-Object -First 1
}

$existing = Get-IngestProcess
if ($existing) {
    Write-Host "Ya hay un loop corriendo con PID $($existing.ProcessId). No lanzo otro."
    Write-Host "Para matarlo:  Stop-Process -Id $($existing.ProcessId)"
    exit 1
}

Write-Host "Lanzando ingest.py --loop desacoplado..."
Start-Process -FilePath 'pythonw.exe' -ArgumentList 'ingest.py','--loop' -WindowStyle Hidden

Start-Sleep -Seconds 2
$new = Get-IngestProcess
if ($new) {
    Write-Host "Loop lanzado OK con PID $($new.ProcessId)."
    Write-Host "Logs en: logs\ingest.log"
    Write-Host "Para matarlo:  Stop-Process -Id $($new.ProcessId)"
    exit 0
} else {
    Write-Host "ADVERTENCIA: no detecto el proceso recien lanzado. Revisa logs\ingest.log."
    exit 2
}
