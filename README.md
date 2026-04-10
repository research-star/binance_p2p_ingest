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
