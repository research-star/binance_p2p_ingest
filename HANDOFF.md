# HANDOFF.md — Contrato canon del Ingeniero Jefe

Documento corto que se lee al inicio de cada ticket. Refleja **estado vivo,
reglas operativas, y áreas en flujo**. Historia detallada y runbooks viven
aparte (`docs/history.md`, `docs/backups.md`).

Última actualización: 2026-05-18.

---

## 0. Estado vivo HOY

El proyecto productivo corre en **VPS Hetzner** (`binance@46.62.158.88`,
`/opt/binance_p2p`, venv `.venv/`). La laptop ya no ingiere — solo hace pull
de backups y, opcionalmente, dashboard local.

| Componente | Dónde corre | Cadencia | Health |
|---|---|---|---|
| `ingest.py --loop` | VPS systemd (`binance-ingest.service`) | 24/7, snapshot cada 10 min | `HC_INGEST` (ping desde watchdog) |
| `normalize.py` | VPS cron user `binance` | `*/5 * * * *` | `HC_NORMALIZE` |
| `scripts/watchdog.py` | VPS cron user `binance` | `*/5 * * * *` | pinga `HC_INGEST` si snapshot reciente |
| `bcb_referencial.py` (via `scripts/bcb_scrape_and_commit.sh`) | VPS cron user `binance` | `5,35 12-15 * * 1-5` (8 corridas/día lun-vie, 08:05–11:35 BO) | `HC_BCB` pendiente |
| `ingest_embi.py` | VPS cron user `binance` | `0 10,22 * * *` (2/día, 06:00 y 18:00 BO) | `HC_EMBI` |
| `scripts/publish_dashboard.py` | VPS cron user `binance` + GitHub Actions | `*/12 * * * *` + workflow on push a `main` | `HC_DASHBOARD` |
| Laptop ingest | ❌ desactivado | — | — |
| Laptop backup pull | local Task Scheduler (opcional) | diario 04:00 hora local | — |
| GitHub Pages | rama `gh-pages` | rebuild ~30-60 s tras push de `publish_dashboard.py` | — |

**Workflow `auto-publish.yml`:** dispara `publish_dashboard.py` en VPS en
cada push a `main`, **excepto** cuando el único cambio es
`bcb_referencial.json` (esos los recoge el cron `*/12` en su ciclo normal,
no fuerzan publish).

---

## 1. Reglas para tickets

### Antes de empezar
Leer este `HANDOFF.md` + `CLAUDE.md`. Eso es el contrato completo. Todo lo
demás es referencia (runbooks, código fuente, historia).

### Naming de branches
Formato real en este repo (CLAUDE.md dice `feature/...` — ignorá eso, está desactualizado):

- `feat/...` — nuevo código
- `fix/...` — corrección de bug
- `docs/...` — solo documentación
- `chore/...` — wiring, cleanup, scripts temporales
- `refactor/...` — cambio sin alterar comportamiento

### Convención de commits
`tipo: descripción corta`. Tipos: `feat`, `fix`, `docs`, `refactor`, `test`,
`chore`. Sub-scope opcional entre paréntesis:
`feat(chart): per-series toggle buttons for VWAP`.

### PR vs push directo
La regla operante real (no la idealizada en `CLAUDE.md`):

| Tipo de cambio | Vía |
|---|---|
| Código (features, refactors, fixes sustantivos) | **PR obligatorio** |
| `template.html`, `dashboard.py`, `normalize.py`, `ingest.py`, `bcb_referencial.py` | **PR obligatorio** |
| `bcb_referencial.json` (data autocommiteada por VPS cron) | Push directo OK |
| Docs cortos (typos, fechas, links) | Push directo OK |
| Scripts temporales (con commit subsecuente que limpia) | Push directo OK |
| Workflow init vía UI GitHub | Push directo OK |

Si dudás, abrí PR. Push directo a `main` **solo** si tu cambio cae en una
de las filas verdes.

