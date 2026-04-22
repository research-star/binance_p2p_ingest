@echo off
REM Actualiza el valor referencial del BCB, la DB normalizada, y el dashboard.
REM Si el scraper del BCB falla, sigue (no es critico).
REM Si normalize falla, corta (es critico).

cd /d %~dp0

echo [1/3] Bajando valor referencial BCB...
python bcb_referencial.py
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: bcb_referencial.py fallo con codigo %ERRORLEVEL%. Continuando con el JSON previo si existe.
)

echo.
echo [2/3] Normalizando snapshots...
python normalize.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: normalize.py fallo con codigo %ERRORLEVEL%. Dashboard NO generado.
    exit /b %ERRORLEVEL%
)

echo.
echo [3/3] Generando dashboard...
python dashboard.py --csv
