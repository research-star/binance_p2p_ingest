@echo off
REM Sincroniza snapshots locales a un backup con robocopy /MIR.
REM /MIR = mirror (copia nuevos, borra los que ya no existen en origen)
REM
REM Configurar destino: set P2P_BACKUP_DIR antes de correr, o editar la linea de abajo.
REM Ejemplo:
REM   set P2P_BACKUP_DIR=D:\backups\p2p_snapshots
REM   sync_snapshots.bat

cd /d %~dp0..
set SRC=%cd%\snapshots

if not defined P2P_BACKUP_DIR (
    echo ERROR: variable P2P_BACKUP_DIR no definida.
    echo Defini el destino con: set P2P_BACKUP_DIR=^<ruta^>
    exit /b 1
)

set DST=%P2P_BACKUP_DIR%

echo Sincronizando snapshots...
echo   Origen:  %SRC%
echo   Destino: %DST%
echo.

robocopy "%SRC%" "%DST%" /MIR /NJH /NJS /NDL /NP

if %ERRORLEVEL% LEQ 3 (
    echo.
    echo Sync completado OK.
) else (
    echo.
    echo ERROR: robocopy devolvio codigo %ERRORLEVEL%
)
