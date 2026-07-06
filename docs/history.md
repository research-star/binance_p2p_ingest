# Historial del proyecto FinanzasBo

Decisiones cerradas y eventos pasados. Lo que importa para operar hoy vive
en `HANDOFF.md`. Esto es paper trail: cómo llegamos al estado actual.

Orden cronológico inverso (más reciente arriba).

---

## 2026-05-12: Workflow `auto-publish.yml` agregado

`.github/workflows/auto-publish.yml` (commit `a0b6c2f`) dispara
`scripts/publish_dashboard.py` en el VPS en cada push a `main`, **excepto**
cuando el único cambio es `bcb_referencial.json` (los commits del cron BCB
los recoge el cron `*/12` en su ciclo normal). Cambia el modelo operativo:
ya no hace falta `git push && esperar cron` para reflejar cambios visuales.

---

## 2026-05-11: Migración del scraper BCB a VPS cron (PR #20)

`bcb_referencial.py` ya no corre como Windows Task Scheduler local
("BCB Referencial Diario" deshabilitada en el mismo PR). Reemplazado por
cron del user `binance@p2p-ingest-prod`:

```
5,35 12-15 * * 1-5 cd /opt/binance_p2p && bash scripts/bcb_scrape_and_commit.sh \
                       >> /var/log/binance_p2p/bcb_ref.log 2>&1
```

8 corridas/día, 08:05–11:35 BO (lun-vie). Wrapper
`scripts/bcb_scrape_and_commit.sh` invoca `bcb_referencial.py` (backfill
total, idempotente), commitea + pushea a `CURRENT_BRANCH` solo si
`bcb_referencial.json` cambió.

Healthcheck del scraper (`HC_BCB`) quedó pendiente — sin él, falla del
scraper es silenciosa hasta huecos visibles en el dashboard. Ver
`HANDOFF.md` § 6 Pendientes abiertos.

---

## 2026-05-08: Backup laptop-pull implementado + smoke test

Arquitectura "laptop hace pull desde VPS" vía ssh/scp/sftp built-in en
OpenSSH client (sin rsync, sin software adicional). Snapshots son
inmutables → pull incremental por filename diff vía `sftp -b`. Costo
recurrente: $0.

**Smoke test post-cutover (2026-05-08):** dos `db` consecutivos
confirmaron IDENTICAL (`n_rows=1,035,079`, global=`e3db585bd213ff5f...`).
`restore` produce copia byte-idéntica (md5=`f8c6df21...`).

Detalle operativo: `docs/backups.md`.

---

## 2026-05-07: Cutover Hetzner

Migración del ingest productivo de laptop a VPS Hetzner.

- **Stop laptop:** 2026-05-07 22:00 UTC (PID 20192 muerto, P2P Watchdog Task Scheduler `Disabled`).
- **VPS go-live:** 2026-05-07 23:41:37 UTC (`systemctl enable --now binance-ingest.service`).
- **Gap de captura:** ~1 h 34 min entre último snapshot laptop
  (`20260507T220741Z`) y primero VPS (`20260507T234137Z`). Costo único del cutover.

### Conteos / verificación

| Métrica | Pre-migración (laptop) | Post-bootstrap (VPS) |
|---|---|---|
| `ads` rows | 935,699 | 1,030,075 |
| max `snapshot_ts_utc` | 2026-05-06T03:19:07Z | 2026-05-07T22:07:41Z |
| snapshots files | 2,709 | 2,709 (creciendo +138/día) |

**Bit-identity (Step 3.5):** `checksum_db.py` global hash local vs VPS
(post-scp, pre-`--full-rebuild`):

```
c5ad8a68fc77394854fb169197c68541a5c5b95b1a025bff23865ff67ae201b5  IDENTICAL
```

El `--full-rebuild` posterior agregó +94k filas (snapshots ya copiados pero
no procesados por la versión vieja del laptop) e introdujo el covering
index `idx_ads_flow`, justificando el crecimiento físico de la DB de
~422 MB → ~548 MB.

> Nota: `records_inserted=1,035,926` (bruto) vs `ads count=1,030,075`
> (post-dedup) es comportamiento esperado de `INSERT OR REPLACE`
> colapsando duplicados intra-snapshot que el API ocasionalmente devuelve
> en bordes de paginación BUY/SELL.

### Procedimiento de rollback (expirado 2026-05-14)

Válido durante los 7 días posteriores al cutover. **Expirado el 2026-05-14.**
Después de esa fecha, el rollback requiere bajar la DB del VPS vía
`backup.py db` (válido pero menos directo).

Procedimiento histórico:

```bash
# 1. Parar el VPS
ssh -i ~/.ssh/id_ed25519_hetzner binance@46.62.158.88 \
    'sudo systemctl stop binance-ingest.service && \
     sudo systemctl disable binance-ingest.service && \
     crontab -u binance -r'

# 2. En la laptop: restaurar la DB pre-migración
cd /c/Dev/binance_p2p_ingest
mv p2p_normalized.db p2p_normalized.db.failed-vps
mv p2p_normalized.db.pre-migration-20260507T180022Z p2p_normalized.db

# 3. Re-habilitar la P2P Watchdog del Task Scheduler
schtasks /Change /TN "P2P Watchdog" /ENABLE

# 4. Lanzar el loop
pythonw.exe ingest.py --loop
```

