# DEPLOY_INE.md — Runbook de deploy del ingest INE Bolivia (macro)

Este documento describe el deploy a producción VPS Hetzner de los scripts
`ingest_ine_pib.py` + `ingest_ine_ipc.py`. **Se ejecuta DESPUÉS del merge
del PR** — los pasos acá NO los corre el cron de auto-publish; el deploy
backend requiere intervención manual.

VPS: `binance@46.62.158.88`, working dir `/opt/binance_p2p`, venv `.venv/`.

---

## Pre-flight (antes de tocar VPS)

1. **PR merged a `main`.** Confirmar con `gh pr view <#>` que `state=MERGED`.
2. **HC UUIDs registrados.** En `healthchecks.io` (cuenta Diego), crear:
   - "ine_pib" → copiar UUID a anotar
   - "ine_ipc" → copiar UUID a anotar
   - Ambos schedule: "Monthly" o "Custom" según preferencia. El deploy
     inicial puede usar "Grace" largo (24 h) y ajustar después.
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
`ingest_ine_pib.py`, `ingest_ine_ipc.py`, `ine_parser.py`,
`scripts/migrations/0001_ine_tables.sql`, `DEPLOY_INE.md`,
`INE_DATA_REPORT.md`. `config.py` y `HANDOFF.md` modificados.

---

## Paso 2 — Migración SQL (crear las 3 tablas en prod)

Idempotente (DDL usa `CREATE TABLE IF NOT EXISTS`). Seguro de re-correr.

```bash
ssh binance@46.62.158.88 \
  'cd /opt/binance_p2p && sqlite3 p2p_normalized.db < scripts/migrations/0001_ine_tables.sql'
```

Verificar:

```bash
ssh binance@46.62.158.88 \
  'cd /opt/binance_p2p && sqlite3 p2p_normalized.db ".tables ine_%"'
# esperado: ine_pib  ine_ingest_state  ine_ipc
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

# PIB primero (más rows). Logs van a stdout (capturar).
.venv/bin/python ingest_ine_pib.py 2>&1 | tee /tmp/ine_pib_first_run.log
# IPC.
.venv/bin/python ingest_ine_ipc.py 2>&1 | tee /tmp/ine_ipc_first_run.log
exit
```

Verificar conteos:

```bash
ssh binance@46.62.158.88 'cd /opt/binance_p2p && sqlite3 p2p_normalized.db "
SELECT cuadro, COUNT(*) AS rows FROM ine_pib GROUP BY cuadro;
SELECT cuadro, COUNT(*) AS rows FROM ine_ipc GROUP BY cuadro;
SELECT * FROM ine_ingest_state ORDER BY cuadro;
"'
```

Conteos de referencia (release 2026-05):

| Cuadro | Filas esperadas |
|---|---:|
| `pib_trim_01_01_01` | ~2 625 |
| `pib_trim_01_01_04` | ~2 550 |
| `pib_trim_02_01_01` | ~1 190 |
| `pib_anual_serie_actividad` | ~1 305 |
| `pib_anual_serie_gasto` | ~315 |
| `ipc_nacional_general` | ~432 (404 non-null) |
| `ipc_division_coicop` | ~5 252 |
| `ipc_empalmada` | ~4 320 (4 267 non-null) |

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
```

Notas:
- Los HC ping van **solo en el cuadro headline** de cada familia
  (PIB Trimestral 01.01.01 e IPC en cualquier run): si ese cuadro pasa,
  consideramos la cadencia healthy. Los otros cuadros que skipean por
  MD5 no necesitan ping individual.
- `cd /opt/binance_p2p` antes del venv, idéntico al patrón del crontab vivo.
- `stdout+stderr` → `/var/log/binance_p2p/ine_{pib,ipc}.log`. Asegurarse
  de que el directorio existe y `binance` tiene permiso de write:

```bash
sudo install -d -o binance -g binance /var/log/binance_p2p
```

(Probablemente ya está creado para los otros logs — verificar.)

---

## Paso 5 — Smoke test del cron

Esperar al próximo tick (`15 5,11,17,23 1-10 * *` → si es entre día 1-10
del mes, el próximo cuarto día). O forzar un test manual:

```bash
ssh binance@46.62.158.88
# Verificar que la env var del HC está expandida en el shell del cron
cat /var/log/binance_p2p/ine_ipc.log | tail -30

# Verificar ping en healthchecks.io: la UI debe mostrar "Up" o "Late".
```

Si el cron tiró `mode=skip` (porque el run manual ya populó), está OK —
la cadena de detección de release está funcionando.

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
