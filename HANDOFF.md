# HANDOFF.md — Estado detallado del proyecto

Última actualización: 2026-04-29

---

## Fase 1: Ingesta cruda

**Estado:** ✅ Completa y funcionando.

- `ingest.py` captura snapshots completos (BUY + SELL) del libro P2P USDT/BOB.
- Guarda JSON crudo gzipeado en `snapshots/YYYY-MM-DD/`.
- **~1,560 snapshots acumulados** (9 abr → 29 abr 2026), cadencia ~10 min.
  Días recientes: 138/día (cobertura ~96% del esperado, gap mínimo por jitter).
  Hueco de DNS local 28-abr 05:26→06:07 UTC (~5 snapshots fallidos como
  WARNING en `logs/ingest.log`; loop sobrevivió sin relanzar).
- Modos: una captura, `--loop` (cada 10 min), `--dry-run`.
- **Watchdog activo:** `watchdog.py` corre cada 5 min vía Windows Task Scheduler
  ("P2P Watchdog", configurada con `pythonw.exe` para que no muestre consola).
  Chequea último snapshot <15 min y verifica con `Get-CimInstance` si hay
  proceso `ingest.py` activo. Si está caído, relanza con `DETACHED_PROCESS`.
  Loop ininterrumpido desde el 2026-04-24 18:44 (≥3 días, 0 caídas).
- Corre en local. Hosting pendiente.

### Corrección histórica importante

El `tradeType` del API de Binance P2P es desde la perspectiva del **taker**,
no del maker. Esto significa:
- **BUY** = taker compra USDT → maker vende USDT al taker
- **SELL** = taker vende USDT → maker compra USDT del taker

Esto afecta la lectura de VWAP y spreads: el "precio BUY" es el precio al que
un taker puede comprar USDT, o sea el precio al que el merchant vende.

---

## Fase 2: Normalización

**Estado:** ✅ Completa.

`normalize.py` lee snapshots crudos y produce `p2p_normalized.db` (SQLite).
1 fila = 1 anuncio en 1 snapshot. PK: `(snapshot_ts_utc, side, adv_no)`.
Idempotente. Exporta CSV opcional con `--export-csv`.

### Features

- **Doble entrada:** lee de `snapshots/` local + directorio de backup opcional
  (configurable vía env `P2P_BACKUP_DIR`, p. ej. OneDrive/Dropbox/disco externo).
  Flag `--no-input2` para ignorar el backup. Deduplica por nombre de archivo.
- **Aplanado base:** extrae price, surplus, cantidad, min/max por transacción
  (BOB y USDT), comisiones, banks, metadata del merchant.
- **quality_tier (A/B/C):**
  - **A:** merchant + ≥100 órdenes/mes + ≥95% completado + ≥500 USDT surplus (~50%)
  - **B:** merchant que no llega a A, o user con ≥20 órdenes/mes (~27%)
  - **C:** resto (~23%)
- **banks como tags:** JSON array + `n_banks`.
- **Validación estructural:** **0 restricciones estructuradas al taker** en
  todo el libro boliviano, **0 remarks/auto_reply con keywords KYC**.

### Pendientes no-bloqueantes

- `minSingleTransAmount` como flag en VWAP → decisión: ignorar en métrica principal.
- VWAP alternativo usando `maxSingleTransAmount` → postpuesto a final del proyecto.

---

## Fase 3: Análisis / Dashboard

**Estado:** 🟢 Sustancialmente construida, dashboard funcional (~770 KB).
Publicado en GitHub Pages: `https://research-star.github.io/binance_p2p_ingest/`.

`dashboard.py` genera `index.html` autocontenido con Plotly.js (más un alias
`p2p_dashboard.html` local por compatibilidad, no trackeado).
Todo se recalcula desde `p2p_normalized.db`. Opcional `--csv` para exportar
métricas por snapshot.

### Métricas / Paneles implementados (11)

1. **VWAP por profundidad** (5/10/25/50%) con bandas — serie temporal BUY+SELL
2. **Spread efectivo** a múltiples profundidades (5/10/25/50%)
3. **Profundidad por lado** (BUY vs SELL) — área apilada
4. **Curva de deciles** (la "tijera") — VWAP acumulado 10%→100%
5. **Ratio SELL/BUY** — asimetría de oferta/demanda
6. **Concentración top-5 merchants** — % controlado por los 5 mayores
7. **Cobertura por banco** — tabla con anuncios, profundidad, %
8. **Merchants principales** — tabla top 10 BUY y SELL side-by-side
9. **Volatilidad intradiaria** — rango (max−min) VWAP por día (solo vista "Por día")
10. **Merchants activos** — serie temporal de merchants únicos + flujo nuevos/desaparecidos
11. **Mapa de calor hora × métrica** — 24h (Bolivia UTC−4) × 6 métricas, normalizado