### Dónde se toca cada cosa
- **Dashboard visual** (CSS, layout, JS de gráficos, KPIs): `template.html`.
  El 80% de los tickets visuales viven acá, **no** en `dashboard.py`.
- **Lógica de cálculo del dashboard** (queries, agregados, métricas): `dashboard.py`.
- **Pipeline crudo → SQLite**: `ingest.py` (Fase 1), `normalize.py` (Fase 2).
- **Publish a Pages**: `scripts/publish_dashboard.py` + `.github/workflows/auto-publish.yml`.
- **BCB scrape**: `bcb_referencial.py` (lógica) + `scripts/bcb_scrape_and_commit.sh` (wrapper VPS).
- **EMBI scrape (BCRD)**: `ingest_embi.py` (lógica + cron one-liner). Snapshot Excel +
  ETag cache en `/opt/binance_p2p/embi_audit/` (fuera del repo).
- **Constantes compartidas**: `config.py`.

---

## 2. Pipeline (Fase 1/2/3) — referencia técnica

### Fase 1 — Ingesta cruda

`ingest.py` captura snapshots completos del libro USDT/BOB (BUY + SELL) del
endpoint `/bapi/c2c/v2/friendly/c2c/adv/search` de Binance, guarda JSON
gzipeado en `snapshots/YYYY-MM-DD/<stem>.json.gz`. Cadencia default 10 min
(configurable vía `--interval`). Modos: una captura, `--loop`, `--dry-run`.

**`tradeType` del API (importante):** desde la perspectiva del **taker**.
- `BUY` = taker compra USDT → maker vende al taker
- `SELL` = taker vende USDT → maker compra del taker

### Fase 2 — Normalización

`normalize.py` aplana snapshots → `p2p_normalized.db` (SQLite). 1 fila =
1 anuncio en 1 snapshot. PK `(snapshot_ts_utc, side, adv_no)`. Incremental
por default vía watermark `last_snapshot_stem` en tabla `normalize_state`.
Idempotente.

Modos:
- `python normalize.py` — incremental (default), exit 0 silencioso si no hay trabajo.
- `--full-rebuild` — vacía `ads`, resetea watermark, reprocesa todo. Necesario tras
  cambios de schema o **primera corrida sobre DB vieja sin tabla `normalize_state`**.
- `--since YYYY-MM-DD` — reprocesa rango (no toca watermark, debugging).
- `--status` — muestra watermark, pendientes, totales. No procesa.

Features:
- Doble entrada: lee de `snapshots/` + `$P2P_BACKUP_DIR` opcional. Deduplica por nombre.
- `quality_tier` A/B/C materializado como columna. Threshold drift requiere `--full-rebuild`.
- `banks` como JSON array + `n_banks` (banco es tag, no filtro).
- 0 restricciones estructuradas al taker, 0 KYC keywords en remarks/auto_reply del libro boliviano.
- Lockfile cooperativo con detección de PID stale.

Optimizaciones SQLite: WAL, `synchronous=NORMAL`, `cache_size=-65536`,
`temp_store=MEMORY`, índice covering `idx_ads_flow (snapshot_ts_utc, side,
advertiser_id)`, una transacción por batch.

### Fase 2.5 — EMBI / Riesgo País (lateral)

