# DEPLOY_INE.md — Runbook de deploy del ingest INE Bolivia (macro)

Este documento describe el deploy a producción VPS Hetzner de los scripts
`ingest_ine_pib.py` + `ingest_ine_ipc.py` + `ingest_ine_ipp.py`. **Se ejecuta
DESPUÉS del merge del PR** — los pasos acá NO los corre el cron de
auto-publish; el deploy backend requiere intervención manual.

VPS: `binance@46.62.158.88`, working dir `/opt/binance_p2p`, venv `.venv/`.

---

## Pre-flight (antes de tocar VPS)

1. **PR merged a `main`.** Confirmar con `gh pr view <#>` que `state=MERGED`.
2. **3 HC UUIDs registrados en `healthchecks.io`** (cuenta Diego). Config
   exacta de cada uno está en la sección "Configuración de healthchecks.io"
   abajo — leerla antes de crear los checks para que el schedule en modo
   Cron, la timezone (`America/La_Paz`) y el grace time queden alineados
   con el cron real del crontab.
3. **Verificar deps en VPS.** Mínimas: `requests`, `openpyxl` (ya OK al
   2026-06-03, confirmado por la recon previa). No requiere `pandas`,
   `numpy`, `xlrd`. Opcionalmente: `beautifulsoup4` + `lxml` (sólo si en
   el futuro se cablea el re-scrape del hub como fallback de tokens
   rotados — no V1).

```bash
ssh binance@46.62.158.88 ".venv/bin/pip list | grep -iE 'openpyxl|requests'"
# esperado: openpyxl 3.1.5, requests 2.33.x
```

---

## Paso 1 — Pull del código

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && git pull --ff-only origin main && git log -1 --oneline'
```

Esperado: el último commit es el merge del PR. Archivos nuevos visibles:
`ingest_ine_pib.py`, `ingest_ine_ipc.py`, `ingest_ine_ipp.py`, `ine_parser.py`,
`scripts/migrations/0001_ine_tables.sql`, `DEPLOY_INE.md`,
`INE_DATA_REPORT.md`. `config.py` y `HANDOFF.md` modificados.

---

## Paso 2 — Migración SQL (crear las 4 tablas en prod)

Idempotente (DDL usa `CREATE TABLE IF NOT EXISTS`). Seguro de re-correr.

```bash
ssh binance@46.62.158.88 \
  'cd /opt/binance_p2p && sqlite3 p2p_normalized.db < scripts/migrations/0001_ine_tables.sql'
```

Verificar:

```bash
ssh binance@46.62.158.88 \
  'cd /opt/binance_p2p && sqlite3 p2p_normalized.db ".tables ine_%"'
# esperado: ine_pib  ine_ingest_state  ine_ipc  ine_ipp
```

```bash
ssh binance@46.62.158.88 \
  "cd /opt/binance_p2p && echo '.schema ine_pib' | sqlite3 p2p_normalized.db"
# esperado: DDL completa con PK (cuadro, periodo, dimension) + index idx_ine_pib_dim
```

---

## Paso 3 — Primer run de carga (manual, sin cron todavía)

Antes de habilitar el cron, hacer una corrida manual para confirmar que
todo el pipeline funciona en prod y poblar las tablas con la serie inicial
completa. Tiempos esperados (medidos en laptop, VPS puede variar):
**PIB ~4 min, IPC ~3 min**.

```bash
# Exportar HC UUIDs en la sesión (NO instala el cron todavía).
ssh binance@46.62.158.88
cd /opt/binance_p2p
export HC_INE_PIB='<UUID_PIB_AQUI>'
export HC_INE_IPC='<UUID_IPC_AQUI>'
export HC_INE_IPP='<UUID_IPP_AQUI>'

