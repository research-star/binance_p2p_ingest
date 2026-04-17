@echo off
REM Actualiza la DB normalizada y regenera el dashboard.
REM Si normalize falla, no corre dashboard.

cd /d %~dp0

echo [1/2] Normalizando snapshots...
python normalize.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: normalize.py fallo con codigo %ERRORLEVEL%. Dashboard NO generado.
    exit /b %ERRORLEVEL%
)

echo.
echo [2/2] Generando dashboard...
python dashboard.py --csv