`ingest_embi.py` descarga diariamente el Excel del BCRD ("Serie Histórica
Spread del EMBI") y lo unpivotea a tabla SQLite `embi_spreads (fecha, pais,
spread_bps)` con PK `(fecha, pais)`. Cobertura: Bolivia + 7 peers LATAM
explícitos (Argentina, Brasil, Chile, Colombia, México, Perú, Ecuador) +
Uruguay, Paraguay, Venezuela, Panamá, El Salvador, Costa Rica, Guatemala,
Honduras + agregados `global` y `latino`.

Unidad de guardado: bps (Excel viene en percentage points, ingest multiplica × 100).

Comportamiento del script:
- `If-None-Match: <etag>` (persistido en `embi_audit/.last_etag`) → BCRD
  responde 304 si el Excel no cambió. 304 = exit 0 limpio, sin tocar SQLite.
- Si 200: snapshot a `embi_audit/embi_YYYY-MM-DD.xlsx` (fecha BO), parse,
  UPSERT idempotente, rota archivos `embi_*.xlsx` con mtime > 7 días.
- Mapeo header→país canónico es **explícito** (no parsea el header). Si BCRD
  agrega columnas, el script falla con error claro en vez de poblar con basura.
- HC ping start/success/fail con body (resumen o stacktrace). Graceful si
  `HC_EMBI` vacío.

Cron: `0 10,22 * * *` UTC (06:00 y 18:00 BO, todos los días). Cobertura
dual: 18:00 BO captura el republish del mismo día (BCRD republica ~10:30 BO);
06:00 BO captura si se atrasó al día anterior. ETag hace que la mayoría de
corridas sean 304 no-op.

`dashboard.py` embebe **el histórico completo** de `embi_spreads` en el JSON
inline del `index.html` (~880 KB adicionales; payload total `index.html`
~1.67 MB). El trimming a 5 años se retiró en PR #29 adendum para soportar
el toggle "Max" del frontend que muestra todo el histórico (Bolivia
2012-11-30 → hoy, peers 2007-10-29 → hoy). Los otros rangos clippean
client-side.

**Frontend tab "Riesgo País"** (en `template.html`):
- Tab insertada entre "Guía" y el placeholder "Noticias Soon".
- Lazy render: `window.renderRiesgoPais()` se invoca solo al activar la tab
  (mismo patrón que renderBbv, renderGuide).
- 3 KPIs hero: Bolivia (último + Δ 1d), Bolivia Δ 1M (~21 hábiles), LATINO
  (último + Δ 1d).
- Multi-toggle país (10 series: Bolivia, LATINO, Global, + 7 peers LATAM) con
  patrón `.fb-stog` (idéntico al toggle VWAP del tab Dólar). Default activos:
  Bolivia + LATINO.
- Toggle rango temporal (1M / 6M / 1Y / 5Y / Max) con patrón `.ds-chip`.
  Default 1Y. Rango en *días hábiles* (no calendario) porque el Excel BCRD
  tiene gaps de fines de semana — 1M ≈ 21 obs, 5Y ≈ 1260 obs, Max = todo.
- **Styling centralizado**: paleta de colores, tooltip, ejes y grid viven en
  CSS variables (`--chart-color-*`, `--tooltip-*`, `--chart-grid`, etc.)
  bajo `:root{}` + override en `body.theme-dark{}` dentro del bloque
  `/* ── Riesgo País chart styles ── */` del `<style>` de template.html.
  El JS las consume con `getComputedStyle`. Para retocar look del chart,
  editar ese bloque CSS, no el JS.
- Bolivia destaca: ámbar saturado (`#d97706`) + line width 2.8 vs 1.4 de los
  peers + opacity 0.85 en peers para reforzar protagonismo visual.
- **Paleta por bandera nacional** (peers): Argentina celeste, Brasil verde,
  Chile rojo, Colombia azul, Ecuador amarillo, México verde oscuro, Perú
  carmesí. LATINO y Global usan grises neutros para señalar su rol de
  benchmark. Colombia usa azul (no amarillo) y México verde oscuro (no rojo)
  para evitar choques con Bolivia/Ecuador/Chile/Perú. Dark mode sube
  luminosidad de los colores oscuros (Brasil/Colombia/México/Perú).
- Theme-aware: un MutationObserver sobre `body.class` re-renderea el chart si
  el usuario cambia tema mientras la tab está visible.
- Sin nueva dependencia JS: usa Plotly ya cargado para el tab Dólar.
- Sin persistencia (no localStorage): estado de toggles en memoria de la
  sesión.

### Routing por paths (SPA + 404 trick)

