# Binance P2P USDT/BOB — Fase 1: Ingesta

Captura snapshots crudos del libro P2P de Binance para el par USDT/BOB.
Solo guarda data cruda. Cero transformacion. Eso viene en Fase 2.

## Setup

Requiere Python 3.10+ (por el type hint `Path | None`).

```bash
pip install -r requirements.txt
```

## Uso

### Una sola captura (manual)

```bash
python ingest.py
```

Crea un archivo tipo `snapshots/2026-04-09/20260409T143012Z_snapshot.json.gz`.

### Loop continuo (mientras tengas la compu prendida)

```bash
python ingest.py --loop               # cada 10 min por default
python ingest.py --loop --interval 300 # cada 5 min
```

Ctrl+C para detener. Los errores no matan el loop, se loguean y sigue.

### Dry run (probar sin escribir)

```bash
python ingest.py --dry-run
```

Util para confirmar que el endpoint responde y ver cuantos anuncios devuelve,
sin ensuciar la carpeta snapshots.

### Periodico en background (sin mantener terminal abierta)

**Linux / macOS (cron)**, cada 10 min:

```cron
*/10 * * * * cd /ruta/al/proyecto && /usr/bin/python3 ingest.py >> logs/cron.log 2>&1
```

**Windows (Task Scheduler)**:
Crea una tarea basica que ejecute `python.exe` con argumento `ingest.py` y
"Start in" apuntando al directorio del proyecto. Trigger: cada 10 minutos.

## Estructura de salida

```
snapshots/
  2026-04-09/
    20260409T143012Z_snapshot.json.gz
    20260409T144014Z_snapshot.json.gz
    ...
logs/
  ingest.log
```

Cada `snapshot.json.gz` contiene:

```
{
  "schema_version": "v1",
  "captured_at_utc": "2026-04-09T14:30:12Z",
  "capture_duration_s": 3.21,
  "endpoint": "...",
  "asset": "USDT",
  "fiat": "BOB",
  "sides": {
    "BUY":  { "pages": [...], "total_declared_by_api": 147, "stop_reason": "last_page" },
    "SELL": { "pages": [...], "total_declared_by_api": 203, "stop_reason": "last_page" }
  }
}
```

Cada `page` dentro de `pages` guarda su `http_status`, `latency_ms`, `attempt`,
el `response` completo que devolvio Binance, y `error` (null si ok).

Los huecos (fallos de red, rate limit, etc.) quedan registrados explicitamente
con `error != null` en lugar de desaparecer en silencio. Esto es importante
para la Fase 2 y para diagnosticar problemas.

## Estimacion de tamano

- ~1 snapshot cada 10 min = 144/dia
- ~30-60 KB gzipeado cada uno
- **Total: ~5-10 MB/dia, ~2-4 GB/ano**

Cabe comodamente en cualquier lado. Si guardas el directorio completo
en un disco externo, USB o Dropbox antes de decidir hosting, estas cubierto.

## Parametros modificables

Estan todos arriba de `ingest.py` como constantes en MAYUSCULAS:
`ROWS_PER_PAGE`, `MAX_PAGES`, `REQUEST_TIMEOUT_S`, etc. Si necesitas cambiarlos,
es solo editar el archivo.

## Nota importante

El endpoint `/bapi/c2c/v2/friendly/c2c/adv/search` NO es parte de la API
publica documentada de Binance. Es el endpoint interno que usa el sitio web
de Binance P2P. Funciona hace anos sin cambios significativos, pero Binance
puede cambiarlo o bloquearlo sin aviso. Si eso pasa:

1. Revisar si el `User-Agent` o los headers cambiaron.
2. Abrir Binance P2P en el navegador, abrir DevTools > Network, filtrar por
   "adv/search" y copiar el request actualizado.
3. Actualizar `BASE_PARAMS` y `HEADERS` en `ingest.py` con lo que uses.