# PIB primero (más rows). Logs van a stdout (capturar).
.venv/bin/python ingest_ine_pib.py 2>&1 | tee /tmp/ine_pib_first_run.log
# IPC.
.venv/bin/python ingest_ine_ipc.py 2>&1 | tee /tmp/ine_ipc_first_run.log
# IPP.
.venv/bin/python ingest_ine_ipp.py 2>&1 | tee /tmp/ine_ipp_first_run.log
exit
```

Verificar conteos:

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && sqlite3 p2p_normalized.db "
SELECT cuadro, COUNT(*) AS rows FROM ine_pib GROUP BY cuadro;
SELECT cuadro, COUNT(*) AS rows FROM ine_ipc GROUP BY cuadro;
SELECT cuadro, COUNT(*) AS rows FROM ine_ipp GROUP BY cuadro;
SELECT * FROM ine_ingest_state ORDER BY cuadro;
"'
```

Conteos de referencia (releases vigentes: PIB → 2024-Q4, IPC → 2026-05, IPP → 2026-04):

| Cuadro | Filas esperadas |
|---|---:|
| `pib_trim_01_01_01` | ~2 625 |
| `pib_trim_01_01_04` | ~2 550 |
| `pib_trim_02_01_01` | ~1 225 |
| `pib_anual_serie_actividad` | ~1 305 |
| `pib_anual_serie_gasto` | ~315 |
| `ipc_nacional_general` | ~432 (404 non-null) |
| `ipc_division_coicop` | ~5 252 |
| `ipc_empalmada` | ~4 320 (4 267 non-null) |
| `ipp_nacional` | ~480 (448 non-null) |
| `ipp_grandes_grupos` | ~3 136 |

Sanity check con un valor headline conocido:

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && sqlite3 p2p_normalized.db "
SELECT indicador, ROUND(valor,2) FROM ine_ipc
WHERE cuadro=\"ipc_nacional_general\" AND periodo=\"2026-05\" ORDER BY indicador;
"'
# esperado:
# indice|150.98
# var_12m|12.51
# var_acumulada|2.62
# var_mensual|2.13
```

---

## Paso 4 — Instalar entradas cron + env vars HC

Editar el crontab del user `binance`:

```bash
ssh binance@46.62.158.88
crontab -e
```

**Convención**: env vars HC declaradas arriba (espejando el patrón de
HC_INGEST/HC_NORMALIZE/HC_DASHBOARD ya vivos). Líneas verbatim a añadir
**al final del archivo, después de las existentes**:

```cron
# Healthcheck UUIDs INE (env vars expandidas por cron al ejecutar)
HC_INE_PIB=<UUID_PIB_AQUI>
HC_INE_IPC=<UUID_IPC_AQUI>
HC_INE_IPP=<UUID_IPP_AQUI>

# INE PIB Trimestral — polleo diario en ventana post-cierre Q (release ~90 d lag)
# Cubre los 4 trimestres con holgura: día +60 a día +120 post-fin-de-Q
30 11 * * * cd /opt/binance_p2p && .venv/bin/python ingest_ine_pib.py --cuadro pib_trim_01_01_01 >> /var/log/binance_p2p/ine_pib.log 2>&1 && curl -fsS --max-time 10 https://hc-ping.com/$HC_INE_PIB > /dev/null
31 11 * * * cd /opt/binance_p2p && .venv/bin/python ingest_ine_pib.py --cuadro pib_trim_01_01_04 >> /var/log/binance_p2p/ine_pib.log 2>&1
32 11 * * * cd /opt/binance_p2p && .venv/bin/python ingest_ine_pib.py --cuadro pib_trim_02_01_01 >> /var/log/binance_p2p/ine_pib.log 2>&1

# INE PIB Anual / Serie Histórica — semanal, release ~1×/año (Q1 del año sig.)
45 11 * * 1 cd /opt/binance_p2p && .venv/bin/python ingest_ine_pib.py --cuadro pib_anual_serie_actividad >> /var/log/binance_p2p/ine_pib.log 2>&1
46 11 * * 1 cd /opt/binance_p2p && .venv/bin/python ingest_ine_pib.py --cuadro pib_anual_serie_gasto >> /var/log/binance_p2p/ine_pib.log 2>&1

# INE IPC — día 1-10 c/6 h hasta detectar release nuevo (publicación mensual)
15 5,11,17,23 1-10 * * cd /opt/binance_p2p && .venv/bin/python ingest_ine_ipc.py >> /var/log/binance_p2p/ine_ipc.log 2>&1 && curl -fsS --max-time 10 https://hc-ping.com/$HC_INE_IPC > /dev/null