URLs limpias por tab via HTML5 History API:

| Slug | Tab id (`data-tab`) | Título |
|---|---|---|
| `/` | `dollar` | FinanzasBo — Mercado P2P USDT/BOB |
| `/dpf` | `dpf` | FinanzasBo — Rendimientos DPF |
| `/bbv` | `bbv` | FinanzasBo — Bolsa Boliviana de Valores |
| `/guia` | `guide` | FinanzasBo — Guía del dashboard |
| `/riesgo` | `riesgo-pais` | FinanzasBo — Riesgo País EMBI |

El mapeo `ROUTE_MAP` vive en el JS del template.html (sección
`// ═══ TAB SWITCHING + ROUTING ═══`). Slug → tab id; el `<title>` se
actualiza junto con la activación.

**Entrada directa a sub-paths** (ej. `finanzasbo.com/bbv` desde bookmark o
link externo): GitHub Pages no encuentra el archivo y sirve `404.html`
(comiteado en `static/404.html`, copiado a la raíz de `gh-pages` por
`publish_dashboard.py`). Ese 404 redirige a `/?path=%2Fbbv`. El init del SPA
lee el `?path`, hace `history.replaceState` a `/bbv`, y activa la tab. UX:
una sola redirección casi imperceptible.

**Navegación interna**: click en tab dispara `history.pushState(slug)`. Back
y forward del browser disparan `popstate` que re-activa la tab sin recargar.

`/noticias` NO está en `ROUTE_MAP` (la tab es un placeholder "Soon"
deshabilitado). Cuando esa tab se implemente, agregar la entrada.

Paths no reconocidos caen en fallback silencioso: `history.replaceState('/')`
+ activa Dólar.

### Fase 3 — Análisis / Dashboard

`dashboard.py` lee `p2p_normalized.db` + `bcb_referencial.json` +
`template.html`, produce `index.html` autocontenido (~770 KB) con
Plotly.js. Publicado en `https://research-star.github.io/binance_p2p_ingest/`.
Opcional `--csv` exporta métricas por snapshot.

11 paneles: VWAP por profundidad, Spread efectivo, Profundidad por lado,
Curva de deciles ("tijera"), Ratio SELL/BUY, Concentración top-5 merchants,
Cobertura por banco, Merchants principales, Volatilidad intradiaria,
Merchants activos, Mapa de calor hora × métrica.

Features clave:
- Toggle temporal: Cada snapshot → Por hora → Por día.
- 5 temas preset + custom guardables, paneles drag & drop, layout
  persistente en `localStorage`.
- Huecos >20 min como franjas grises (`shapes: rect, opacity:0.08`).
- Eje X con `nticks:8`, `tickformat:'%d %b'`, `tickangle:-30`.
- Hover dinámico por vista (`%d %b · %H:%M` → `%Hh` → `%d %b`).
- BCB referencial: histórico compra (tabla v2 HTML) + venta (SVG hist),
  merge en `bcb_referencial.json` (119 entradas a la fecha). KPI + línea
  en VWAP con `connectgaps:false` para fines de semana como cortes.

---

## 3. Topología productiva VPS

**Host:** Hetzner, IP `46.62.158.88`, hostname `p2p-ingest-prod`, Ubuntu
24.04 LTS, 38 GB disco / 3.7 GB RAM / 2 GB swap (`/swapfile`,
`vm.swappiness=10`).

**User dedicado:** `binance` (uid 1000). Sudo restringido por
`/etc/sudoers.d/binance` a 5 operaciones sobre `binance-ingest.service`:
`restart`, `start`, `stop`, `enable`, `disable`. Sin sudo full.

**Paths:**
- Código: `/opt/binance_p2p/` (clone de `main`, deploy key `id_ed25519_github` privada del VPS con write access)
- venv: `/opt/binance_p2p/.venv/`
- DB: `/opt/binance_p2p/p2p_normalized.db`
- Snapshots crudos: `/opt/binance_p2p/snapshots/YYYY-MM-DD/`
- Logs: `/var/log/binance_p2p/{ingest.log, ingest.err, normalize.log, watchdog.log, bcb_ref.log, publish_dashboard.log}`
- Env vars (incluye `HC_*`): `/opt/binance_p2p/.env`