### Features del dashboard

- **Toggle temporal (en orden):** Cada snapshot → Por hora → Por día. Cada
  vista usa el último snapshot de cada período.
- **Sistema de temas:** 5 presets en la barra (Claro, Beige, Oscuro + Otros
  con Negro/ink) + temas custom guardables (import/export JSON, máx 5).
- **Paneles movibles y redimensionables:** drag & drop entre posiciones,
  toggle ancho completo/medio, layout persiste en `localStorage`.
- **Eje X profesional:** `nticks: 8`, `tickformat: '%d %b'`, `tickangle: -30`
  en todos los gráficos temporales (Plotly elige posiciones automáticamente).
- **Hover dinámico por vista:** `hoverformat` cambia según vista activa —
  `%d %b · %H:%M` en "Cada snapshot", `%d %b · %Hh` en "Por hora",
  `%d %b` en "Por día" (commit `462ac21`, 2026-04-28).
- **Huecos visibles:** Python detecta gaps >20 min entre snapshots; JS los
  renderiza como franjas grises semitransparentes en todos los gráficos
  temporales (`shapes: rect, opacity:0.08`). Aclarado en descripción del VWAP.
- **Interacción Plotly:** drag-to-pan, scroll zoom, rangeslider en los 5 gráficos
  temporales, hover mode `x unified`. Leyendas arriba (`y:1.08`).
- **BCB referencial (`bcb_referencial.py`):**
  - Histórico de **compra**: scraper de la tabla HTML en
    `/valor_referencial_compra_svg_v2.php` (fila "BANCOS PROMEDIO PONDERADO"),
    desde 1-dic-2025.
  - Histórico de **venta**: scraper de los pares `cell-text`/`cell-value` (con
    variantes `--highlight`) en `/valor_referencial_venta_svg.php`, ~106 días.
  - Merge por fecha en `bcb_referencial.json` (`{fecha, compra, venta, source}`).
  - KPI "TC Referencial BCB" + serie temporal en el VWAP (con `connectgaps:false`
    para que fines de semana se vean como cortes naturales).
- **Líneas de referencia en el VWAP:** BCB Ref Compra y Venta visibles por
  default, BCB oficial 6.96 oculto por defecto (aplastaba la escala).
- **Filtro temporal del histórico BCB:** `load_bcb_ref(first_date)` filtra
  para que solo se grafiquen fechas dentro del rango de snapshots.

---

## Archivos del proyecto

| Archivo | Rol |
|---|---|
| `ingest.py` | Captura snapshots del libro P2P |
| `normalize.py` | Aplanar snapshots a SQLite |
| `dashboard.py` | Generar HTML autocontenido |
| `bcb_referencial.py` | Scraper compra (tabla v2) + venta (SVG hist) del BCB |
| `config.py` | Constantes compartidas (BCB_RATE, rutas default, intervalos). Importado por todos los scripts productivos. |
| `template.html` | Plantilla HTML del dashboard (CSS/JS). `dashboard.py` la lee y reemplaza el `__DATA_PLACEHOLDER__`. |
| `scripts/watchdog.py` | Relanzar loop de ingesta si se cae |
| `scripts/update.bat` | Pipeline: bcb → normalize → dashboard (con `PYTHONIOENCODING=utf-8`) |
| `scripts/backup.py` | Backup a Hetzner Storage Box (SFTP vía rclone). Subcomandos: db, snapshots, prune, verify, restore, status |
| `scripts/test_backup_retention.py` | Tests unitarios de la lógica GFS (sin frameworks externos) |
| `backup.env` | Credenciales y paths del Storage Box. **Gitignored.** Plantilla en `backup.env.example` |
| `.claude/skills/actualizar-dashboard/SKILL.md` | Skill local que ejecuta el pipeline end-to-end con verificación por paso. Soporta `--publish` (push a Pages) y sync opcional si `P2P_BACKUP_DIR` definida. Reemplaza correr `scripts/update.bat` a mano. Creada 2026-04-29. |
| `scripts/sync_snapshots.bat` | `robocopy /MIR` snapshots → `$P2P_BACKUP_DIR` |
| `scripts/watchdog.bat` | Wrapper para Task Scheduler (no usado actualmente: la tarea corre `pythonw.exe scripts\watchdog.py` directo) |
| `p2p_normalized.db` | SQLite generado (reconstruible, no trackeado) |
| `bcb_referencial.json` | Histórico acumulado del BCB (sí trackeado, ~106 entradas) |
| `index.html` | Dashboard final (regenerado por update.bat, servido por GitHub Pages) |