# INE IPP — día 1-10 c/6 h, misma cadencia que IPC (publicación mensual)
# (offset 15 min para no traslapar requests al mismo host nube.ine.gob.bo)
30 5,11,17,23 1-10 * * cd /opt/binance_p2p && .venv/bin/python ingest_ine_ipp.py >> /var/log/binance_p2p/ine_ipp.log 2>&1 && curl -fsS --max-time 10 https://hc-ping.com/$HC_INE_IPP > /dev/null
```

Notas:
- Los HC ping van **solo en el cuadro headline** de cada familia
  (PIB Trimestral 01.01.01 e IPC/IPP en cualquier run): si ese cuadro pasa,
  consideramos la cadencia healthy. Los otros cuadros que skipean por
  MD5 no necesitan ping individual.
- `cd /opt/binance_p2p` antes del venv, idéntico al patrón del crontab vivo.
- `stdout+stderr` → `/var/log/binance_p2p/ine_{pib,ipc,ipp}.log`. Asegurarse
  de que el directorio existe y `binance` tiene permiso de write:

```bash
sudo install -d -o binance -g binance /var/log/binance_p2p
```

(Probablemente ya está creado para los otros logs — verificar.)

---

## Configuración de healthchecks.io (los 3 checks INE)

Crear 3 checks en `healthchecks.io` ANTES del Paso 4 para tener los UUIDs.
Config exacta por check abajo. El cron del VPS corre en **UTC**; las
expresiones de schedule abajo se especifican en timezone **America/La_Paz**
(equivalentemente, BO local = UTC − 4 todo el año) — HC convierte
internamente y la próxima ejecución esperada se calcula correctamente.

| Check | Schedule Type | Cron expression | Timezone | Grace time | Pings que recibe |
|---|---|---|---|---|---|
| **ine_pib** | Cron | `30 7 * * *` | `America/La_Paz` | **6 hours** | Diario, sólo desde el cron line del cuadro `pib_trim_01_01_01` (los otros 4 cuadros PIB skipean por MD5 y no pingean) |
| **ine_ipc** | Cron | `15 1,7,13,19 1-10 * *` | `America/La_Paz` | **90 min** | Hasta 4×/día entre días 1-10 del mes, hasta detectar release nuevo (luego skip por MD5). Fuera del día 1-10 NO se espera ping → schedule sólo cubre esos 10 días |
| **ine_ipp** | Cron | `30 1,7,13,19 1-10 * *` | `America/La_Paz` | **90 min** | Idéntico a IPC pero offset 15 min (no traslapar requests al mismo host nube.ine.gob.bo) |

Pasos exactos en la UI de healthchecks.io para cada uno:

1. **Add Check** → Name = `ine_pib` / `ine_ipc` / `ine_ipp` (respectivamente).
2. **Schedule** tab → seleccionar **"Cron"** (no "Simple") → pegar la expresión de la tabla.
3. **Timezone** dropdown → buscar y seleccionar `America/La_Paz`.
4. **Grace time** → setear a 6 h / 90 min según la fila.
5. Copiar el **UUID** que muestra la URL del check (`https://healthchecks.io/checks/<UUID>/details/`)
   o el botón "Show ping URL" → es lo que va en las env vars del crontab.
6. (Opcional) bajo "Notifications" / "Integrations", habilitar email / Slack /
   Telegram según preferencia para alertas de fail.

**Cómo cada script pingea al HC** (referencia rápida, ya cableado en código):

- En éxito: `requests.get(f'https://hc-ping.com/{UUID}')` (con `body=` resumen vía POST).
- En `start`: `requests.get(f'https://hc-ping.com/{UUID}/start')` — opcional, marca inicio.
- En fail: `requests.post(f'https://hc-ping.com/{UUID}/fail', data=stacktrace)`.
- Si la env var falta (`HC_INE_*` vacío) → degradación silenciosa, no aborta el ingest.

---

## Paso 5 — Smoke test del cron