**systemd unit:** `binance-ingest.service` (`Type=simple`, `Restart=on-failure`,
`RestartSec=30`). Append a `ingest.log`/`ingest.err`.

**Cron del user `binance`:**
```
*/5  * * * *       cd /opt/binance_p2p && .venv/bin/python normalize.py
*/5  * * * *       cd /opt/binance_p2p && .venv/bin/python scripts/watchdog.py
*/12 * * * *       cd /opt/binance_p2p && .venv/bin/python scripts/publish_dashboard.py
5,35 12-15 * * 1-5 cd /opt/binance_p2p && bash scripts/bcb_scrape_and_commit.sh \
                       >> /var/log/binance_p2p/bcb_ref.log 2>&1
0    10,22 * * *  cd /opt/binance_p2p && .venv/bin/python ingest_embi.py \
                       >> /var/log/binance_p2p/embi.log 2>&1
```

**Auto-publish workflow** (`.github/workflows/auto-publish.yml`):
- Dispara en cada push a `main`, con `paths-ignore: bcb_referencial.json`.
- SSH al VPS → `git pull --rebase origin main` → borra
  `publish_dashboard.last_size` (cache bust) → `.venv/bin/python scripts/publish_dashboard.py`.
- Secret: `HETZNER_SSH_KEY` (repo settings).
- Concurrency: grupo `publish-dashboard`, `cancel-in-progress: false`.

**Healthchecks (healthchecks.io):**
- `HC_INGEST` — pingeado desde `scripts/watchdog.py` cuando hay snapshot reciente. Confirmado en código del repo.
- `HC_NORMALIZE`, `HC_DASHBOARD` — pingeados desde la cron line en VPS (no desde código del repo).
- `HC_BCB` — **pendiente** (ver § 6).
- `HC_EMBI` — pingeado desde `ingest_embi.py` (start / success-with-body / fail-with-body). Period 12h grace 6h.

**SSH desde laptop:**
```bash
ssh -i ~/.ssh/id_ed25519_hetzner binance@46.62.158.88
```
`root` está bloqueado tras hardening (`PasswordAuthentication no`,
`PermitRootLogin no`, `KbdInteractiveAuthentication no` en
`/etc/ssh/sshd_config.d/99-hardening.conf`). Usar Hetzner Rescue Console
si necesitás root real.

**Firewall + fail2ban:** `ufw` permite solo `22/tcp` (v4+v6). `fail2ban`
jail `sshd` activa.

### Verificación post-deploy

Tras merge a `main`, el flujo automático es: workflow `auto-publish` → SSH al
VPS → `git pull` → cache bust (`rm -f /var/log/binance_p2p/publish_dashboard.last_size`)
→ `publish_dashboard.py` → push a `gh-pages` → GH Pages rebuild (~30-60 s).
Verificar contra `finanzasbo.com` directo puede devolver HTML viejo porque el
CDN del custom domain cachea agresivamente — eso **no significa que el deploy
falló**. La fuente de verdad post-deploy es la rama `gh-pages`.

**1) Confirmar que el deploy completó**

- Workflow:
  ```
  gh run list --workflow=auto-publish.yml --limit 2 --json status,conclusion,headSha,databaseId,url
  gh run watch <run-id> --exit-status
  ```
- Commit de `gh-pages`:
  ```
  gh api repos/research-star/binance_p2p_ingest/commits/gh-pages \
    --jq '{sha,date:.commit.committer.date,msg:.commit.message,author:.commit.committer.name}'
  ```
  Debe tener `author: "binance VPS"` y `date` posterior al `mergedAt` del PR.

**2) Verificar el HTML en vivo evitando cache stale**