---

## Operación diaria

1. **`ingest.py --loop`** corre 24/7 en background.
2. **Watchdog** (Task Scheduler "P2P Watchdog", cada 5 min) lo relanza si cae.
3. Para refrescar el dashboard publicado, opciones:
   - **Recomendado:** decirle a Claude "actualizá el dashboard" (sin push) o
     "actualizá el dashboard --publish" (con push). La skill
     `actualizar-dashboard` corre el pipeline con verificación por paso.
   - **Manual:** `scripts\update.bat` + `git add . && git commit -m "..." && git push`.
   - El push gatilla rebuild de GitHub Pages (~30-60s).
   - Pages a veces deja deployments atascados — se desbloquean marcándolos
     `inactive` vía API y empujando un commit nuevo.

### Gotchas operativos

- **Encoding `cp1252` en Windows:** ✅ resuelto el 2026-04-29. Los `print()`
  de `normalize.py` y `bcb_referencial.py` ya no usan caracteres fuera de
  ASCII (`✓` → `[OK]`, `→` → `->`, `⚠` → `[WARN]`, `── ──` → `--- ---`,
  `—` → `--`, `·` → `|`). Los scripts corren limpio en cualquier shell de
  Windows sin `PYTHONIOENCODING=utf-8`. `update.bat` y la skill mantienen
  la env var por defensa pero ya no es necesaria.

### Refactor de organización (2026-04-29)

- `config.py` centraliza constantes (BCB_RATE, rutas default, intervalo de
  ingesta, umbral del watchdog). Todos los scripts productivos importan de ahí.
- `template.html` extraído de `dashboard.py` (antes inline como `HTML_TEMPLATE`).
  `dashboard.py` lo lee con `TEMPLATE_HTML.read_text()` y hace el replace del
  placeholder. Editar el dashboard visual = editar `template.html`.
- `scripts/` agrupa los wrappers operativos (watchdog.py + .bat, update.bat,
  sync_snapshots.bat). Todos los `.bat` hacen `cd /d %~dp0..` para volver a la
  raíz del proyecto antes de ejecutar.
- Task Scheduler "P2P Watchdog" actualizado a `pythonw.exe scripts\watchdog.py`
  (WD sigue siendo la raíz del proyecto).
- **BCB agendado diario:** ✅ resuelto el 2026-04-29. Task Scheduler
  `BCB Referencial Diario` corre `pythonw.exe bcb_referencial.py` lunes a
  viernes a las 12:00 hora Bolivia (UTC−4). El BCB publica el referencial
  por la mañana, así que al mediodía ya está disponible.

---

## Backups laptop-pull: cómo operar y restaurar

**Estado:** 🟢 implementado. End-to-end real pendiente hasta cerrar 5.2 (deploy
del código al VPS Hetzner).

**Arquitectura:** la laptop hace **pull desde el VPS** vía ssh/scp/sftp (todo
built-in en OpenSSH client de Win11; rsync NO se usa para evitar instalar
software adicional). Snapshots son inmutables → pull incremental por filename
diff via `sftp -b` batch mode. Costo recurrente: $0.

### Setup inicial (una vez por máquina)

1. **OpenSSH client en Windows** (ya viene en Win11; en Win10 verificar con
   `Get-WindowsCapability -Online -Name OpenSSH.Client*`).
2. **Generar SSH key** específica del VPS (si no existe ya):
   ```
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_hetzner -C "hetzner $(date +%Y-%m)"
   ```
   Subir la pública al VPS (`ssh-copy-id` o append manual a
   `/root/.ssh/authorized_keys`).
3. **`apt install sqlite3` en el VPS** (~200 KB, requerido para el
   `.backup` consistente).