`p2p_normalized.db.pre-migration-20260507T180022Z` quedó intacto en la
laptop hasta esa fecha como reserva única de rollback duro.

### Limitación bulk-seed inicial (operación one-time)

`backup.py snapshots` usa `sftp -b` batch — eficiente para incremental
pero inviable para bulk-pull desde cero (~36 min para 2,710 archivos
chicos). Mitigación manual:

```bash
ssh -i ~/.ssh/id_ed25519_hetzner binance@46.62.158.88 \
    'cd /opt/binance_p2p && tar -cf - snapshots' \
    | tar -xf - -C ~/backups/
```

(~50 s para 150 MB / 2,710 archivos.) Mejora futura no-bloqueante: flag
`--bulk-seed` en `backup.py snapshots`.

---

## 2026-04-29: Refactor de organización + auditoría visual + encoding cp1252

### Refactor de organización

- `config.py` centraliza constantes (BCB_RATE, rutas default, intervalo
  de ingesta, umbral del watchdog). Todos los scripts productivos
  importan de ahí.
- `template.html` extraído de `dashboard.py` (antes inline como
  `HTML_TEMPLATE`). `dashboard.py` lo lee con `TEMPLATE_HTML.read_text()`
  y hace el replace del placeholder. Editar el dashboard visual =
  editar `template.html`.
- `scripts/` agrupa los wrappers operativos (watchdog.py + .bat, update.bat,
  sync_snapshots.bat). Todos los `.bat` hacen `cd /d %~dp0..` para volver
  a la raíz del proyecto antes de ejecutar.
- Task Scheduler "P2P Watchdog" actualizado a
  `pythonw.exe scripts\watchdog.py` (WD sigue siendo la raíz del proyecto).
  *Nota: la tarea quedó `Disabled` tras el cutover Hetzner del 2026-05-07.*

### Auditoría visual (cerrada en bloque)

Hallazgos detectados el 27-abr y resueltos el 29-abr.

**Alta** (idioma + KPIs):
- BUY/SELL → Compra/Venta en Volatilidad, Merchants activos (Flow), Ratio,
  Spread, sub-headers de Merchants principales y heatmap labels.
- KPI Asimetría: subtítulo "Venta / Compra (profundidad)" + decimales `.toFixed(2)`.
- KPI TC Referencial BCB: label "TC Referencial BCB (venta)" + unidad "BOB/USDT".
- KPI TC Oficial BCB: subtítulo "Prima P2P vs oficial: +X%" + `bcb_rate.toFixed(2)`.

**Media** (unidades + headers):
- Tabla Merchants: `USDT`/`%`/`VWAP` → `Profundidad (USDT)` / `% del lado` / `VWAP (BOB)`.
- Ejes Y con título: VWAP `BOB/USDT`, Spread `BOB`, Profundidad `USDT`, Ratio `×`.
- `hovermode:'x unified'` ya muestra el yaxis title arriba.

**Baja** (pulido):
- Decimales uniformes: precios `.4f`, porcentajes `.2f`, ratios `.2f`, profundidad `,.0f`.
- Descripción Curva de deciles: agregada frase "La «tijera» revela anuncios trampa".

### Gotcha encoding cp1252 (resuelto)

Los `print()` de `normalize.py` y `bcb_referencial.py` ya no usan
caracteres fuera de ASCII (`✓` → `[OK]`, `→` → `->`, `⚠` → `[WARN]`,
`── ──` → `--- ---`, `—` → `--`, `·` → `|`). Los scripts corren limpio en
cualquier shell de Windows sin `PYTHONIOENCODING=utf-8`. `update.bat` y la
skill `actualizar-dashboard` mantienen la env var por defensa pero ya no
es necesaria — vestigio que se puede limpiar.

---

## Gotchas resueltos

| # | Fecha | Issue | Resolución |
|---|---|---|---|
| 1 | 2026-04-29 | `print()` con UTF-8 crasheaba en cp1252 (Windows default) | ASCII-only en scripts productivos |
| 2 | 2026-05-07 | DB pre-migración tenía que migrarse bit-idéntica | `checksum_db.py` confirmó hash global IDENTICAL post-scp |
| 3 | 2026-05-08 | Pages a veces deja deployments atascados | Desbloqueo marcándolos `inactive` vía API + commit nuevo |

---

## Pendientes cerrados (`[x]` del HANDOFF original)

- [x] Hosting de la ingesta — VPS Hetzner desde 2026-05-07.
- [x] GitHub Pages publicado en `research-star.github.io/binance_p2p_ingest/`.
- [x] Cutover de hosting a **Cloudflare Pages** (Direct Upload) el 2026-07-06 — `finanzasbo.com` + `www` pasan a servirse desde el edge CF; `gh-pages` retenido como carril de push (dual-publish) + fallback caliente, retiro en fase posterior.
- [x] Repo Git + `.gitignore` inicializado, historial saneado con `git filter-repo`.
- [x] Watchdog operativo (laptop pre-cutover; ahora vive en VPS cron).
- [x] Histórico BCB compra+venta scrapeado (~106 días iniciales del SVG).
- [x] Auditoría visual corregida en bloque (2026-04-29, Alta+Media+Baja).
- [x] Agendar `bcb_referencial.py` diario — migrado a VPS cron 2026-05-11.
- [x] Encoding ASCII en `print()` de normalize/bcb (2026-04-29).