- **Preferido** — bypassa el CDN del custom domain:
  ```
  curl -sL https://raw.githubusercontent.com/research-star/binance_p2p_ingest/gh-pages/index.html -o /tmp/raw.html
  ```
- **Alternativa** — custom domain con cache-buster agresivo:
  ```
  curl -sL -H "Cache-Control: no-cache" -H "Pragma: no-cache" \
       "https://www.finanzasbo.com/?_cb=$(date +%s%N)" -o /tmp/live.html
  ```
  El cache-buster nanosegundo (`%s%N`) bustea casos donde `?_cb=<epoch>`
  integer no fue suficiente — visto en verificación de PR #36 con CDN del
  custom domain.

**3) Campo a chequear**

`meta.generated_at` (string ISO embebida en el payload JSON inline del
`index.html`) debe ser `>=` el `mergedAt` del PR. Si es anterior al merge, el
HTML que estás viendo es de un publish previo (cache stale del CDN, o el
publish post-merge aún no llegó al CDN).

**4) Diagnóstico cuando algo no cuadra**

| Síntoma | Causa probable | Acción |
|---|---|---|
| Custom domain devuelve HTML viejo, raw `gh-pages` está fresco (`generated_at` posterior al merge) | Cache CDN stale | Esperar, o re-fetch con cache-buster nanosec + headers no-cache. **NO es deploy roto.** |
| Raw `gh-pages` también está viejo (`generated_at` anterior al merge) | Deploy roto o skipeado | Investigar `gh run view <run-id>` y `/var/log/binance_p2p/dashboard.log` en el VPS. |
| Workflow dice `success` en ~5-10 s en lugar de ~20 s | Race-lock con cron `*/12` (publish salió limpio sin generar HTML porque el cron tenía el lock cooperativo) | Esperar al próximo tick del cron, o forzar manual: `ssh -i ~/.ssh/id_ed25519_hetzner binance@46.62.158.88 "cd /opt/binance_p2p && rm -f /var/log/binance_p2p/publish_dashboard.last_size && .venv/bin/python scripts/publish_dashboard.py"`. |

