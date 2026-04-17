@echo off
REM Sincroniza snapshots locales al backup en OneDrive con robocopy /MIR
REM /MIR = mirror (copia nuevos, borra los que ya no existen en origen)
REM /NJH /NJS = sin headers de robocopy para output limpio

set SRC=C:\Dev\binance_p2p_ingest\snapshots
set DST=%USERPROFILE%\OneDrive\work-files\5. Modelos\0. Alt\Snapshots_copy

echo Sincronizando snapshots a OneDrive...
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