4. **Configurar `backup.env`** (gitignored):
   ```
   cp backup.env.example backup.env
   # editar con VPS_HOST, VPS_USER, VPS_PORT, VPS_DB_PATH, VPS_SNAPSHOTS_PATH,
   # SSH_KEY_PATH, LOCAL_BACKUP_ROOT
   ```
5. **Smoke test de conectividad**:
   ```
   ssh -i ~/.ssh/id_ed25519_hetzner root@<VPS_HOST> 'echo ok && which sqlite3'
   ```

### Comandos diarios

```
python scripts/backup.py db          # ssh+sqlite3 .backup → scp pull → cleanup
python scripts/backup.py snapshots   # ssh+find diff → sftp -b batch get
python scripts/backup.py prune       # GFS sobre $LOCAL_BACKUP_ROOT/db/
python scripts/backup.py status      # resumen rápido
python scripts/backup.py verify      # cuenta + tamaño locales
```

### Pipeline interno

- **db**: SSH al VPS → `sqlite3 $VPS_DB_PATH ".backup /tmp/p2p_backup_<stamp>.db"`
  → `scp` pull a `~/backups/db/p2p_normalized_<stamp>.db` → SSH cleanup del
  tmp remoto (en `finally`, garantizado).
- **snapshots**: SSH al VPS → `find $VPS_SNAPSHOTS_PATH -type f -name '*.json*'`
  → diff con files locales por path relativo → `sftp -b` batch mode con `get`
  para los nuevos. Una sola conexión SFTP, no scp-per-file.

### Política de retención GFS (solo db/, snapshots/ se conservan forever)

- **7 daily**: el más reciente de cada uno de los últimos 7 días distintos con backup.
- **4 weekly**: el más antiguo de cada una de las 4 ISO weeks inmediatamente
  anteriores al tramo daily (semanas que no se cruzan con daily).
- **3 monthly**: el más antiguo de cada uno de los 3 meses anteriores al tramo weekly.
- **Total**: hasta 14 versiones, ~125 días de cobertura.

Gaps en el calendario (días sin backup por VPS caído) se saltan: el tramo
daily son los **7 días distintos con ≥1 backup**, no los 7 días calendario.

Lógica testeada en `scripts/test_backup_retention.py` (13 casos, todos
pasando: empty/single, multi-per-day, gaps, steady-state, idempotencia,
no-overlap entre tranches).

### Restaurar

```
python scripts/backup.py restore --target /tmp/restore-test
# trae la última versión por default. Para una específica:
python scripts/backup.py restore --target /tmp/restore-test \
                                  --version 2026-05-07T120000Z
```

Validación: comparar checksums con la DB local original:

```
python scripts/checksum_db.py /tmp/restore-test/p2p_normalized_*.db p2p_normalized.db
# debe imprimir "IDENTICAL"
```

### Estructura local

```
$LOCAL_BACKUP_ROOT/    (default: ~/backups)
├── db/
│   ├── p2p_normalized_2026-05-07T120000Z.db
│   ├── p2p_normalized_2026-05-08T120000Z.db
│   └── ...
└── snapshots/         ← mirror del VPS (inmutable, sin retención)
    └── YYYY-MM-DD/...
```

### Scheduling vía Windows Task Scheduler

`scripts/install_task_scheduler.ps1` registra una tarea `Binance P2P Backup`
que dispara `db && snapshots && prune` diario a las 04:00 hora local. **No se
ejecuta automáticamente** — corré explícitamente:

```
# Mostrar el plan (no registra nada)
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Show

# Registrar la tarea
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Register

# Ver estado
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Status

# Desregistrar
powershell -ExecutionPolicy Bypass -File scripts\install_task_scheduler.ps1 -Action Unregister
```

La tarea invoca Git Bash con `python scripts/backup.py db && snapshots && prune`
en el directorio del repo. Trigger configurable con `-Time HH:mm`.

### Logging

Una línea estructurada por operación a stderr, mismo estilo que `normalize.py`:

```
[backup] mode=db target=p2p_normalized_2026-05-07T120000Z.db size_mb=537.1 sqlite_backup_s=4.20 scp_pull_s=42.50
[backup] mode=snapshots remote=2700 local_before=2685 pulled=15/15 duration_s=3.10
[backup] mode=prune total=15 keep=14 deleted=1 duration_s=0.05
```

### Lockfile

`backup.py` usa lockfile cooperativo per-subcomando (`.backup.<cmd>.lock`,
PID-aware). Diseñado para correr vía Task Scheduler sin overlap con
instancias previas.