> **Caveat histórico** (PR #36, 2026-05-25): un cache stale del CDN se
> diagnosticó inicialmente como race-lock entre cron y workflow. La race no
> existió — el commit de `gh-pages` ya tenía timestamp posterior al merge,
> confirmando que el workflow sí pusheó a tiempo. Antes de diagnosticar
> race, **contrastar siempre el `date` del commit `gh-pages` contra el
> `mergedAt` del PR**; si el commit `gh-pages` es posterior al merge, el
> deploy está OK y el síntoma es cache stale.

---

## 4. Backups

La laptop hace **pull desde el VPS** vía ssh/scp/sftp built-in (sin rsync,
sin software adicional). Snapshots son inmutables → pull incremental por
filename diff. DB: política GFS (7 daily + 4 weekly + 3 monthly).
Subcomandos: `python scripts/backup.py {db,snapshots,prune,verify,restore,status}`.
Validado end-to-end el 2026-05-08 contra VPS productivo.

**Runbook completo (setup, retención, restore, scheduling, validación):
`docs/backups.md`.**

---

## 5. WIP / áreas calientes

Mantenido manualmente. Actualizar al abrir PR nuevo o iniciar workstream.

- **Dashboard visual** — trabajo activo en formato post-PR-H: per-series
  toggles del VWAP (Compra default), BCB Ref stepped (hv), padding del eje
  temporal, KPIs uniformes, iconos/favicon/OG image. PRs recientes: #13,
  #14, #17, #19, #21, #22.
- **BCB scraper** — recién migrado a VPS cron (PR #20, 2026-05-11).
  Healthcheck `HC_BCB` pendiente (ver § 6).
- **Auto-publish workflow** — agregado 2026-05-12 (`a0b6c2f`). Vigilar
  primeras semanas por edge cases (workflow se atasca, cache bust no toma
  efecto, race con cron `*/12`, etc.).

---

## 6. Pendientes abiertos

- [ ] **`HC_BCB` healthcheck** — crear UUID en healthchecks.io, agregar a
      `/opt/binance_p2p/.env` como `HC_BCB`, y appendear
      `&& curl -fsS --max-time 10 https://hc-ping.com/$HC_BCB > /dev/null`
      al cron line del BCB. Sin esto, falla del scraper es silenciosa.
      (Follow-up de PR #20.)
- [ ] **Cache key de `publish_dashboard.py`** — el cache (ahora
      `(n_snap, n_rows, embi_max_fecha)` desde feat/embi-ingest) sigue sin
      invalidar con cambios de código (`template.html`, `static/`).
      Consecuencia: deploys visuales sin cambio de dataset esperan hasta
      próximo snapshot + próximo tick del cron (~22 min worst case). Fix
      propuesto: agregar hash de `template.html` + `listdir(static/)`, o
      usar commit hash de main. **Ticket Notion: "Cache key de
      publish_dashboard.py no invalida con cambios de código".** Update
      2026-05-18: la pieza de embi_max_fecha cubre el caso de la tabla
      `embi_spreads`, pero el agujero genérico de "cambio de código sin
      cambio de dataset" sigue abierto.
- [ ] **`quality_tier` como VIEW** — actualmente materializado como columna.
      Threshold drift requiere `--full-rebuild` para repropagar. Mover a
      VIEW para evaluación lazy.
- [ ] **VWAP alternativo con `maxSingleTransAmount`** — postpuesto a final del proyecto.
- [ ] **Análisis de reacción a eventos macro** (feriados, anuncios BCB,
      quincenas de pago) — pendiente de prioridad.
- [ ] **Limpiar carpeta `.json` espuria en `snapshots/2026-04-09/`** —
      pendiente sin contexto suficiente; evaluar si abrir ticket o cerrar.
- [ ] **Cierre del período de gracia de rollback** (expira 2026-05-14):
      ¿borrar `p2p_normalized.db.pre-migration-20260507T180022Z` (442 MB
      untracked) de la laptop? ¿desinstalar Task Scheduler "P2P Watchdog"
      o dejar `Disabled` como reserva?

---

## 7. Hoja de estilo — tokens y theming

Sistema de design tokens introducido en `refactor/css-tokens` (PR1 invisible).
Define la "hoja de estilo compartida" del proyecto sin cambiar el archivo
físico — todo el CSS sigue viviendo inline en `template.html`, ahora con una
capa de tokens al principio del `<style>`.

### Capas del sistema visual (de menor a mayor especificidad)

1. **`:root{}` base** en `template.html` (~L25): defaults light de las vars
   semánticas (bg/text/border/color-*) y estructurales (`--nav-h`, `--sub-h`,
   `--kpi-value-size` ahora alias deprecado de `--text-5xl`).
2. **`:root{}` de design tokens** (~L26-L62): tipografías, escala de tamaños,
   radios, sombras y tooltip vars compartidos. Bloque nuevo del PR-tokens.
3. **`:root{}` extendido del chart EMBI** (~L325-L345): paleta `--chart-color-*`
   (banderas nacionales) + axis/grid (`--chart-grid`, `--chart-axis-text`,
   `--chart-spike`). Tooltip ya no vive acá — se centralizó en (2).
4. **JS dinámico** (`THEMES.paper/.slate` + `applyTheme()`, ~L946-1009):
   reescribe vars semánticas via `root.style.setProperty()` al togglear tema.
   Maneja `bg-*`, `text-*`, `color-*`, `border-color`. NO maneja design tokens.
5. **`body.theme-dark{}` CSS** (~L346-L385): overrides para las vars que no
   pasan por JS (chart palette del EMBI, `--tooltip-bg/border/text`).

### Categorías de tokens

| Categoría | Tokens | Theme-dependent | Override en |
|---|---|---|---|
| Tipografías | `--font-display`, `--font-body`, `--font-mono` | no | — |
| Tamaños texto | `--text-2xs` ... `--text-5xl` (11 niveles) | no | — |
| Radios | `--radius-xs/sm/md/lg/xl` + `--radius-pill` | no | — |
| Sombras | `--shadow-sm/md/lg/xl` | sí (pendiente) | PR2 (hoy sin override) |
| Tooltip | `--tooltip-bg/text/border/font` | sí | `body.theme-dark{}` (solo `--tooltip-bg` literal; el resto resuelve vía `--border-color` / `--text-primary` / `--font-mono` que ya son theme-aware) |
| Bg/text/border/color-* | (existentes) | sí | JS `THEMES.paper/.slate` |
| Chart EMBI | `--chart-color-*`, `--chart-grid`, etc. | sí | `body.theme-dark{}` |

### Pendientes de PR1 → PR2

- **Overrides dark de `--shadow-*`**: hoy los 4 tokens viven solo en `:root`
  con su valor único (alpha .06/.18/.24 sobre `rgba(0,0,0,...)`). En dark mode
  resuelven al mismo valor → sombras casi invisibles. Bug latente preservado
  tal cual (era el estado anterior). Override validado va en PR2.
- **Migración de colores hardcodeados**: literales hex `#1e4d7a`, `#6b7d92`,
  `#5589c0`, `#8c8c8c` que aparecen en `style="--fb-trace-color:..."` inline
  ([template.html:493-502](template.html#L493-L502)) y en `.fb-pill.active` ([template.html:373](template.html#L373)). PR2 introduce capa de
  color tokens semánticos.
- **Paleta Plotly hardcodeada en JS** (PR2c): ~25 colores en stops de heatmap,
  categorías DPF, axis text y línea Spread Evo. La mayoría no son tokenizables
  invisiblemente porque las vars semánticas existentes cambian en dark — PR2c
  decide ruta (tokens nuevos vs. fixes deliberados de dark).

**Cerrado por `fix/unify-plotly-tooltips` (PR2a):** los 3 hoverlabels Plotly
(VWAP P2P, DPF, EMBI) consumen `cssVar('--tooltip-*')`. `--tooltip-bg` apunta
ahora a `--bg-tertiary` (celeste sólido en light, override `#1c2632` en dark).
EMBI bajó `size` de 12 a 11 para unificarse. Helper `cssVar()` promovido a
scope módulo (eliminada copia local en EMBI IIFE).

### Reglas de uso

- **Cuándo agregar un token**: valor literal repetido ≥2 veces, con razón
  funcional/semántica (no accidental), con override potencial por tema.
- **Cuándo NO**: uso único (literal directo OK), valor derivable (composiciones
  como `var(--radius-sm) 0 0 var(--radius-sm)`), valores intencionalmente
  contextuales (`rgba(0,0,0,0)` transparente Plotly).
- **Plotly hoverlabel**: siempre via `cssVar('--tooltip-*')`. Los 3 charts
  ya migrados (P2P/DPF/EMBI) en `fix/unify-plotly-tooltips` (PR2a).
- **Para retocar el chart EMBI**: editar el bloque `/* ── Riesgo País chart
  styles ── */`, no el JS.
- **Tokens nuevos NO van en `THEMES.paper/.slate` JS**: ese sistema gestiona
  solo vars semánticas (bg/text/color). Los design tokens tienen su override
  dark (cuando aplica) en `body.theme-dark{}` CSS.

### Tokens deprecados / alias

- `--kpi-value-size` → alias de `--text-5xl` (`--kpi-value-size: var(--text-5xl)`
  en L25). Se mantiene para no romper `.kpi .value` ni los entries actuales
  en `THEMES.paper/.slate` JS (que escriben `'kpi-value-size':'28px'`).
  Marcar para futura limpieza cuando se migre la regla `.kpi .value` y los
  entries JS.