## Dashboard (GitHub Pages)

El dashboard HTML autocontenido se genera con `dashboard.py` y se llama
`index.html` para que GitHub Pages lo sirva por defecto.

### Actualizar y publicar

```bash
scripts\update.bat                                   # bcb + normalize + dashboard
git add index.html bcb_referencial.json      # o: git add .
git commit -m "update dashboard"
git push
```

El dashboard queda servido en:

```
https://<tu-usuario>.github.io/binance_p2p_ingest/
```

(Reemplazá `<tu-usuario>` por tu handle de GitHub.)

### Activar GitHub Pages (una sola vez)

1. Abrí el repo en GitHub → **Settings**.
2. En el sidebar izquierdo, click en **Pages**.
3. En **"Build and deployment" → Source**, seleccioná **"Deploy from a branch"**.
4. Debajo, en **Branch**, elegí:
   - Branch: `main` (o la branch que uses)
   - Folder: `/ (root)`
5. Click **Save**.
6. Esperá 1–2 minutos. GitHub te mostrará arriba un cartel verde con la URL
   (`Your site is live at https://...`).
7. Cada `git push` actualiza el dashboard en ~30–60 segundos.

**Notas:**
- `snapshots/`, `p2p_normalized.db`, `logs/` NO se suben (están en `.gitignore`).
  Solo se sube el HTML generado y `bcb_referencial.json`.
- Si el repo es privado, Pages público requiere plan Pro. Si querés, podés
  hacer el repo público solo para el dashboard (la data está en la DB local,
  no se sube).

## BCB referencial diario (Task Scheduler)

`bcb_referencial.py` se agenda en Windows Task Scheduler para correr **una
vez por día, lunes a viernes a las 12:00 hora Bolivia (UTC−4)**. El BCB
publica el referencial cada mañana, así que al mediodía ya está disponible.

**Tarea registrada:** `BCB Referencial Diario`. Comando equivalente en
PowerShell (admin) para reproducir en otra máquina:

```powershell
$action = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "bcb_referencial.py" -WorkingDirectory "C:\Dev\binance_p2p_ingest"
# Nota: bcb_referencial.py vive en la raíz del proyecto (no en scripts/), por eso el Argument no lleva path.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 12:00pm
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "BCB Referencial Diario" -Action $action -Trigger $trigger -Settings $settings -Force
```

El script ya no requiere `PYTHONIOENCODING=utf-8` (los caracteres no-ASCII
en `print()` fueron reemplazados por equivalentes ASCII, así corre limpio
en cualquier shell de Windows).

## Watchdog (auto-relanzador del loop)

`watchdog.py` chequea si el último snapshot tiene >15 min y relanza `ingest.py --loop`
si el proceso se murió (ej: la máquina se suspendió). No lanza un segundo loop si
ya hay uno corriendo.

**Configurar con Windows Task Scheduler (cada 5 min):**

1. Abrí Task Scheduler (`taskschd.msc`).
2. Crear tarea básica → nombre: `P2P Watchdog`.
3. Desencadenador: "Diariamente", hora de inicio: ahora. En propiedades
   avanzadas, marcá "Repetir cada: 5 minutos" con duración "Indefinida".
4. Acción: "Iniciar un programa" → `<ruta-del-repo>\scripts\watchdog.bat`.
5. En la pestaña "Condiciones", desmarcá "Iniciar solo si el equipo usa CA"
   (así corre también con batería).
6. En "Configuración", marcá "Ejecutar tarea lo antes posible tras un inicio
   programado omitido".

Una sola línea de PowerShell (admin) equivalente:

```powershell
schtasks /Create /SC MINUTE /MO 5 /TN "P2P Watchdog" /TR "%CD%\scripts\watchdog.bat" /RL LIMITED /F
```

Log en `logs/watchdog.log`. Silencio = todo bien (solo escribe cuando relanza
o detecta anomalías).