### Validación

- **Unit tests** (sin red): `python scripts/test_backup_retention.py` corre
  los 13 casos de la lógica GFS. Idempotencia, gaps, steady-state,
  oldest-of-week / oldest-of-month, no-overlap entre tranches.
- **Smoke test contra VPS** (manual, requiere VPS configurado):
  1. `ssh -i ~/.ssh/id_ed25519_hetzner root@<VPS_HOST> 'echo ok'`
     (valida key + conectividad)
  2. Subir un `p2p_normalized.db` de prueba al VPS:
     `scp local.db root@VPS:/opt/binance_p2p/p2p_normalized.db`
  3. `python scripts/backup.py db` → debe aparecer en `~/backups/db/`.
  4. `python scripts/backup.py restore --target /tmp/r` y comparar con
     `scripts/checksum_db.py` → `IDENTICAL`.
- **End-to-end con datos reales**: pendiente hasta deploy del proyecto
  productivo al VPS (5.2).

---

## Auditoría visual (2026-04-29) — ✅ Corregida

Hallazgos detectados el 27-abr y resueltos en bloque el 29-abr:

**Alta** (todo en español + KPIs claros):
- ✅ BUY/SELL → Compra/Venta en Volatilidad, Merchants activos (Flow), Ratio,
  Spread, sub-headers de Merchants principales y heatmap labels.
- ✅ KPI Asimetría: subtítulo "Venta / Compra (profundidad)" + decimales `.toFixed(2)`.
- ✅ KPI TC Referencial BCB: label aclarado a "TC Referencial BCB (venta)";
  subtítulo agrega unidad "BOB/USDT".
- ✅ KPI TC Oficial BCB: subtítulo "Prima P2P vs oficial: +X%" + `bcb_rate.toFixed(2)`.

**Media** (unidades + headers):
- ✅ Tabla Merchants: `USDT`/`%`/`VWAP` → `Profundidad (USDT)` / `% del lado` /
  `VWAP (BOB)`.
- ✅ Ejes Y con título: VWAP `BOB/USDT`, Spread `BOB`, Profundidad `USDT`,
  Ratio `×` (con `ticksuffix:'×'`).
- ✅ Tooltips: `hovermode:'x unified'` ya muestra el yaxis title arriba — al
  agregar títulos quedaron contextualizados sin tocar `hovertemplate`.

**Baja** (pulido):
- ✅ Decimales uniformes: precios `.4f` (VWAP, Spread, Decile, Volatilidad);
  porcentajes `.2f` (Concentración); ratios `.2f` (KPI Asimetría, gráfico Ratio);
  profundidad `,.0f` (no tiene sentido decimal en USDT enteros grandes).
- ✅ Descripción de Curva de deciles: agregada frase "La «tijera» revela
  anuncios trampa" en el subtítulo del panel.
- Capitalización: "Por día" / "por día" no aparece minúsculo en código actual.

---

## Pendientes

- [ ] **Hosting de la ingesta** (Oracle Free vs Hetzner €4/mes) — postpuesto,
      el loop corre en local con watchdog estable.
- [x] **GitHub Pages** — publicado en `research-star.github.io/binance_p2p_ingest/`.
- [x] **Repo Git + `.gitignore`** — inicializado. Historial saneado con
      `git filter-repo` (sin datos personales).
- [x] **Watchdog operativo** — Task Scheduler corriendo cada 5 min.
- [x] **Histórico BCB compra+venta scrapeado** — 106 días reales del BCB.
- [x] **Auditoría visual** — corregida en bloque el 2026-04-29 (Alta+Media+Baja).
- [ ] **VWAP alternativo con `maxSingleTransAmount`** — postpuesto a final.
- [ ] **Análisis de reacción a eventos macro** (feriados, anuncios BCB,
      quincenas de pago, etc.).
- [ ] **Automatizar `update.bat` + push** vía Task Scheduler (cada N horas)
      para que Pages se refresque sin intervención manual.
- [x] **Agendar `bcb_referencial.py` diario** — Task Scheduler "BCB Referencial
      Diario", lun-vie 12:00 BOL (2026-04-29).
- [x] **Encoding ASCII en `print()` de normalize/bcb** — eliminado el
      requerimiento de `PYTHONIOENCODING=utf-8` (2026-04-29).
- [ ] Limpiar carpeta `.json` espuria en `snapshots/2026-04-09/`.