El cron IPC corre `15 5,11,17,23 1-10 * *` UTC → durante los días 1-10 del
mes hay 4 ticks diarios (05:15 / 11:15 / 17:15 / 23:15 UTC, todos visibles
también como 01:15 / 07:15 / 13:15 / 19:15 hora Bolivia). Esperar al próximo
tick de esos 4. Fuera del día 1-10 hay que ejecutarlo manualmente para
validar el wiring del crontab:

```bash
ssh binance@46.62.158.88
# Confirmar que las entradas del crontab están donde corresponde.
crontab -l | grep -E 'ine_(pib|ipc)'
# Forzar un run manual con --force para que no skipee por md5_unchanged.
cd /opt/binance_p2p && .venv/bin/python ingest_ine_ipc.py --force
# Verificar el log que produciría el cron.
tail -30 /var/log/binance_p2p/ine_ipc.log
```

Después de un tick real del cron, verificar en `healthchecks.io` que el UUID
`HC_INE_IPC` muestra "Up" (último ping reciente, sin grace expirada). Si el
cron tiró `mode=skip` (porque el run manual ya populó), está OK — la cadena
de detección de release está funcionando idempotentemente.

---

## Paso 6 — Rotación de audit

El audit folder (`/opt/binance_p2p/ine_audit/{pib,ipc}/`) se crea
automáticamente en el primer run. La rotación interna (60 días) corre al
final de cada ejecución de `ingest_ine_pib.py` / `ingest_ine_ipc.py`.

Verificación opcional:

```bash
ssh binance@46.62.158.88 'ls -la /opt/binance_p2p/ine_audit/pib/ /opt/binance_p2p/ine_audit/ipc/'
```

---

## Rollback

Si algo sale mal y hay que revertir:

### Datos sólo

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && sqlite3 p2p_normalized.db "
DELETE FROM ine_pib;
DELETE FROM ine_ipc;
DELETE FROM ine_ingest_state;
"'
```

Las tablas quedan vacías pero presentes (las queda re-poblar la próxima
corrida del cron).

### Esquema completo

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && sqlite3 p2p_normalized.db "
DROP TABLE ine_pib;
DROP TABLE ine_ipc;
DROP TABLE ine_ingest_state;
DROP INDEX IF EXISTS idx_ine_pib_dim;
DROP INDEX IF EXISTS idx_ine_ipc_ind;
"'
```

### Cron

Comentar (con `#`) las 6 líneas agregadas al crontab. Los HC vars pueden
quedar — son inertes.

### Código

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && git revert <merge_sha> --no-edit'
# o si querés volver a un punto anterior:
ssh binance@46.62.158.88 'cd /opt/binance_p2p && git reset --hard <commit_anterior>'
```

(Confirmar con Diego antes de `--hard`.)

---

## Apéndice — SQL de migración inline

Contenido completo de `scripts/migrations/0001_ine_tables.sql` para deploy
de emergencia sin pull (no recomendado, pero documentado):

```sql
CREATE TABLE IF NOT EXISTS ine_pib (
  periodo         TEXT NOT NULL,
  cuadro          TEXT NOT NULL,
  dimension       TEXT NOT NULL,
  valor           REAL,
  unidad          TEXT NOT NULL,
  is_preliminary  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cuadro, periodo, dimension)
);
CREATE INDEX IF NOT EXISTS idx_ine_pib_dim
  ON ine_pib (cuadro, dimension, periodo);

CREATE TABLE IF NOT EXISTS ine_ipc (
  periodo     TEXT NOT NULL,
  cuadro      TEXT NOT NULL,
  indicador   TEXT NOT NULL,
  valor       REAL,
  unidad      TEXT NOT NULL,
  base_year   TEXT,
  PRIMARY KEY (cuadro, periodo, indicador)
);
CREATE INDEX IF NOT EXISTS idx_ine_ipc_ind
  ON ine_ipc (cuadro, indicador, periodo);

CREATE TABLE IF NOT EXISTS ine_ingest_state (
  cuadro             TEXT PRIMARY KEY,
  last_filename      TEXT,
  last_md5           TEXT,
  last_release_id    TEXT,
  last_fetched_at    TEXT NOT NULL
);
```
