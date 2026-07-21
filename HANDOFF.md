# HANDOFF.md — Contrato canon del Ingeniero Jefe

Documento corto que se lee al inicio de cada ticket. Refleja **estado vivo,
reglas operativas, y áreas en flujo**. Historia detallada y runbooks viven
aparte (`docs/history.md`, `docs/backups.md`).

Última actualización: 2026-07-15.

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
| `ingest_bcb_tco.py` (via `scripts/bcb_tco_scrape_and_commit.sh`) | VPS cron user `binance` | `*/5 0-3 * * 2-6` (cada 5 min, UTC 00:00–03:55 mar–sáb = 20:00–23:55 BO lun–vie; reintenta hasta capturar el TCO, que el BCB publica a las 20:00 BO pero a veces con atraso; baja ventana 14 días atrás + 5 adelante —la fecha del TCO es su vigencia, que va por delante de hoy—. Wrapper idempotente: commitea por **cambio de valor** (snapshot `{fecha:tco}`, ignora `fetched_at`), no solo por fecha nueva, para capturar **revisiones** del BCB sobre una fecha ya publicada (publica preliminar a las 20:00 y a veces corrige). Dos fuentes: (A) portada cada tick sin auto-freno; (B) detalle CSV histórico 1×/noche —gate por stamp `.tco_histsync_YYYYMMDD`, gitignored— que reconcilia revisiones tardías con rezago ~2 días) | `HC_BCB_TCO` (ping desde wrapper; falta crear UUID + .env) |
| `ingest_bcb_tre.py` (via `scripts/bcb_tre_scrape_and_commit.sh`) | VPS cron user `binance` | `15 12 * * *` (diario 08:15 BO; la TRE es MENSUAL pero el día de publicación varía — wrapper idempotente: no-op si ya tiene la vigencia del mes, commitea solo cuando la vigencia máxima avanza. Descubre el xlsx de la gestión más alta del listado `?q=tasas_interes`, el nombre cambia por año) | `HC_BCB_TRE` (ping desde wrapper; falta crear UUID + .env) |
| `ingest_embi.py` | VPS cron user `binance` | `0 10,22 * * *` (2/día, 06:00 y 18:00 BO) | `HC_EMBI` |
| `ingest_ine_pib.py` | Código en main, **ingest PAUSADO por decisión** — no scheduleado, no ping | (cuando se reanude) diario post-cierre Q (PIB trim) + semanal (PIB anual) | `HC_INE_PIB` (pausado en UI de Diego) |
| `ingest_ine_ipc.py` | VPS cron user `binance` | `15 5,11,17,23 1-10 * *` UTC | `HC_INE_IPC` |
| `ingest_ine_ipp.py` | VPS cron user `binance` | `30 5,11,17,23 1-10 * *` UTC (offset 15 min vs IPC) | `HC_INE_IPP` |
| `ingest_noticias.py` | VPS cron user `binance` | `7 0,11-23 * * *` UTC (07:07–20:07 BO, horario 7/7 — 14 corridas/día; minuto :07 evita colisión con `ingest_embi` a :00 y los INE a :15/:30) | `HC_NOTICIAS` (ping desde código: start/success-body/fail-body) |
| `scripts/retencion_noticias.py` | VPS cron user `binance` | `40 4 * * *` UTC (00:40 BO, hueco nocturno) — backup 20d a JSONL append-only (`noticias_ingest/data/noticias_archive.jsonl`, gitignored) + borrado físico 30d de `noticias`; bajo flock, borrado con self-archive (nunca borra sin archivar) | — (sin HC aún) |
| `ingest_asfi.py` (via `scripts/asfi_scrape_and_commit.sh`) | **DEPLOYADO** — VPS cron user `binance` (módulo ASFI en prod, PRs #200–#217) | `10 1,13,23 * * *` UTC (21:10 / 09:10 / 19:10 BO; idempotente, no-op si ASFI no publicó) + `30 12 2 * *` mensual para `ingest_asfi.py --resumir` (promueve resúmenes IA bajo el cap). Detalle en § 9 | — (sin HC; `HC_ASFI` opcional, UUID pendiente) |
| `ingest_ine_comunicado.py` | VPS cron user `binance` | `45 5,11,17,23 1-15 * *` UTC (días 1-15, 4×/día) — overlay provisional del IPC del comunicado INE antes del XLSX (#221) | — (sin HC) |
| `scripts/publish_dashboard.py` | VPS cron user `binance` + GitHub Actions | `*/12 * * * *` + workflow on push a `main` | `HC_DASHBOARD` |
| Laptop ingest | ❌ desactivado | — | — |
| Laptop backup pull | local Task Scheduler (opcional) | diario 04:00 hora local | — |
| Hosting dashboard (edge) | **Cloudflare Pages** (Direct Upload) sirve `finanzasbo.com` + `www`; rama `gh-pages` = destino del push (dual-publish) + fallback caliente | rebuild ~30-60 s tras push de `publish_dashboard.py` | — |

**Workflow `auto-publish.yml`:** dispara `publish_dashboard.py` en VPS en
cada push a `main`, **excepto** cuando el único cambio es data BCB
autocommiteada (`bcb_referencial.json` / `bcb_tco.json` / `bcb_tre.json`) — esos los recoge el
cron `*/12` en su ciclo normal, no fuerzan publish.

**Watchdog del TCO (revisión del dólar oficial):**
- **Alerta admin (frontend).** El dashboard computa `meta.bcb_tco_stale` en
  `dashboard.py:load_bcb_tco` (última vigencia publicada < hoy BO → el histórico
  dejó de actualizarse) y `template.html` muestra un banner FEO admin-only en la
  tab Dólar (`#fbTcoStaleAlert`, `fbApplyTcoStaleAlert`, gate `npAdmin.isAdmin`).
  Cero markup para el público; se revela solo con sesión admin + stale.
- **Chequeo 22:00 + 07:00 BO.** Routine cloud (`0 2,11 * * *` UTC) que re-scrapea
  la portada del BCB + reconcilia el histórico y commitea a `main` si el valor
  cambió (mismo idempotente que el wrapper). El 07:00 BO cubre el hueco matutino
  que el cron VPS (ventana nocturna 00:00–03:55 UTC) no toca — donde el BCB suele
  publicar revisiones. Convive con el cron VPS (ambos idempotentes; el routine
  hace `git pull --rebase` antes de push). Equivalente en cron VPS si se prefiere
  mover ahí: `0 2,11 * * 2-6`.

> **Estado de hosting (transitorio, cutover 2026-07-06).** El edge productivo/canónico
> de `finanzasbo.com` (+ `www`) es **Cloudflare Pages** (Direct Upload desde el mismo
> worktree que publica `gh-pages`). La rama **`gh-pages` NO se retiró**: sigue siendo el
> destino del push del dual-publish y el **fallback caliente** (pendiente de retiro en una
> fase posterior). El rollback DNS a GitHub Pages queda disponible mientras `gh-pages` viva.
> Las menciones a "GitHub Pages" más abajo en este doc deben leerse bajo este marco: el
> mecanismo (push a gh-pages, copiado de `static/`, truco 404, proxy de frescura `raw`)
> sigue vigente; lo que cambió es qué edge sirve el HTML al público.

### Cerrado desde el último refresh (2026-06-10 → 2026-06-17)

**Rediseño editorial v2 (#58-#64) — CERRADO.** Reskin completo del dashboard
sobre los design tokens del repo, dual-theme: #58 (reordenar tabs + Noticias
landing + slug `/dolar`), #59 (tab Dólar a lazy-loading), Fase 1 fundación
(tipografía + paper navy, #60), Fase 2 portada Noticias editorial FT (#61),
Fase 3 reskin de tabs con componentes compartidos (#62), Fase 4 paleta
editorial + EMBI híbrido + poda Noticias + cleanup (#63), y fondo de página
paper → `#fafbfe` (#64). El estado de tabs/routing en §2 ya refleja esto.

**Feature "ocultar noticias" (#65-#70) — COMPLETA y en producción.** Permite a
un admin ocultar notas del feed. La **fuente de verdad de los ocultos es el KV
de Cloudflare**, NO la DB (la tabla local es solo cache para el filtro de build):

| Pieza | Dónde | Qué hace |
|---|---|---|
| Worker Cloudflare | `api.finanzasbo.com` (Worker `finanzasbo-spike`, dir `worker/`; **deploy `wrangler` manual**) | Rutas `GET /v1/hidden` (público `{ids,v}`), `GET /v1/me`, `GET /v1/hidden/admin`, `POST /v1/hide`, `POST /v1/unhide`, + bounces de auth `GET /v1/login` y `GET /v1/logout` (ver "Auth admin" abajo). KV (1 key `index`) = verdad de los ocultos. (Name `finanzasbo-spike` es legacy engañoso — tech-debt P3, ver Notion.) |
| Auth = Cloudflare Access | edge + gate JWT del Worker | Access (team `finanzasbo.cloudflareaccess.com`) protege en el **edge** `/v1/me`, `/v1/hide` y `/v1/login` (302 al login); `/v1/unhide` y `/v1/hidden/admin` dependen **solo del gate JWT del Worker** (401) — cobertura edge **asimétrica**. `ALLOWED_EMAILS` = 7 admins @ddrcapitalpartners.com (secret en el Worker, NO en el repo). **Mapa de gating completo + flujos login/logout: subsección "Auth admin" abajo.** |
| Admin UI | `template.html`, tab Noticias, **gated tras `#admin`** | Sin `#admin` en la URL → markup idéntico a hoy, cero requests. Con `#admin`: barra admin con login / "Editar ocultas" + acciones inline por nota (PR-C2, #70). PR-C1 (#69) = filtro instant client-side de los ocultos. |
| Tabla `noticias_hidden` | `p2p_normalized.db` (migración `0003_noticias_hidden.sql`) | Cache local de ids para el filtro de build; `dashboard.py` la self-crea idempotente y filtra `AND id NOT IN (...)` (`CREATE TABLE` en [dashboard.py:1174](dashboard.py#L1174); filtro `NOT IN` en [dashboard.py:1207](dashboard.py#L1207)). Migraciones se aplican a mano en el VPS (sin runner). |
| `publish_dashboard.py` | VPS (PR-B′, #68) | Antes de publicar hace `GET /v1/hidden` (UA propio — CF da 403 al UA default de urllib) y sincroniza la mirror `noticias_hidden` transaccionalmente, fail-toward-stale estricto (funciones `fetch_hidden` / `sync_hidden_mirror` en `scripts/publish_dashboard.py`; const `HIDDEN_API_URL`). |

### Auth admin — login/logout (saga login/logout, cerrada 2026-06-18)

La autorización de la feature "ocultar noticias" vive en **dos capas**; la verdad
de gating está en el **edge (Cloudflare Access)**, NO en el código del repo:

- **Cloudflare Access (edge).** App del team `finanzasbo` (`finanzasbo.cloudflareaccess.com`),
  policy "Allow 7 admins (OTP)", `AUD 679296d3…fe7bbd71`. Protege en el edge (sobre
  `api.finanzasbo.com`): `/v1/me`, `/v1/hide`, `/v1/login`. La config del App vive
  **solo en el dashboard CF** — no hay archivo en el repo.
- **Worker `finanzasbo-spike`** (sirve `api.finanzasbo.com`; **deploy `wrangler` MANUAL**,
  no GHA). `gate()` (JWT RS256) protege: `/v1/me`, `/v1/hide`, `/v1/unhide`,
  `/v1/hidden/admin`. Los bounces NO llaman `gate()`: `/v1/login` (gateado en el edge),
  `/v1/logout` (público).

**Mapa de gating** (edge = Access; worker = `gate()` JWT):

| Ruta | edge | worker |
|---|---|---|
| `/v1/me` | ✅ | ✅ (doble) |
| `/v1/hide` | ✅ | ✅ (doble) |
| `/v1/login` | ✅ | — (bounce) |
| `/v1/unhide` | — | ✅ |
| `/v1/hidden/admin` | — | ✅ |
| `/v1/logout` | — | — (bounce público) |

**Flujo login.** Click → **navegación** (`location.href`, nunca `fetch`) a
`api.finanzasbo.com/v1/login?return=https://finanzasbo.com/` → el edge gatea → OTP →
sesión → el Worker rebota (destino validado por `safeReturn`) a `finanzasbo.com`. Al
volver, el hint `localStorage NP_SESS_HINT` dispara `npCheckMe` → `fetch` credentialed a
`/v1/me` (cookie cross-subdominio) → `{admin:true}` → barra logueada.

**Flujo logout (bounce de 2 pasos).** Click → navegación a
`api.finanzasbo.com/v1/logout?return=https://finanzasbo.com/` → el Worker hace 302 al
team-logout de Access con `returnTo=https://api.finanzasbo.com/v1/logout?done=1&return=<dest>`
(returnTo a un **app-domain** → CF lo acepta) → Access borra la cookie y vuelve →
`/v1/logout?done=1` → 302 a `safeReturn(return)` (default `finanzasbo.com`) → anónimo.

**Invariantes (no romper):**
- Las rutas gateadas (login) se pegan por **NAVEGACIÓN, nunca `fetch`** — un `fetch` muere
  en CORS en el redirect de Access. El probe `/v1/me` SÍ es `fetch` (correcto: se chequea
  con `redirect:'manual'`, fail-open).
- `safeReturn` allowlist = **origin exacto `https://finanzasbo.com`**; aplicado en el bounce
  de login y en **ambas piernas** del logout (sin open-redirect).
- **Regla `returnTo` de Cloudflare**: el `returnTo` del logout solo acepta el authdomain del
  team, sus subdominios, y hostnames que **son apps de Access** en la org. `finanzasbo.com`
  NO es app → el `returnTo` se rutea por `api.finanzasbo.com` (que SÍ lo es). De ahí el
  logout de 2 pasos.
- La autorización real es **server-side** (edge + JWT del Worker). El "200 = admin" del
  cliente es **cosmético**.

**Saga (commits/PRs):** #72 (`6f2ce28`, barra de sesión) · #74 (mitigación botón oculto,
luego revertida) · #75/C4a (`2d1ab2c`, bounce + `safeReturn`) · gate de Access en `/v1/login`
(dashboard CF, **sin commit** — arregló el loop de redirects) · #76/C4b (`17ea633`, rewire
frontend + botón restaurado) · #78 (`df1b60d` loop guard + `8d0451f` logout de 2 pasos),
**mergeado a main** (`596063c`). **Worker prod: version `b0ec816a`.**

**Tech debt P3 (sobre main, no bloqueante):**
- Código muerto en `/v1/login`: el self-drive (bounce manual a Access) + el loop guard
  quedaron **redundantes** una vez que el edge gatea `/v1/login`; y el comentario
  `"/v1/login no protegido"` ([worker/src/index.js:144-150](worker/src/index.js#L144)) es
  **stale** (precede al gate del edge). Limpieza opcional.
- Asimetría de edge-gating: `/v1/unhide` y `/v1/hidden/admin` solo por JWT del Worker (sin
  edge) — ver mapa arriba.
- Renombrar Worker `finanzasbo-spike` → nombre de prod (legacy engañoso).
- La config del Access App vive en el dashboard CF, fuera del repo.

### Anatomía del chrome (header + footer) — refresh 2026-07-15

(Supersede el recon 2026-06-17: la reconstrucción "chrome editorial v3" y el
re-skin cálido cambiaron la estructura descrita entonces — ya no existen
`.fb-navbar-left/right`, `.fb-logo` ni `#themeToggle`.)

- **Header global = `<header class="fb-chrome">`** ([template.html:854](template.html#L854)),
  **NO sticky** (scrollea con la página). Contiene, en orden:
  - **`.fb-utility`**: fecha (`#fbDate`) a la izquierda; a la derecha
    "Actualizado" (`#fbUpd` + dot `.fb-live`) y `#langToggle` (ES | EN,
    navegación full-page a la ruta equivalente en el otro idioma, ver
    § "Interfaz EN (i18n bake-time)" abajo).
  - **`.fb-ticker`** ("El día en cifras"): tag fijo + `#fbTickerTrack` vacío en
    el markup, poblado por `fbRenderTicker()` — data-driven, no admite
    contenido estático.
  - **`.fb-masthead`**: grid de 3 zonas `1fr auto 1fr` —
    `.fb-masthead-left` (**vacía**, `aria-hidden`, solo balancea el grid;
    `display:none` bajo 980px), `.fb-brand` (nameplate "FinanzasBo" +
    tagline, centrado), `.fb-masthead-actions` (derecha, `flex-direction:column`;
    hoy solo contiene el buscador `.fb-search-link` deshabilitado y `hidden` —
    zona con espacio libre). Bajo 980px el grid colapsa a filas
    `"actions" / "name"`.
- **Fila de tabs = `<nav class="fb-navbar">`** ([template.html:886](template.html#L886)),
  hermana del header (fuera de `.fb-chrome`), sticky `top:0; z-index:52`, con
  `overflow-x:auto` bajo 980px. Contiene `.fb-tabs`: 8 botones `.fb-tab` en
  **markup literal** (no loop), cada módulo opcional envuelto en marcadores
  `bake:optional:<mod>`. Inventario por tab, gate `data-admin-only` (Agro) y
  mecánica del desbake en § 2 "Routing por paths" y "Módulos desbakeados".
- **Sub-header por tab** (`.fb-subheader`, sticky `top:var(--nav-h); z-index:51`):
  `h1` + subtitle. Cada tab tiene el suyo; Macro y Agro lo hacen `position:static`.
- **NO hay toggle de tema ni dark mode.** `#themeToggle`, `body.theme-dark` y
  `THEMES.slate` se retiraron con el re-skin editorial cálido: `THEMES` solo
  tiene `paper` ([template.html:2023](template.html#L2023)). Single-theme.
- **Footer estructural = `<footer class="fb-chrome-foot">`**
  ([template.html:1996](template.html#L1996)), al fin de la página, no sticky.
  Un solo hijo: el slot global `#fbFooterSession`. Lo puebla `fbRenderSession()`
  en cada transición de sesión (init/login/logout/expire): anónimo → botón de
  login icon-only ghost (`.fb-foot-login`, SVG `currentColor`, opacity .45→1 en
  hover); admin → email de sesión + `.fb-logout`. `fbRenderSession()` es también
  quien togglea todos los `[data-admin-only]` (`el.hidden = !npAdmin.isAdmin`).
- **Botón de login — vive en el footer, NO en el masthead ni en la barra admin
  de Noticias.** El click (`data-np-login`, listener a nivel `document`) llama
  `npLogin()` → navegación full-page al **bounce `/v1/login` del Worker** (que
  el edge gatea → login de Cloudflare Access; flujo completo en §0 "Auth
  admin"). La barra admin de Noticias (`npAdminBar()`) quedó solo con los
  controles de edición de ocultas, sin gate `#admin` en la URL.
- CSS del chrome: `.fb-chrome` (~L271), `.fb-utility` (~L272), `.fb-masthead`
  (~L310), `.fb-chrome-foot` / `.fb-foot-login` (~L319-324), `.fb-navbar`
  (~L345), `.fb-subheader` (~L356); offset sticky vía `--nav-h`.

---

## 1. Reglas para tickets

### Antes de empezar
Leer este `HANDOFF.md` + `CLAUDE.md`. Eso es el contrato completo. Todo lo
demás es referencia (runbooks, código fuente, historia).

### Naming de branches
Formato real en este repo (alineado con CLAUDE.md):

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
La regla operativa, alineada con `CLAUDE.md` (acá con el detalle por archivo):

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
- **BCB scrape (referencial)**: `bcb_referencial.py` (lógica) + `scripts/bcb_scrape_and_commit.sh` (wrapper VPS).
- **ASFI hechos relevantes RMV**: `asfi_ingest/` (parser PDF + fetch proxy + resumen IA) +
  `ingest_asfi.py` (orquestador) + `scripts/asfi_scrape_and_commit.sh` (wrapper VPS) +
  `static/asfi.html` (página). Detalle: § 9.
- **BCB TCO (Tipo de Cambio Oficial, RD 88/2026)**: `ingest_bcb_tco.py` (lógica) +
  `scripts/bcb_tco_scrape_and_commit.sh` (wrapper VPS). **Dos fuentes** (`--via`):
  - **Portada** (`--via portada`, DEFAULT): `https://www.bcb.gob.bo/` trae un card
    "Tipo de cambio oficial" (server-rendered, clase `is-tc-oficial`) con **HOY y
    MAÑANA**. Es la fuente **primaria** porque va por **delante** del detalle
    histórico, que tiene **rezago** (la portada ya muestra el TCO de mañana cuando
    el detalle aún no). Parser `parse_homepage_tco` (lee `<time datetime>` para HOY,
    el `<span>` con fecha en español para MAÑANA, y las dos `bcb-tco-duo-num`;
    valida rango con `parse_rate`). `source='bcb_tco_portada'`.
  - **Histórico** (`--via historico`, lo fuerza `--backfill`): el reporte
    `tco_reporte_detalle_historico.php` es un **formulario** (rango + "Descargar
    CSV"); el scraper introspecciona el form (`--desde/--hasta`, default ventana
    14 días atrás + 5 adelante; `--backfill` desde 2026-06-26). Del CSV **lee el
    TCO publicado** (fila `TCO`, col `TOTAL BANCOS`) y lo **verifica** recalculando
    el promedio ponderado del detalle (Anexo II). `source='bcb_tco'`. Se usa para
    backfill/verificación, no en el cron diario.
  - Salida a `bcb_tco.json` (merge dedup por fecha; `_fill_weekends_tco` en
    `dashboard.py` sintetiza sáb/dom). `--from-file` parsea un archivo local
    offline (respeta `--via`); `--debug` vuelca el crudo.
- **EMBI scrape (BCRD)**: `ingest_embi.py` (lógica + cron one-liner). Snapshot Excel +
  ETag cache en `/opt/binance_p2p/embi_audit/` (fuera del repo).
- **INE Bolivia macro (PIB + IPC + IPP)**: `ingest_ine_pib.py` /
  `ingest_ine_ipc.py` / `ingest_ine_ipp.py` (entry points por familia,
  mismas convenciones que EMBI). Parser compartido en `ine_parser.py`.
  Catálogo de cuadros y mapeo host/token en `config.INE_CUADROS`. Snapshot
  XLSX y estado por cuadro en `/opt/binance_p2p/ine_audit/{pib,ipc,ipp}/`
  (fuera del repo).
- **Noticias (dos carriles)**: `ingest_noticias.py` (CLI, mismas
  convenciones que EMBI/INE) sobre el módulo `noticias_ingest/`:
  carril Bolivia = scraper + scoring TF-IDF portado de
  `research-star/boletines` (fuentes/keywords en
  `noticias_ingest/scraper.py`, modelo committeado en
  `noticias_ingest/modelo_relevancia.pkl` ~722 KB); carril Latam = RSS
  de Bloomberg Línea sección Latinoamérica en `noticias_ingest/latam.py`
  (sin scoring). Mapeos al schema del frontend en
  `noticias_ingest/transform.py`. Runtime (caché de URLs TTL 7d + CSV de
  diagnóstico) en `noticias_ingest/data/` (gitignored).
- **Constantes compartidas**: `config.py`.

### Preview local (frontend)

Para ver un cambio de `template.html` / `dashboard.py` funcionando antes de
abrir PR (la skill `actualizar-dashboard` de `.claude/skills/` automatiza el
pipeline completo con data fresca del VPS; esto es la versión manual mínima):

1. **Build**: `python dashboard.py` regenera `index.html` local desde
   `p2p_normalized.db`. Para no ensuciar el working tree, generar a un
   directorio temporal (dashboard.py crea los directorios padres solo):
   `python dashboard.py --output "$env:TEMP\fb-preview\index.html"`.
   Como el output se llama `index.html`, también escribe un alias
   `p2p_dashboard.html` al lado (inocuo en un temp dir), y además hornea la
   versión EN en `<dir>\en\index.html` (doble bake i18n; `--output-en` para
   otro path).
   **No commitear `index.html`** — el publish productivo lo hace el VPS.
2. **Servir**: `python -m http.server 8000 --directory <dir del build>`.
   NO abrir con `file://` — rompe el routing por History API.
3. **Deep-links** (ej. `/noticias`, `/riesgo`): `http.server` no replica el
   truco 404.html del edge (Cloudflare Pages en prod; era GitHub Pages antes del
   cutover — mecanismo idéntico, paridad verificada). Probar el mismo code-path con
   `http://localhost:8000/?path=%2Fnoticias` (es lo que el 404 redirige).
4. **Validación automatizada** (opcional): Playwright vive en el cache de npx
   de esta máquina, no en `node_modules`. Desde un script Node:
   `NODE_PATH="<npm cache>/_npx/<hash>/node_modules" node script.js` — localizar
   el hash con `find "$(npm config get cache)/_npx" -name playwright -type d`.
   Chromium bundled ya instalado (`chromium.launch()`).

### Artefactos no commiteados (solo esta laptop)

Cosas que existen en la máquina de trabajo y NO están en el repo — un
colaborador fresco no las ve en un clone:

- **`CLAUDE.local.md`** — flujo personal de Diego con Claude Code (formato de
  briefs, protocolo de reporte, anti-patrones del flujo). Complementa
  `CLAUDE.md` sin contradecirlo.
- **`.claude/settings.local.json`** — permisos locales de Claude Code
  (allowlist mínima: lecturas git/gh, pipeline local, preview, test tooling).
- **`design-system/`** — kit de diseño exportado de Claude Design (galería de
  componentes, snapshot del template, handoffs de mockups). Fue el input
  normativo del PR #48 (tab Noticias). Pedírselo a Diego si un ticket lo
  referencia.
- **`p2p_dashboard.html`** — alias local del build de inspección, ignorado
  por git. Ojo: `index.html` SÍ está trackeado (es el archivo que se publica al
  edge productivo —Cloudflare Pages— vía la rama `gh-pages`) — el build local solo
  lo ensucia en el working tree; no commitearlo (ver § Preview local).

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

### Schema SQLite — partición migrations vs runtime

`scripts/migrations/` **NO es el schema canónico completo.** Es solo una parte:
las migraciones INE/noticias/gasto. El resto de las tablas se crean **en runtime**
por el propio script que las usa (`CREATE TABLE IF NOT EXISTS` al arrancar). Al
tocar schema hay que mirar **ambos lugares**.

**Declaradas en `scripts/migrations/` (9 archivos, `0001`–`0009`):**

| Migración | Tablas / cambio |
|---|---|
| `0001_ine_tables.sql` | `ine_pib`, `ine_ipc`, `ine_ipp`, `ine_ingest_state` |
| `0002_noticias.sql` | `noticias` |
| `0003_noticias_hidden.sql` | `noticias_hidden` |
| `0004`–`0008` | **`ALTER TABLE` sobre `noticias`** (image_url `0004`, clasificacion_v1 `0005`, tambien_en `0006`, summary_origen `0007`, reresumen: extract_len + resumen_reintentos `0008`) — no crean tablas |
| `0009_api_spend.sql` | `api_spend` (contador de gasto IA de noticias) |

**Creadas en RUNTIME, fuera de `migrations/` (7 tablas):**

| Tabla | Origen | DB |
|---|---|---|
| `ads` | `normalize.py` (`init_schema`) | `p2p_normalized.db` |
| `normalize_state` | `normalize.py` | `p2p_normalized.db` |
| `embi_spreads` | `ingest_embi.py` | `p2p_normalized.db` |
| `bcb_dpf_rates` | `ingest_bcb_dpf.py` | `p2p_normalized.db` |
| `ine_ipc_comunicado` | `ingest_ine_comunicado.py` | `p2p_normalized.db` — **NUEVA vía #221, SIN `.sql`** (rompe la convención; no se crea migración 0010 por decisión de este ciclo) |
| `urls_vistas` | `noticias_ingest/scraper.py` (`CacheURLs`) | `noticias_ingest/data/cache_urls.db` (gitignored, aparte de la DB principal) |
| `asfi_api_spend` | `asfi_ingest/resumen.py` | `p2p_normalized.db` (contador de gasto IA de ASFI) |

Nota: `noticias_hidden` (0003) y `api_spend` (0009) también se auto-crean en
runtime (`dashboard.py`/`publish_dashboard.py` y `resumen_ia.py` respectivamente)
— belt-and-suspenders, redundante con su migración. Lo mismo las 4 tablas INE
(auto-create en cada `ingest_ine_*.py`).

**Módulos SIN tabla SQLite** (persisten en JSON committeado o no persisten):
ASFI datos (`static/asfi_YYYY-MM.json` + `asfi_index.json`) · bloqueos
(`bloqueos.json`) · tasas/TRE (`bcb_tre.json`) · mercado247 (Hyperliquid en vivo,
sin persistencia server-side) · BBV (dataset JS estático embebido en `template.html`) ·
Agro (datasets JSON en `static/`: producción SIIP `agro_produccion.json`,
exportaciones INE-Comex snapshot `agro_exportaciones.json`, precios
FPMA/Pink Sheet/valor unitario `agro_precios.json`, 2 geojson
`agro_geo_municipal.json`/`agro_geo_departamental.json`; sin tabla — ver
§ Tab Agro).

### Gasto API Anthropic — 2 carriles, 2 contadores

Hay **exactamente 2 carriles productivos** que llaman a la API de Anthropic
(Haiku), ambos con el candado `autorizado=True` pasado por su pipeline/cron:

| Carril | Entrypoint | Módulo POST | Contador (cap $1/mes) |
|---|---|---|---|
| Noticias | `ingest_noticias.py` (cron noticias) → `resumen_ia.aplicar(...)` | `noticias_ingest/resumen_ia.py` | tabla `api_spend` |
| ASFI | `ingest_asfi.py --resumir` (cron mensual) → `resumen.aplicar(...)` | `asfi_ingest/resumen.py` | tabla `asfi_api_spend` |

No hay un tercer carril. El resto de menciones a `resumir(`/`aplicar(` en el repo
son docstrings, el pipeline interno de `resumen_ia.py`, o el **stub no-op del
Noticias Inspector** (`inspector_core.py` reemplaza `resumen_ia.aplicar` por
`lambda: 0`, sin API). Techo total de IA del sitio = noticias $1 + ASFI $1 = $2/mes.

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
- Vive como subtab "Riesgo país" dentro de la tab Macro (reorganización
  de navbar + subnav Macro, PR #47).
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

**Card "Servicio de deuda en bonos soberanos"** (segundo card de la subtab,
debajo del chart EMBI):
- Barras apiladas Plotly con el servicio anual (capital + cupones, USD MM) de
  los bonos soberanos 2026-2031, una traza por emisión (2017 / 2022 / 2026),
  total anual como anotación sobre cada barra. 3 KPIs arriba (servicio total,
  pico intermedio 2028, bullet 2031).
- **Dataset estático embebido** en JS (`const DEBT_SCHEDULE`, junto a su
  render en `template.html`) — desviación deliberada del patrón `DATA.*`:
  términos contractuales inmutables, no pasan por `dashboard.py`. Si Bolivia
  emite/recompra/canjea deuda, se edita el literal y se redeploya.
- Render lazy: `window.renderDeudaSoberana()`, colgado del mismo hook de
  `MACRO_SUBTABS` que `renderRiesgoPais()`. Theme-aware vía MutationObserver
  propio (mismo patrón que EMBI).
- Colores: tokens `--chart-debt-em2017/em2022/em2026` en `THEMES.paper/.slate`
  (ramp azul cronológico + ámbar para la emisión 2026, protagonista del bullet).

**Frontend subtab "Inflación"** (en `template.html`, hermano de Riesgo País
dentro de Macro):
- **⚠️ Corrección 2026-06-23 (supersede lo de abajo sobre IPP):** la subtab
  Inflación renderiza **solo IPC** (`DATA.inflacion.ipc`); el código lo dice
  explícito (`template.html`: `// Solo IPC (el IPP se ignora)`). El **IPP
  (`DATA.inflacion.ipp`) se computa en el payload de `dashboard.py` pero NO se
  renderiza en ninguna superficie del frontend** desde que el ticker "El día en
  cifras" (`.fb-ticker`) dejó de mostrar "IPP interanual" (2026-06-23). Las
  menciones de abajo a "IPP interanual" como KPI hero, al dual **IPC vs IPP**, y
  al dual-card **IPP por grandes grupos** describen un diseño **no implementado**
  (stale): el payload `ipp` y los tokens `--chart-ipp-*` quedan latentes.
- Payload `DATA.inflacion`: `dashboard.py` pivotea `ine_ipc`/`ine_ipp` a
  shape columnar estilo EMBI — `{ipc:{periodos, general:{var_12m,
  var_mensual, var_acumulada}, divisiones:{slug:{label, var_12m, var_mensual,
  peso?, contrib?}}}, ipp:{..., grupos:{...}}, ultimo:{ipc, ipp}}`. Siempre
  `valor IS NOT NULL` (el parser INE deja placeholders NULL en meses futuros
  del año en curso). `ipc`/`ipp` llegan `null` si su tabla falta o está
  vacía → card de fallback sin crash. Peso payload ~55 KB (vs ~880 KB EMBI).
- **Contribuciones derivadas** (`contrib`/`peso`): el INE no publica
  ponderaciones en los cuadros ingeridos, pero el índice total es Laspeyres
  EXACTO de las divisiones; `_laspeyres_contrib()` (dashboard.py) recupera
  los pesos base 2016 por mínimos cuadrados (stdlib, sin numpy) y deriva
  `c_i(t) = w_i·ΔI_i/I_T(t−12)·100`. Doble guarda fail-closed: reconstrucción
  del índice casi exacta + suma de contribuciones replica la `var_12m`
  publicada (verificado: error 0.000 IPC / 0.001 IPP); si no valida, el
  payload va sin `contrib` y el hero degrada a líneas.
- 4 KPIs hero: IPC interanual / mensual / acumulada + IPP interanual, con Δ
  en pts vs mes anterior (color: aceleración orange, desaceleración green).
- Chart hero dual: **Contribuciones** (default; barras apiladas por división
  COICOP + línea IPC total, `barmode:relative`, anotaciones de pico y último
  dato) ↔ **Líneas** (IPC vs IPP var 12m). Chips `.ds-chip`.
- Desglose dual-card (IPC por división COICOP + IPP por grandes grupos) con
  vista **Ranking** (bar horizontal del último mes, total destacado) ↔
  **Series** (multi-línea con leyenda `.fb-stog`, total en línea punteada;
  defaults: total + 2 drivers) y métrica 12m ↔ mensual.
- Lazy render: `window.renderInflacion()` colgado del hook `render` de
  `MACRO_SUBTABS`; theme-aware vía MutationObserver con guard
  `offsetParent` (mismo patrón que Riesgo País).
- Tokens: `--chart-ipc-general` (ámbar hero), `--chart-ipp-general` (azul),
  `--chart-infl-total` (traza total punteada), + `--chart-ipc-<slug>` (12
  divisiones) y `--chart-ipp-<slug>` (6 grupos) en `THEMES.paper/.slate`.

### Routing por paths (SPA + 404 trick)

URLs limpias por tab via HTML5 History API. **Noticias es la landing en `/`**;
Dólar tiene slug propio `/dolar`.

**Tabs — 4 públicas en prod, 5 DESBAKEADAS** (existen en
`template.html` pero NO se inyectan al `index.html` publicado; ver § Módulos desbakeados):

| # | `data-tab` | Label | Slug | Estado en prod |
|---|---|---|---|---|
| 1 | `noticias` | Inicio | `/` (+ alias `/noticias`) | **visible, landing/active** |
| 2 | `dollar` | Dólar | `/dolar` | visible |
| 3 | `macro` | Macro | `/macro` (+ subtabs) | visible |
| 4 | `asfi` | ASFI | `/asfi` | visible |
| 5 | `agro` | Agro | ~~`/agro`~~ (+ subtabs) | **DESBAKEADO de nuevo** (2026-07-16, pedido de Diego: ocultar la tab entera; historial: nació desbakeado 07-09 → bakeado 07-10 → desbakeado 07-16) |
| 6 | `mercado247` | Mercado 24/7 | ~~`/mercado247`~~ | **DESBAKEADO** (antes admin-only oculto) |
| 7 | `dpf` | DPF | ~~`/dpf`~~ | **DESBAKEADO** (antes hidden, ES-only) |
| 8 | `bbv` | BBV | ~~`/bbv`~~ | **DESBAKEADO** (antes hidden, ES-only) |
| 9 | `guide` | Guía | ~~`/guia`~~ | **DESBAKEADO** (antes hidden, ES-only) |

**Subnav de Macro** (4 subtabs, botones `.fb-macro-tab`, array `MACRO_SUBTABS`):
`riesgo` (default) · `inflacion` (IPC/IPP INE) · `bloqueos` (mapa vial + KPIs) ·
`tasas` (TRE mensual del BCB). El primero de la lista es el default al entrar a
`/macro` bare. (Macro y sus 4 subtabs NO están afectados por el desbake.)

**Gate `data-admin-only` — COSMÉTICO (aplica a `mercado247`/`agro` cuando se
bakeen).** El gate solo oculta el botón de nav (`fbRenderSession` togglea
`el.hidden = !npAdmin.isAdmin` en cada transición de sesión); `activateTab` NO
chequea `isAdmin`, así que la URL directa del tab renderiza igual para anónimos.
Con `agro` desbakeado de nuevo (2026-07-16) el leak es moot para ambos módulos:
la ruta no existe en prod (404-trick → landing) y sus assets no se sirven.

### Módulos desbakeados (opción B — presentes en repo, NO servidos en prod)

Cinco módulos en el set (`mercado247`, `dpf`, `bbv`, `guide`, `agro`), **desbakeados**
(opción B, 2026-07-09): su código fuente PERMANECE en el repo pero NO se inyecta al
`index.html` publicado ni se sirve su asset. No es un retiro (C) — nada se borró.
`agro` nació desbakeado el 2026-07-09, salió del set el 2026-07-10 (OK de Diego,
bakeado) y **volvió al set el 2026-07-16** (pedido de Diego: ocultar la tab entera).
Sus assets `agro_*.json` dejan de publicarse (entrada de `MODULO_ASSETS` reactivada).

**Punto de control ÚNICO:** el set `config.MODULOS_NO_BAKEADOS` ([config.py](config.py)).
Un módulo listado ahí:
- se strippea del bake — cada punto de contacto (botón nav, entrada `ROUTE_MAP`/
  `TAB_PANELS`, rama de `activateTab`, markup del panel, CSS, JS, datasets) está
  envuelto en marcadores `bake:optional:<mod>` que `i18n_bake.strip_optional_modules`
  elimina (misma maquinaria que los `i18n:es-only`, pero por módulo);
- omite su payload — `dashboard.py` no emite `dpf_data` si `dpf` está desbakeado;
- no publica su asset — `publish_dashboard.py` excluye los archivos de
  `config.MODULO_ASSETS` de los módulos EN el set (hoy solo `mercado247-tab.js`).
  La entrada `agro` en `MODULO_ASSETS` (5 datasets `agro_*.json` + 7 shards
  preventivos `agro_prod_g1..g7.json`) quedó **dormida** al salir agro del set:
  sus assets SÍ se publican; la entrada se conserva por si se re-desbakea.

**Revertir (re-bakear) = quitar el módulo de `MODULOS_NO_BAKEADOS` y rebakear.** Es
la ÚNICA edición necesaria en config/código; los marcadores quedan en el template y
el contenido vuelve intacto. (Verificado en local con `bbv`, y con `agro` el
2026-07-10.) Para módulos con assets en `MODULO_ASSETS` (hoy `mercado247`;
`agro` ya salió), re-bakear implica además que el próximo publish copie sus assets
al edge — automático al salir del set (el publish los excluye solo mientras el
módulo esté desbakeado).

**Acoplamiento a tener en cuenta:** `guide` NO es independiente de `bbv` — sus
funciones JS (`renderGuide`, `renderGuideIssuers`) viven DENTRO del IIFE de `bbv`
y usan sus datasets/`renderGlossarySection`. Re-bakear `guide` requiere `bbv`
también bakeado. `dpf`, `bbv` y `mercado247` sí son independientes.

Ahorro de superficie: ~85 KB en `index.html` (markup/JS/CSS de los 4 + payload
`dpf_data` ~26 KB) + 58 KB del asset `mercado247-tab.js` que deja de servirse.
`.fb-data-table` y `.fb-pill`/`.fb-pills` se PRESERVAN (los usan ASFI y Dólar/Macro).
El pipeline de ingesta de DPF (`ingest_bcb_dpf.py`) sigue igual (frío: nadie lo
corre) — el desbake solo dejó de emitir el payload; la tabla `bcb_dpf_rates` intacta.

**Tabla de slugs** (`ROUTE_MAP` en el JS de `template.html`):

| Slug | Resuelve a | Título |
|---|---|---|
| `/` | tab `noticias` (landing) | FinanzasBo — Noticias |
| `/dolar` | tab `dollar` | FinanzasBo — Mercado P2P USDT/BOB |
| `/macro` | tab `macro`, subtab default (`riesgo`) | FinanzasBo — Riesgo País EMBI |
| `/riesgo` | tab `macro`, subtab `riesgo` | FinanzasBo — Riesgo País EMBI |
| `/inflacion` | tab `macro`, subtab `inflacion` (IPC/IPP INE) | FinanzasBo — Inflación |
| `/bloqueos` | tab `macro`, subtab `bloqueos` | FinanzasBo — Bloqueos en carreteras |
| `/tasas` | tab `macro`, subtab `tasas` | FinanzasBo — Tasa de Referencia BCB |
| `/asfi` | tab `asfi` | FinanzasBo — Hechos Relevantes ASFI |
| `/agro` | tab `agro`, subtab default (`soya`) — **admin-only** (gate cosmético) | FinanzasBo — Agro · Soya |
| `/agro/soya` | tab `agro`, subtab `soya` — **admin-only** | FinanzasBo — Agro · Soya |
| `/agro/girasol` | tab `agro`, subtab `girasol` — **admin-only** | FinanzasBo — Agro · Girasol |
| `/agro/azucar` | tab `agro`, subtab `azucar` — **admin-only** | FinanzasBo — Agro · Azúcar |
| `/agro/otros` | tab `agro`, subtab `otros` — **admin-only** | FinanzasBo — Agro · Otros cultivos |
| `/mercado247` | tab `mercado247` (gate cosmético) | FinanzasBo — Mercado 24/7 |
| `/dpf` | tab `dpf` (ES-only) | FinanzasBo — Rendimientos DPF |
| `/bbv` | tab `bbv` (ES-only) | FinanzasBo — Bolsa Boliviana de Valores |
| `/guia` | tab `guide` (ES-only) | FinanzasBo — Guía del dashboard |
| `/noticias` | alias → tab `noticias`; la barra canonicaliza a `/` (entry `alias:true`, excluido de `TAB_TO_SLUG`) | FinanzasBo — Noticias |

Los slugs Agro v1 (`/agro/produccion`, `/agro/exportaciones`) quedan en
`ROUTE_MAP` como **redirects** a la cadena default (subtab `soya`): renderizan
soya al entrar; la barra de URL se canonicaliza al slug nuevo recién al primer
click de subnav (`pushState`) — el init NO los reescribe con `replaceState`
(eso solo pasa con entradas `alias:true`, hoy solo `/noticias`).

El mapeo `ROUTE_MAP` vive en el JS del template.html (sección
`// ═══ TAB SWITCHING + ROUTING ═══`); cada entrada resuelve a
`{tab, subtab?}`. Registros hermanos: `TAB_PANELS` (tab id → id del
contenedor DOM), `TAB_TITLES` (título del documento) y `MACRO_SUBTABS`
(lista genérica de subtabs de Macro con su slug plano, título y render
lazy). El `<title>` se actualiza junto con la activación.

**Entrada directa a sub-paths** (ej. `finanzasbo.com/bbv` desde bookmark o
link externo): el edge (Cloudflare Pages en prod; GitHub Pages antes del cutover —
mismo comportamiento, paridad verificada) no encuentra el archivo y sirve `404.html`
(comiteado en `static/404.html`, copiado a la raíz de `gh-pages` por
`publish_dashboard.py`). Ese 404 redirige a `/?path=%2Fbbv`. El init del SPA
lee el `?path`, hace `history.replaceState` a `/bbv`, y activa la tab. UX:
una sola redirección casi imperceptible.

**NO existe archivo `_redirects`.** El deep-linking se resuelve exclusivamente
por el truco `static/404.html` descrito arriba — no hay `_redirects` (ni en raíz,
ni en `static/`, ni emitido por `publish_dashboard.py`/`dashboard.py`). Si algún
día se migra a redirects nativos de Cloudflare Pages habría que crearlo; hoy no
está y el 404-trick basta.

**Navegación interna**: click en tab dispara `history.pushState(slug)`. Back
y forward del browser disparan `popstate` que re-activa la tab sin recargar.

~~`/noticias` NO está en `ROUTE_MAP`~~ — regla cumplida en
`feat/noticias-tab`: la tab Noticias está activa y `/noticias` mapeada
(ver § Frontend tab "Noticias" abajo).

Paths no reconocidos caen en fallback silencioso: `history.replaceState('/')`
+ activa Noticias (landing).

### Tab Agro (BAKEADA admin-only desde 2026-07-10; rediseño por cadenas 2026-07-10)

Tab con subnav propio (patrón Macro; `AGRO_SUBTABS` se deriva 1:1 de la config
`AGRO_CADENAS` + `activateAgroSubtab`), organizado por **CADENAS DE VALOR**:
**Soya · Girasol · Azúcar · Otros**. Config extensible: cadena nueva = 1 entrada
en `AGRO_CADENAS` + claves i18n (`agro.subtab_<id>`, `doc_title/subtitle_<id>`)
+ entradas en `ROUTE_MAP` + panel `subtab-agro-<id>`. Mapeo actual: Soya =
grano+torta+aceite / cultivo SIIP 61; Girasol = grano+aceite / 58; Azúcar =
azúcar+etanol / caña 57; Otros no fija cadena (`selector:true` → selects de
cultivo SIIP y producto Comex en su panel).

Cada cadena apila **dos dashboards duales**: Producción (SIIP municipal
2013–2024, 73 cultivos, choropleth municipal/departamental, mapa de 520 px)
arriba y Exportación (INE IneComex 2017–2026, 2026 YTD marzo; 35 productos
NANDINA 10 dígitos, FOB USD + toneladas) abajo. Layout: producción = DUAL
(mapa izq + KPIs/ranking/sparklines der, `.agro-dash` grid `1fr/1fr`; pedido
2026-07-10: KPIs nunca desbordan); exportación = APILADO en forma cuadrada
(`.agro-dash--expo`, pedido 2026-07-10 tarde: controles → fila de KPIs →
mapa mundial full-width → slider → abajo ranking | sparkline FOB +
estacionalidad en `.agro-dash-bottom` 1fr/1fr; los KPIs no cambian al
alternar vistas — expoSide es el único que los escribe). **Escala de color
FIJA por serie completa** (`_zr` — `zrProdMun`/`zrProdDep`/`zrExpoDest`:
zmin/zmax computados sobre TODOS los años por clave cultivo|productos ×
métrica × nivel), así el slider compara colores entre años. El dashboard de
exportación tiene dos vistas MUNDIALES (el mapa Bolivia-por-depto de origen se
retiró 2026-07-10; `porDepto`/`origTotal` siguen en el JSON — `origTotal`
alimenta `expoNacArr('__todos__')`): **Países** (default) = choropleth de
destinos por ISO-3 (`AGRO_DEST_GEO[].iso`), países sin venta en el año quedan
en gris neutro (paridad con producción) y el hover lleva FOB + t +
participación; y **Flujos** (valor interno `destinos`) = arcos Bolivia→destino
con partículas animadas, con guards de performance — pausa vía
`IntersectionObserver` fuera de viewport, `prefers-reduced-motion` → flechas
estáticas, presupuesto runtime mobile (promedio del restyle > `DEST_BUDGET`
12 ms → degrada a estático, decisión pegajosa) — e instrumentación del modo en
el atributo `data-agro-dest-anim`. La card de precios congela el select como
etiqueta estática (`.agro-select-solo`) en cadenas mono-producto
(girasol/azúcar hoy).

**Valor agregado — 4 VAs con matriz por cadena:** VA-1 balance
producción↔exportación (% exportado = ton Comex de la cadena / ton SIIP del
cultivo; solo cadenas con `cultivo_siip` fijo, en Otros se omite); VA-2 brecha
del valor unitario FOB implícito vs benchmark Pink Sheet (**SOLO soya-grano y
azúcar** — extensión autorizada de la REGLA DE PRECIOS, ver abajo;
girasol/otros omitidos limpio); VA-3 estacionalidad (heatmap mes×año del FOB
mensual agregado); VA-4 concentración de destinos (mercados activos + top-3
FOB, mismos helpers `destAgg`/`destItems` que las vistas Países y Flujos). La card de **precios** (FAO GIEWS
FPMA doméstico Bs + WB Pink Sheet USD/t + valor unitario FOB/t; 25 series) va
al fondo de cada cadena, con whitelist propia (productos de la cadena +
`precios_default`; en Otros, catálogo completo).

**Rutas:** `/agro` → soya; `/agro/{soya,girasol,azucar,otros}`; los slugs v1
`/agro/produccion|exportaciones` quedan como redirects → soya (detalle en
§ Tabla de slugs). Botón nav entre Macro y ASFI, con `data-admin-only hidden`
(patrón Mercado 24/7): `fbRenderSession` lo revela solo con `npAdmin.isAdmin`
confirmado vía `/v1/me`. Nació desbakeada (cero bytes) el 2026-07-09; salió del
set el 2026-07-10 → hoy se bakea y sus assets se publican, pero el botón es
admin-only. El código sigue envuelto en `bake:optional:agro` (marcadores inertes
mientras agro NO esté en el set; re-desbakear = re-agregarlo). Gate cosmético: el
público no ve el botón pero `/agro` por URL directa renderiza igual (ver § Gate
`data-admin-only`).

**Piezas:**
- `ingest_agro.py` — harvester SIIP (endpoint `JsonAjaxAgricolaMdryt.php`), cache
  en disco resumible/idempotente (5xx aborta ruidoso, la próxima corrida resume),
  `--rebuild-mapa` reconstruye el CSV de mapeo, emisión con sharding por grupo si
  el índice supera 1.3 MB (`agro_prod_g<n>.json` + `meta.shards`).
- `ingest_agro_precios.py` — 3 fuentes (FPMA/Pink Sheet/valor unitario),
  fail-closed por fuente: si UNA falla entera, aborta SIN escribir output parcial.
- `scripts/build_agro_geojson.py` — geoBoundaries gbOpen BOL ADM3 (**Public
  Domain**, upstream GeoBolivia; 339 municipios) simplificado con shapely →
  `static/agro_geo_municipal.json` (~496 KB). El depto se asigna por spatial
  join contra el ADM1; crosswalk a nuestros gid por nombre+depto. (Reemplazó
  al derivado GADM el 2026-07-10 por licencia; el archivo GADM quedó en la
  historia git de la branch del PR #230 — residuo aceptado a decisión.)
- `scripts/agro/` — builder Comex portado (`granos_ingest.py`) + `granos_config.json`
  (35 semillas NANDINA) + README con provenance/regeneración/atribución.
- `scripts/data/agro_municipios.csv` — mapa códigos INE del SIIP → gid (344
  registros; los gid son claves OPACAS del join, formato GADM-oide legado del
  fixture — la geometría ya NO es GADM). 5 registros `Lago Titicaca` son
  pseudo-unidades de agua sin código INE: quedan fuera del geojson.
- Los 5 `static/agro_*.json`: `agro_produccion.json` (~763 KB, harvest COMPLETO
  73 cultivos × 2013-2024), `agro_exportaciones.json` (~288 KB), `agro_precios.json`
  (~69 KB), `agro_geo_municipal.json` (~496 KB, 339 features),
  `agro_geo_departamental.json` (~310 KB).
- Frontend en `template.html`: markup, CSS, JS y rutas, todo envuelto en
  `bake:optional:agro`.

**REGLA DE PRECIOS (de Diego, crítica):** valor unitario FOB/ton SOLO para
productos mono-partida homogéneos — whitelist EXACTA `[sesamo, chia, quinua,
mani, castana, cafe]`. **PROHIBIDO** derivar precio de grupos mixtos (ej. soya y
derivados = aceite+torta+grano: sesgado, no representativo). Toda serie de precio
lleva etiqueta de fuente visible en el chart. **Excepción acotada (autorizada
explícitamente en el brief del rediseño, 2026-07-10):** la comparación VA-2
—brecha del valor unitario FOB implícito vs benchmark Pink Sheet— para
soya-grano (key mono-partida `soya`, NO la cadena agregada) y azúcar
(`VA2_BENCH` en el template). El resto de la whitelist no cambia; girasol/otros
no computan VA-2.

**Datos lazy:** nada pasa por `DATA`/`dashboard.py` — el frontend fetchea
`/agro_*.json` (paths absolutos) al activar la subtab, con cache module-level y
estados de carga/error visibles (patrón Bloqueos/ASFI).

**Preview local:** `python dashboard.py --output <tmp>` — agro ya se bakea por
default (salió de `MODULOS_NO_BAKEADOS`). OJO: `--incluir-modulo agro` **ahora
falla** (solo acepta módulos EN el set); el flag sigue vigente para dpf/bbv/
guide/mercado247.

**Fuentes / atribución:**
- Producción: SIIP–MDPyEP (endpoint JSON interno sin API formal — puede cambiar
  sin aviso).
- Exportaciones: INE IneComex vía snapshot del build COMEX-Bolivia; los crudos
  (`expYYYY.txt`, ~26 MB) NO se versionan en este repo (viven en el working tree
  de COMEX-Bolivia en la laptop de Diego; ver `scripts/agro/README.md`).
- Precios: FAO GIEWS FPMA (`price_value` BOB nominal, NUNCA el dólar al TC
  oficial) + WB Pink Sheet (URL con GUID anual rotativo: discovery en la página
  de commodity markets + fallback hardcodeado).
- Geometrías: geoBoundaries gbOpen BOL ADM3/ADM1, licencia textual **"Public
  Domain; free use and access to information"** (fuente primaria: GeoBolivia,
  geo.gob.bo, límites municipales oficiales). Apta para redistribución.
  Atribución en el pie del mapa municipal y en `/creditos-imagenes.html`
  (sección "Datos geográficos"). El flag de licencia GADM quedó resuelto con
  este swap (2026-07-10).

**Pendientes:**
- Bakear tras validación visual de Diego (el harvest SIIP completo ya corrió:
  73 cultivos × 2013-2024, 49.537 filas municipales, 99,8% georreferenciadas).
- Cron VPS de refresco (sesión 2 — requiere autorización).
- Códigos SIIP `225`/`226` (La Paz, `desc_mun` NULL upstream) sin
  georreferenciar: ~101 filas en `sin_georef`; asignación manual pendiente vía
  seeds del CSV.
- Candidatos NANDINA adicionales propuestos — decisión de Diego (ver PR).

### Interfaz EN (i18n bake-time) — `feat/i18n-en`

Doble bake desde el mismo `template.html`: `dashboard.py` emite `index.html`
(ES) + `en/index.html` (EN) en una sola corrida. Mecanismo: tokens
`{{t:clave}}` en el template, resueltos por `i18n_bake.py` contra
`i18n/es.json` (texto ES verbatim) e `i18n/en.json` (497→465 claves tras
descope de DPF, ver abajo). Clave faltante en un diccionario → el bake aborta
ruidoso listando las claves (nunca se shippea un `{{t:...}}` crudo); el
carril EN es fail-soft a nivel bake (si falla, `dashboard.py` omite el output
EN con warn y el ES sigue intacto) y `publish_dashboard.py` degrada a
warn + EN stale si el output EN falta o es demasiado chico (mismo espíritu
que `_inject_riesgo`).

- **Tabs Guía, BBV y DPF son ES-only** — no existen en el build EN (sin botón
  de nav, sin panel, sin ruta). DPF se descopeó de la interfaz EN a media
  implementación (decisión de Diego, enmienda la spec original del ticket
  i18n-EN que sí incluía DPF); sus ~32 claves `dpf.*` se removieron de ambos
  diccionarios. Mecanismo de exclusión: marcadores `<!-- i18n:es-only -->` /
  `/* i18n:es-only */` alrededor de los botones de nav, los paneles, y las
  entradas `ROUTE_MAP`/`TAB_TITLES` de las tres tabs — el motor los stripea
  enteros en el bake EN y solo remueve los comentarios-marcador en el bake ES.
- **Ruteo con prefijo**: `FB_BASE` baked (`''` en ES, `'/en'` en EN);
  `ROUTE_MAP` sigue con slugs sin prefijo, un helper (`fbSlug`/`fbHref`)
  normaliza `location.pathname` quitando `FB_BASE` antes de resolver, y todo
  `pushState`/`replaceState` escribe `FB_BASE + slug`. `static/404.html` es
  prefix-aware: si el path perdido empieza con `/en/`, rebota a
  `/en/?path=<resto>` preservando el prefijo; si no, comportamiento de
  siempre. Deep-links a `/en/riesgo`, `/en/dolar` etc. resuelven a la tab
  correcta en inglés; `/en/guia`, `/en/bbv`, `/en/dpf` caen a home EN
  (mismo patrón que un path desconocido).
- **`#langToggle`** (ver arriba): calcula el slug sin prefijo actual y navega
  full-page (no SPA) a `FB_BASE` + slug del otro idioma; si el slug actual es
  una de las tres tabs ES-only, degrada a home del destino.
- **Locale de fechas/números y Plotly**: condicionados a `FB_LANG` baked
  (arrays de meses/días, `toLocaleString`, formateadores custom de fecha,
  registro y aplicación del locale `es` de Plotly — todo gateado a
  `FB_LANG==='es'`; EN usa el default en inglés de Plotly).
- **SEO**: `<html lang="{{lang}}">`, `<link rel="canonical">` propio por
  versión, `hreflang` cruzado (es/en/x-default) en ambos outputs.
- **Noticias en EN**: el contenido (titulares/resúmenes) queda en español
  (es data, no UI); el chrome (feed title, ranking rail, categorías, barra
  admin) sí está en inglés. Nota discreta `.np-lang-note` bajo el subtítulo
  del feed ("News content is in Spanish.") — vacía y colapsada (`:empty` +
  `display:none`) en el bake ES.
- Payload de datos: labels COICOP (IPC) y PIB que `dashboard.py` inyecta al
  JSON se relabelan por idioma contra `i18n/*.json` (prefijo `data.*`) sin
  reconstruir la data dos veces (deep-copy barato de la subtree
  `inflacion` solamente).
- Tests: `scripts/test_i18n_bake.py` (motor + cobertura de tokens template↔
  dicts + slugs COICOP/PIB↔dicts). `scripts/conftest.py` allowlista qué
  módulos de `scripts/` son recolectables por pytest (legacy con `sys.exit`
  a nivel de módulo quedan excluidos de la colección, no de la ejecución
  directa).

**Frontend tab "Noticias"** (en `template.html`):
- Variante D ("Terminal · tabla densa") del mockup de Claude Design
  (`design-system/Noticias-Handoff.md`, no committeado). Activada en
  `feat/noticias-tab`: botón nav `data-tab="noticias"`, contenedor
  `#tab-noticias`, lazy render `window.renderNoticias()` (patrón
  renderBbv/renderGuide).
- **Feed real desde `feat/noticias-real`**, dos carriles en la MISMA
  corrida de `ingest_noticias.py` (un cron, un HC; fail-safe por
  carril — si uno falla el otro corre, y cualquier carril en error
  pingea fail):
  - **Bolivia**: scrape de 24 portales (`scraper.FUENTES`) → geo-gate **ancla Bolivia
    OR tema≠General** (funnel-v2 #130, en `scraper.evaluar` → descarte `falta_bolivia`:
    pasa si ANCLA en Bolivia —término geográfico/adjetivo o entidad boliviana, la
    lógica del gate viejo— **o** clasifica en un tema económico no-General; rescata
    economía boliviana sin ancla geográfica, ej. real "el dólar referencial baja a
    Bs 9,92" → tema Dólar. El set CONTIENE al del gate viejo: solo agrega rescates por
    tema, cero pérdida de recall. El ruido internacional sin ancla NI tema lo siguen
    conteniendo el corte 6.7 + el budget top-N) →
    scoring TF-IDF 0-10 de RELEVANCIA (**modo DEGRADADO por keywords si falta el
    modelo**, calibración 2026-06-21; antes fail-closed) **+ penalización opinión
    ×0.7** (funnel-v2 #130, `scraper.es_opinion` + ajuste editorial en `evaluar`:
    columna/editorial NO se mata —va con `category='opinion'`— pero se penaliza el
    score y no recibe bonos de portal/FX/instituciones) **· piso Bloomberg-Bolivia ≥9**
    (M1: Bloomberg Línea que pasa los gates duros —exclusión + geo-gate— queda ≥9,
    dominando ajustes y el umbral del modelo; solo carril Bolivia) → corte editorial
    `puntaje >= 6.7` → **boost institucional +1** (M2, `_boost_institucional`:
    fuentes primarias INE/IBCE/BCB/ASFI/… reordenan por sobre refritos; se aplica
    DESPUÉS del corte → NO rescata sub-umbral; recomputa `impact`. Split en
    `scraper.FUENTES_INSTITUCIONALES`) → **agrupación por evento + tier de fuente**
    ("También en…", col `tambien_en`; `agrupar_eventos`) → dedupe fuzzy inter-día
    (7 días, umbral 0.70) → **top rotativo por score** (cupo **50/día**,
    `config.NOTICIAS_TOP_BOLIVIA`; con cupo lleno evicta el de menor score del día —
    DELETE físico, #179). **Resumen IA opt-in** (`noticias_ingest/resumen_ia.py`,
    `ANTHROPIC_API_KEY`; sin key → extracto). **Activo en prod desde 2026-06-24.**
    El origen de cada summary se registra en la col `summary_origen`
    (`'ia'`|`'extractivo'`|NULL legacy; migración `0007`, self-migrate en
    `init_schema`/`dashboard.py`): `build_nota` arranca `'extractivo'` y
    `resumen_ia.aplicar` lo sube a `'ia'` en éxito (prompt **V2.1 solo-data** por
    ámbito BO/Latam, calibración 2026-06-25: usa EXCLUSIVAMENTE la info del texto
    provisto —prohibido editorializar causas/contexto—; Latam ya NO se rechaza; el
    centinela `INSUFICIENTE` y los patrones de rechazo de la IA se tratan como FALLO
    → degradan a extractivo; corte ≤200 con límite de palabra LIMPIO, sin `…`).
    La IA se resume sobre el **CUERPO scrapeado completo** (`insumo_para_ia`, ≤10000;
    fallback al detail si el cuerpo no es sustantivo), no sobre el detail de 400 —palanca
    contra el starve que producía INSUFICIENTE. **Re-resumen B→A** (`reresumir_pendientes`,
    paso de `main()` tras los lanes): cada corrida re-fetchea el cuerpo de las no-A de HOY
    (Bolivia) y, con un **pre-gate de suficiencia** ANTES de tocar la API, re-llama la IA
    **solo si** el cuerpo nuevo (1) supera `extract_len` (creció desde el último resumido,
    col `0008`) **y** (2) pasa el piso absoluto `UMBRAL_SUFICIENCIA` (~230, calibrado al
    detail mínimo de una A; el avg de un B es 144). Cap por corrida (`RESUMEN_REINTENTO_TOP`)
    y por nota (`resumen_reintentos`, col `0008`) — gasto API ADICIONAL gateado por el candado
    (`autorizado=True`). El umbral es proxy de longitud, no garantía semántica: un cuerpo
    largo pero basura puede volver INSUFICIENTE igual y lo absorbe el cap. El Deber: **con
    el proxy residencial activo (PR #146) su cuerpo SÍ baja** vía proxy → el re-resumen lo
    promueve a A; sin `PROXY_URL` cae bajo el umbral y solo suma reintentos (fail-safe).
    El frontend **renderiza la bajada (dek)** en las cards BO y el standfirst
    Latam (`ntDekMark`), con
    **asterisco** ` *` al final cuando NO es IA (extractivo/legacy); el descarte de
    `summary≈titular` sigue vigente (dek vacío colapsa). El **TEMA es independiente
    de la relevancia**: lo asigna el motor contextual `_tema`/`_TEMA_SPEC` de
    `scraper.py` (word-boundary + strong/weak/context/exclude, FASE 3) y devuelve
    tema + **confianza** (`tema_hits`); `detectar_entidades` taguea entidades
    canónicas (BCB, YPFB, YLB, FMI…). La caché de URLs vistas la escribe el
    caller (`lane_bolivia` → `scraper.marcar_urls_vistas`): marca insertadas +
    no-calificadas + dedupe-losers, así una calificada que pierde el budget sigue
    reconsiderable (fix de yield, FASE 3).
  - **Instrumentación de embudo** (funnel-v2 #130, WS6): `scraper.LAST_FUNNEL`
    (entran/cache_skip/evaluados/sobreviven/unicos) + el desglose de kills por razón
    se unifican en `lane_bolivia` → `res["funnel"]` de **15 llaves** (entran…insertadas,
    [ingest_noticias.py:545](ingest_noticias.py#L545)), que va al log y al ping
    `HC_NOTICIAS`. El **Noticias Inspector** lo mide etapa-por-etapa (parity FIEL
    post-#130; `parity_test.py` verde). Baseline congelado replay-byte-estable en
    `tools/noticias-inspector/fixtures/baseline-2026-06-24/` (criterio-iteración-2):
    captura prod-fiel + fixture determinista para diffear mismo-input en iteración-3.
  - **Latam** (desde `feat/noticias-latam`): sección Latinoamérica de
    Bloomberg Línea vía RSS outboundfeeds (`noticias_ingest/latam.py`),
    SIN scoring — el criterio editorial de Bloomberg es el filtro
    (decisión de Diego). pubDate últimas 24 h, orden desc, cupo configurable
    (default **8/día**, `config.NOTICIAS_TOP_LATAM`; FASE 3, antes 5)
    con presupuesto INDEPENDIENTE del carril Bolivia. `impact='medio'` fijo,
    `puntaje=0.0` como sentinela "sin scoring" en la DB. El feed de
    sección es flaky (a veces 500/vacío, y cuando responde mezcla otras
    secciones): SIEMPRE se filtra por path `/latinoamerica/` del link,
    con fallback al feed raíz.
  Ambos carriles desembocan en la tabla `noticias` (INSERT OR IGNORE,
  PK = hash del link/guid normalizado; DDL en
  `scripts/migrations/0002_noticias.sql`). `DATA.noticias` = últimos 30
  días (dashboard.py, patrón graceful dpf/embi).
- **Imagen de la nota** (`image_url`, FASE 2a): columna `image_url` TEXT
  nullable en `noticias` (migración `scripts/migrations/0004_noticias_image_url.sql`,
  ADD COLUMN aditivo tras `0003`; distinta de `url`, que es el link al
  artículo). Guarda el `og:image`, parseado del HTML crudo en la **fase
  cuerpo del carril Bolivia** y entregado al frontend como **hotlink directo**
  (sin re-host); el slot cae al placeholder `.np-imgph` cuando es NULL.
  **El Deber: con el proxy residencial ACTIVO (PR #146, `PROXY_URL` en el `.env`
  del VPS desde 2026-06-26) su HTML SÍ baja vía proxy → `og:image` se puebla
  (hotlink `pxcdn.eldeber.com.bo`) y el cuerpo se resuelve a A (inserción +
  re-resumen, ambos cablean el flag `proxy_cuerpo`). Sin `PROXY_URL` vuelve a
  NULL/B (fail-safe, reversible).** **Latam = FASE 2b** (pendiente). `dashboard.py` self-migra
  la columna (ALTER idempotente) para no depender del orden de aplicación de 0004.
- Catálogos del frontend: 24 portales (`NOTICIAS_PORTALS` en `template.html`;
  slugs en `noticias_ingest/transform.py`). **`category` editorial de 5 cubos —
  `{economia, finanzas, politica, internacional, otros}`** (calibración 2026-06-21,
  antes 2; `transform.TEMA_CATEGORIA`): Tipo de cambio/Dólar y Deuda/Finanzas →
  `finanzas`; Bloqueos/Conflictos y Elecciones/Política económica → `politica`;
  `General` → `otros` (relleno, NO se descarta — matar General tiraba ~60-70% de
  noticia relevante mal rotulada); carril Latam → `internacional`. El frontend
  **ordena `otros` como relleno** (después de los carriles de negocios) y **poda el
  sufijo del medio** del título. El detalle de tema vive en `tema`/`tema_hits`/
  `topics`; el **carril** (Bolivia/Latam) en su columna dedicada `carril`, NO en
  `category`. El frontend parte los carriles por `carril` (`ntBolivia`/`ntLatam`).
  `impact` por bandas de puntaje: ≥8 alto · 7–7.99 medio · resto bajo (carril
  Bolivia). `ntSrcTag` tiene fallback defensivo para slugs fuera del catálogo.
- **Colores de marca por portal** (`feat/noticias-latam`): los tokens
  `--src-*` de ambos THEMES son el color de marca real de cada medio
  (investigado de logos/CSS oficiales), ajustado SOLO en luminosidad
  HSL por tema hasta contraste AA ≥4.5:1 contra `bg-secondary` (paper
  `#ffffff` / slate `#122237`). Mecanismo visual: dot + nombre del
  portal coloreados vía `--nt-c` (patrón preexistente, sin CSS nuevo).
- **"Hoy" del tab** (`NT_TODAY`): derivado de `meta.generated_at` (UTC)
  convertido a hora Bolivia (UTC-4 fijo) — determinista entre visitantes;
  fallback al reloj del cliente. `date`/`time` por carril: Bolivia usa
  la fecha/hora de la corrida (no se inventan horas de publicación);
  latam usa el pubDate REAL del RSS convertido a hora Bolivia. La
  columna Hora se quitó de la tabla (solo fecha visible); `time` se
  sigue persistiendo y ordena el feed (`date+time` desc).
- **Agenda placeholder**: `NOTICIAS_EVENTS_BASE` sigue siendo dato de
  ejemplo; el badge `.nt-badge-demo` quedó scopeado SOLO al KPI
  "Próximo hecho" (las noticias reales no llevan badge). El rebase
  `NT_ANCHOR`/`NT_DELTA` sobrevive únicamente para que la agenda no
  envejezca; muere cuando la agenda sea real.
- **Interacciones** (estado en memoria, sin persistencia): chips de
  categoría multi-select con "Todas" como toggle total y conteos del
  dataset completo; toggle "Solo guardadas"; slider de 30 días (burbuja
  con clamp, marcas decorativas por día con nota, HOY outline, flechas
  ±1 día, botón "Todos los días"); tabla densa de 6 columnas (sin Hora)
  con thead sticky y scroll interno (max-height 520px, scrollbar visible);
  acordeón de detalle de fila única con link "Ver nota original" al
  artículo del portal; acciones por fila (leído / guardado / detalle)
  vía event delegation. Los tres filtros se intersectan. Orden fijo
  desc por `date+time` — **sin sort interactivo** (decisión cerrada; la
  tabla no usa `.fb-rank-table` ni `data-sort-key` justamente para no
  heredar el sort genérico ni chocar con el sort propio de BBV).
- **Schema por nota** (contrato backend → frontend):
  `{id, source, category, carril:'bolivia'|'latam', date:'YYYY-MM-DD',
  time:'HH:MM', title, summary, detail, topics:[..], tema,
  temaConfianza, entidades:[..], impact:'alto|medio|bajo', sourceNote,
  url, imageUrl, gallerySlug}` (`url` = link al artículo original; `imageUrl` =
  `og:image` hotlink (FASE 2a), `null` → placeholder `.np-imgph`;
  `carril`/`tema`/`temaConfianza` (=`tema_hits`)/`entidades` agregados en
  FASE 3 — `carril` parte los carriles; `summary` hoy no se renderiza). `detail` es un
  extracto ≤400 chars del cuerpo, nunca el artículo completo (sitio público).
- **Galería de imágenes (v2 — rotación con cooldown)**: cada nota trae `galleryImg`
  precomputado (`slug-k`) → el front (`npImg`) arma `static/gal-<slug>-<k>.webp` en la
  cascada **og:image → galería → placeholder `.np-imgph`** (`galleryImg=null` → placeholder).
  Cada slug tiene un SET de imágenes (`dashboard.GALLERY_SETS`, slug→N); `assign_gallery_images`
  asigna una por nota rotando con cooldown ~3 días (determinístico, stateless; NO fijo
  build-a-build — la imagen de una nota puede cambiar al correr la ventana). **46 imágenes
  reales en 16 slugs, TODAS de Wikimedia Commons** (el slug `elecciones` queda en placeholder:
  no hay foto electoral boliviana con licencia libre en Commons, solo mapas de resultados
  partidarios — descartados por sesgo). Licencias CC BY/BY-SA/CC0/PD verificadas
  archivo por archivo vía Commons API) — fuentes/licencias/autores en `GALLERY-CREDITS.md`;
  los créditos CC se publican en `/creditos-imagenes.html` (`static/`, link en el footer de
  Inicio). microtag "ilustrativa" **solo-admin** (`npAdmin.isAdmin`). **Motor de selección v1.1**
  (`dashboard.py` `gallery_slug_v2`): **PASS de PRIORIDAD POR KEYWORD** sobre
  `title`+`summary`+`detail` normalizado (tabla `GALLERY_KEYWORD_PRIORITY`,
  orden = prioridad, límite de palabra + multipalabra) — ante co-ocurrencia gana
  el tópico de mayor prioridad; sin match → **fallback** al lookup por `tema`
  (`gallery_slug`/`GALLERY_TEMA_SLUGS`); `carril='latam'` → `internacional`. **NO usa
  `temaConfianza`** (NULL en histórico → mataría cobertura) ni `entidades` (v2).
  Solo emite slugs de las 17 imágenes existentes (guarda `VALID_GALLERY_SLUGS` al cargar +
  guarda de existencia de archivo en el test, fail-fast). Reglas `[ENT]` (entidad nombrada):
  `fmi`/`banco-central` con foto propia, `gobierno` sobre las generales y bajo los temas
  concretos; `multilaterales`/`asfi` aún proxy. Tests: `scripts/test_gallery_keyword.py`.
- Visitas en el subheader: **RETIRADAS de la UI** (los KPIs "Visitas hoy / Visitas
  mes" del subheader del tab Dólar se quitaron). Mostraban "—" porque Umami no está
  configurado: `_inject_umami()` solo trae conteos si están las env vars
  `UMAMI_API_KEY` + `UMAMI_WEBSITE_ID` + `UMAMI_HOST`; sin ellas cae a None → "—".
  El mecanismo `_inject_umami` (placeholders + `<script>` de tracking) sigue en
  `dashboard.py` por si se reactiva; ya no hay placeholders en el template, así que
  el `str.replace` es no-op.

### Fase 3 — Análisis / Dashboard

`dashboard.py` lee `p2p_normalized.db` + `bcb_referencial.json` +
`template.html`, produce `index.html` autocontenido (~770 KB) con
Plotly.js, más la versión en inglés `en/index.html` (doble bake vía
`i18n_bake.py` + `i18n/*.json`; misma data). El EN es fail-soft de punta a
punta: si su bake falla, dashboard.py lo omite con warn (el ES no se
bloquea) y `publish_dashboard.py` degrada a warn + EN stale.
Publicado en `https://finanzasbo.com` (edge Cloudflare Pages; la URL del fallback
`https://research-star.github.io/binance_p2p_ingest/` sigue existiendo pero no es el
canal productivo). Opcional `--csv` exporta métricas por snapshot.

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
- BCB TCO (Tipo de Cambio Oficial, RD 88/2026): serie diaria del **nuevo oficial**
  que reemplaza al fijo 6.96 (promedio ponderado de las compras de USD de los
  bancos, publicado 20:00 BO, vigente al día siguiente; venta referencial =
  TCO + 0,10). `ingest_bcb_tco.py` → `bcb_tco.json` → `load_bcb_tco` lo embebe en
  el payload (`bcb_tco_history` / `bcb_tco_last`). En el chart VWAP del tab Dólar
  es una **serie nueva** (`#B45309`, toggle "TCO oficial"): **1 dato = punto, ≥2 =
  línea conectada**. La KPI **Prima P2P se calcula vs el TCO** (antes vs el fijo
  6.96, hoy obsoleto), con fail-soft al 6.96 si aún no hay datos de TCO. El ticker
  "El día en cifras" (landing Noticias) también usa el TCO como "BCB oficial".
  - **Dating por VIGENCIA**: el `fecha` del CSV (y de `bcb_tco.json`) es la fecha
    en que el TCO **rige**, no la de las operaciones. El cierre del viernes se
    publica como vigente el **lunes** (regla de fin de semana de la RD 88/2026),
    así que la fecha de vigencia va por DELANTE de "hoy". Por eso: (a) el rango de
    descarga lleva buffer `+5 días` en `hasta`; (b) el chart **dibuja el TCO
    adelantado** — `rVwap` no clipea los puntos TCO por el borde derecho del P2P y
    **extiende el eje X** hasta el último TCO (el oficial siempre va ~1 día hábil
    por delante y el P2P lo va alcanzando).
  - **Re-fechado de la publicación del viernes** (`_redate_weekend_publications`,
    dashboard.py — corre ANTES del relleno): la BCB timbra la publicación del
    viernes 20:00 con `Fecha de vigencia` = **sábado** (día-siguiente nominal;
    `ingest_bcb_tco.py:416` guarda esa columna tal cual). Pero por la regla operativa
    (RD 88/2026 art. 5, confirmada por Diego 2026-07-20: lo publicado el **jueves es
    válido hasta el domingo**; lo publicado el **viernes entra en validez el lunes**)
    ese valor recién rige el próximo día hábil. Como la BCB no publica finde, TODA
    entrada publicada fechada en sáb/dom es la del viernes mal-timbrada → se **mueve
    al lunes** (dedup si el lunes ya existe). Esto además corrige el **falso positivo
    de `bcb_tco_stale` los lunes** (la última vigencia deja de ser un sábado < hoy).
  - **Relleno de fin de semana** (`_fill_weekends_tco`, dashboard.py — corre DESPUÉS
    del re-fechado): sábados y domingos se rellenan con el TCO **VIGENTE del viernes**
    (= último día hábil publicado ANTERIOR, backward-fill). Efecto uniforme en KPI,
    gráfico, ticker "día en cifras" y tarjeta `/boletin-4k9x/`: **el delta día del
    finde queda plano y el salto aparece el lunes** (ej. vie 10.75 → finde 10.75 →
    lun 10.85 = +0,10). Las entradas sintéticas llevan `source='bcb_tco_fin_semana'`,
    NO pisan publicados; el ticker/KPI/boletín usan **vigente-hoy** = `bcb_tco_history`
    con `fecha ≤ hoy`, no `bcb_tco_last`. Un finde sin día hábil publicado anterior
    queda hueco (no se inventa). `bcb_tco.json` queda PURO (solo lo del BCB); tanto el
    re-fechado como el relleno son derivados en build.
  - **KPI "BCB Ref" = TCO / TCO+0,10** (RD 88: la venta referencial es TCO + 0,10),
    reordenada **primera** en la fila de KPIs. Fail-soft a `bcb_referencial` si aún no
    hay TCO. La **banda "BCB Ref" del gráfico se retiró** (toggle + traces): era
    redundante con la serie TCO y la KPI; el chart del Dólar solo tiene Compra (P2P)
    + TCO. Se quitaron también los sublabels "Prima BCB Ref" de USDT Compra/Venta
    (duplicaban la KPI "Prima P2P", que queda como única métrica de prima).

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
- Logs: `/var/log/binance_p2p/{ingest.log, ingest.err, normalize.log, watchdog.log, bcb_ref.log, dashboard.log, embi.log, ine_ipc.log, ine_ipp.log, noticias.log}`
- Env vars (incluye `HC_*`): `/opt/binance_p2p/.env`

**systemd unit:** `binance-ingest.service` (`Type=simple`, `Restart=on-failure`,
`RestartSec=30`). Append a `ingest.log`/`ingest.err`.

**Cron del user `binance`** (sincronizado con `crontab -l` real el 2026-07-08;
los UUIDs `HC_*` viven como env vars arriba del crontab y en `.env`). **14 jobs**;
la columna HC anota la cobertura de healthcheck real:

```
# job                    schedule (UTC)          healthcheck
normalize.py             */5  * * * *            + curl $HC_NORMALIZE
scripts/watchdog.py      */5  * * * *            pingea HC_INGEST si snapshot reciente
publish_dashboard.py     */12 * * * *            + curl $HC_DASHBOARD
bcb_scrape_and_commit.sh 5,35 12-15 * * 1-5      — SIN HC
ingest_embi.py           0    10,22 * * *        pingea HC_EMBI desde código (sin curl en cron)
ingest_ine_ipc.py        15   5,11,17,23 1-10 * *  + curl $HC_INE_IPC
ingest_ine_ipp.py        30   5,11,17,23 1-10 * *  + curl $HC_INE_IPP
ingest_noticias.py       7    0,11-23 * * *       pingea HC_NOTICIAS desde código (start/éxito/fail)
bcb_tco_scrape_and_commit.sh  */5 0-3 * * 2-6    — SIN HC (HC_BCB_TCO no está en .env)
scripts/retencion_noticias.py 40 4 * * *         — SIN HC (backup 20d + borrado 30d de `noticias`)
bcb_tre_scrape_and_commit.sh  15 12 * * *        — SIN HC (HC_BCB_TRE no está en .env; TRE mensual, no-op si el mes ya está)
asfi_scrape_and_commit.sh 10  1,13,23 * * *       — SIN HC
ingest_asfi.py --resumir 30   12 2 * *           — SIN HC (mensual: promueve resúmenes IA bajo el cap)
ingest_ine_comunicado.py 45   5,11,17,23 1-15 * *  — SIN HC (overlay provisional IPC, #221)
```
(Todos con `>> /var/log/binance_p2p/<nombre>.log 2>&1`.)

**Cobertura HC — 7 jobs SIN healthcheck:** `bcb_scrape`, `bcb_tco`,
`retencion_noticias`, `bcb_tre`, `asfi_scrape`, `ingest_asfi --resumir`,
`ingest_ine_comunicado`. (Los wrappers `bcb_tco`/`bcb_tre` *pingearían* si
`HC_BCB_TCO`/`HC_BCB_TRE` estuvieran en `.env`, pero no lo están → sin ping.)

**Desincronía crontab↔.env (benigna):** las cabeceras del crontab todavía
comentan `HC_EMBI` y `HC_NOTICIAS` como `<pending>`, pero **ambos ya existen en
`.env`** y sus scripts los pingean desde código. El comentario del crontab quedó
stale; el ping funciona. El cron de `ingest_embi.py` **no tiene `curl` de ping en
la línea** — el ping ocurre dentro del script.

**Ausentes:** `HC_BCB` (los scrapers BCB de referencial no tienen HC) y
`HC_INE_PIB` (no hay cron de PIB — el ingest de PIB está PAUSADO por decisión,
ver § 0 y § 8).

**Auto-publish workflow** (`.github/workflows/auto-publish.yml`):
- Dispara en cada push a `main`, con `paths-ignore: bcb_referencial.json` + `bcb_tco.json`.
- SSH al VPS → `git pull --rebase origin main` → borra
  `publish_dashboard.last_size` (cache bust) → `.venv/bin/python scripts/publish_dashboard.py`.
- Secret: `HETZNER_SSH_KEY` (repo settings).
- Concurrency: grupo `publish-dashboard`, `cancel-in-progress: false`.

**Healthchecks (healthchecks.io):**
- `HC_INGEST` — pingeado desde `scripts/watchdog.py` cuando hay snapshot reciente. Confirmado en código del repo.
- `HC_NORMALIZE`, `HC_DASHBOARD` — pingeados desde la cron line en VPS (no desde código del repo).
- `HC_BCB` — **pendiente** (ver § 6).
- `HC_BCB_TCO` — pingeado desde `scripts/bcb_tco_scrape_and_commit.sh` (start / éxito / fail vía trap). **Pendiente**: crear el UUID en healthchecks.io (modo **Cron**, expr `5 0 * * 2-6`, TZ **UTC**, grace 2h) y agregarlo como `HC_BCB_TCO` al `.env` + env del crontab. Sin la var, los pings se omiten graceful (no rompe).
- `HC_EMBI` — pingeado desde `ingest_embi.py` (start / success-with-body / fail-with-body). Period 12h grace 6h.
- `HC_NOTICIAS` — pingeado desde `ingest_noticias.py` (start / success-with-body / fail-with-body). Ping fail si CUALQUIER carril (Bolivia o latam) erró; el body trae el resumen por carril — un fail puede convivir con inserts del carril sano. Sin modelo TF-IDF el carril Bolivia corre en **modo DEGRADADO por keywords** (calibración 2026-06-21; antes fail-closed con exit 1) y reporta `scoring=keywords`; latam corre igual. UUID en `.env` (activo desde 2026-06-11). Cadencia ~14×/día (horario 07:07–20:07 BO desde 2026-06-23). Monitoreo en **modo Cron** (cron expression `7 0,11-23 * * *`, timezone **UTC**, grace time **2h**). **NO usar modo Simple/period**: el cron tiene gap nocturno (~11h sin corridas, 20:07→07:07 BO) que un period fijo interpretaría como caída y dispararía falsa alarma cada noche.

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
→ `publish_dashboard.py` → push a `gh-pages` → **dual-publish a Cloudflare Pages**
(Direct Upload del mismo worktree, edge productivo desde el cutover 2026-07-06).
Verificar contra `finanzasbo.com` directo puede devolver HTML viejo porque el
edge (Cloudflare Pages) también cachea — eso **no significa que el deploy falló**.
La fuente de verdad de frescura sigue siendo el **`raw` de `gh-pages`** (sin CDN
delante; el dual-publish sigue pusheando ahí, así que refleja el mismo bake que
sube a CF).

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
- Edge productivo (opcional) — confirmar que `finanzasbo.com` sirve desde
  Cloudflare Pages:
  ```
  curl -sI https://finanzasbo.com | grep -iE '^server:|^cf-ray:'
  ```
  Esperado: `server: cloudflare` + `cf-ray` presente. (El deploy CF es NO-FATAL
  en `publish_dashboard.py`: si falla, `gh-pages` igual quedó publicado y el
  fallback sigue vivo — ver el log `cf=ok/skip/error` en `dashboard.log`.)

**2) Verificar el HTML en vivo evitando cache stale**

- **Preferido** — `raw` de `gh-pages`, sin CDN delante (fuente de verdad de
  frescura; refleja el mismo bake que el dual-publish sube a CF):
  ```
  curl -sL https://raw.githubusercontent.com/research-star/binance_p2p_ingest/gh-pages/index.html -o /tmp/raw.html
  ```
- **Alternativa** — edge productivo (Cloudflare Pages) con cache-buster agresivo:
  ```
  curl -sL -H "Cache-Control: no-cache" -H "Pragma: no-cache" \
       "https://www.finanzasbo.com/?_cb=$(date +%s%N)" -o /tmp/live.html
  ```
  El cache-buster nanosegundo (`%s%N`) bustea casos donde `?_cb=<epoch>`
  integer no fue suficiente — visto en verificación de PR #36 (entonces con CDN
  del custom domain de GitHub Pages; el edge CF cachea con la misma lógica).

**3) Campo a chequear**

`meta.generated_at` (string ISO embebida en el payload JSON inline del
`index.html`) debe ser `>=` el `mergedAt` del PR. Si es anterior al merge, el
HTML que estás viendo es de un publish previo (cache stale del CDN, o el
publish post-merge aún no llegó al CDN).

**4) Diagnóstico cuando algo no cuadra**

| Síntoma | Causa probable | Acción |
|---|---|---|
| Edge (`finanzasbo.com`, Cloudflare Pages) devuelve HTML viejo, raw `gh-pages` está fresco (`generated_at` posterior al merge) | Cache del edge stale | Esperar, o re-fetch con cache-buster nanosec + headers no-cache. **NO es deploy roto.** |
| Raw `gh-pages` también está viejo (`generated_at` anterior al merge) | Deploy roto o skipeado | Investigar `gh run view <run-id>` y `/var/log/binance_p2p/dashboard.log` en el VPS. |
| Workflow dice `success` en ~5-10 s en lugar de ~20 s | Race-lock con cron `*/12` (publish salió limpio sin generar HTML porque el cron tenía el lock cooperativo) | Esperar al próximo tick del cron, o forzar manual: `ssh -i ~/.ssh/id_ed25519_hetzner binance@46.62.158.88 "cd /opt/binance_p2p && rm -f /var/log/binance_p2p/publish_dashboard.last_size && .venv/bin/python scripts/publish_dashboard.py"`. |

> **Caveat histórico** (PR #36, 2026-05-25; host de entonces: GitHub Pages —
> hoy `finanzasbo.com` es edge Cloudflare Pages): un cache stale del CDN se
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

## 5. — retirada

Sección retirada (2026-06-10): el "WIP / áreas calientes" mantenido a mano
quedaba fósil en cada merge. El estado vivo está en **§0** y el tracking de
workstreams en **Notion**. Se conserva el número de sección para no romper
las referencias existentes a §6–§8.

---

## 6. Pendientes abiertos

- [ ] **Flip del repo a privado** — hoy `research-star/binance_p2p_ingest` es
      **público** (verificado 2026-06-17). El flip a privado está pendiente y
      requiere **GitHub Pro primero** (Pages sobre repo privado necesita plan
      pago). Decisión/acción de Diego.
- [ ] **Rediseño del top-UI / login** — próximo workstream. Reubicar o crear el
      acceso de login, que hoy está gated tras `#admin` dentro de la tab Noticias
      (ver §0 "Anatomía del header"). Brief por venir.
- [ ] **Housekeeping git** — las ramas de la feature ocultar-noticias quedaron
      **sin borrar** en `origin` tras merge: `feat/publish-consume-hidden` (#68),
      `feat/noticias-filtro-client` (#69), `feat/noticias-admin-ui-pr-c2` (#70).
      Además, cruft local en la laptop de Diego (working tree: `index.html`
      modificado + untracked `design-system/`, `worker-spike/`,
      `docs/clasificacion_nandina_granos.html`). Limpieza aparte.
- [ ] **`HC_BCB` healthcheck** — crear UUID en healthchecks.io, agregar a
      `/opt/binance_p2p/.env` como `HC_BCB`, y appendear
      `&& curl -fsS --max-time 10 https://hc-ping.com/$HC_BCB > /dev/null`
      al cron line del BCB. Sin esto, falla del scraper es silenciosa.
      (Follow-up de PR #20.)
- [x] **Deploy INE inflación (IPC + IPP) a VPS** — HECHO (2026-06-08):
      cron instalado, `HC_INE_IPC`/`HC_INE_IPP` activos, tablas `ine_ipc` /
      `ine_ipp` pobladas en prod. Detalle en §8.
- [ ] **Deploy INE PIB** — código en main y tabla `ine_pib` creada (vacía),
      pero el ingest quedó **PAUSADO por decisión estratégica** (lag
      estructural del XLSX del INE, ver §8). Reanudar = 5 líneas de cron +
      env var `HC_INE_PIB` (pausado en healthchecks.io) + primer run manual.
- [x] **Deploy tab Noticias — FASE B** — HECHO (2026-06-11, autorizado por
      Diego; PR #50 mergeado): deps instaladas en `.venv` (sklearn **pineado
      1.8.x en el venv** — 1.9 cargaba el pkl con `InconsistentVersionWarning`;
      requirements acota `<1.9`), migración `0002_noticias.sql` aplicada,
      corrida de prueba OK (95 candidatos, 10 filas insertadas, 41 s,
      `scoring=tfidf`), cron `45 11 * * *` UTC instalado (11:45, corrido de
      11:30 por colisión con `ine_ipp` días 1-10; backup del crontab previo
      en `/tmp/crontab.pre-noticias.bak` del VPS; **schedule original —
      cambiado a `7 0,11-23 * * *` (14×/día) el 2026-06-23, ver la tabla de
      crons al inicio**), `HC_NOTICIAS` en `.env`
      con ping de prueba OK. Addendum fail-closed (sin modelo TF-IDF → fail
      + exit 1, sin scrape) entregado en PR aparte post-deploy.
      **Caveat vigente**: la cache key del publish (`n_snap, n_rows,
      embi_max, ipc_max, ipp_max`) NO incluye noticias — las notas del día
      entran al próximo republish disparado por snapshots de ads (~12-22 min
      tras el cron); si se quiere garantía, extender la key con `max(date)`
      de `noticias` (precedente exacto: `embi_max`).
      **Watch-item**: La Razón falló su primer scrape desde la IP del VPS
      (12/13 portales OK) — puede ser transitorio o bloqueo a IP datacenter;
      vigilar los primeros días en `noticias.log`.
- [ ] **Cache key de `publish_dashboard.py`** — el cache (ahora
      `(n_snap, n_rows, embi_max, ipc_max, ipp_max)`; los dos últimos son
      `MAX(periodo) WHERE valor IS NOT NULL` de `ine_ipc`/`ine_ipp`, sumados
      en feat/inflacion-contenido para que un release del INE republique)
      sigue sin invalidar con cambios de código (`template.html`, `static/`).
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
- [x] **Cierre del período de gracia de rollback** — CERRADO (2026-06-10,
      pre-autorizado por Diego): `p2p_normalized.db.pre-migration-*` borrado
      de la laptop tras verificar cadena de backup fresca (pull del VPS del
      mismo día, `quick_check` ok, retención GFS aplicada, task diario
      registrado). El Task Scheduler "P2P Watchdog" viejo fue desinstalado
      el 2026-06-12 (pre-autorizado). Ítem completamente cerrado.

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
3. **JS dinámico** (`THEMES.paper/.slate` + `applyTheme()`): reescribe via
   `root.style.setProperty()` al togglear tema. Maneja vars semánticas
   (`bg-*`, `text-*`, `color-*`, `border-color`) y además los 43 tokens
   de chart/tooltip/noticias entregados via `THEMES` (ver "Delivery de
   tokens" abajo).
4. **`body.theme-dark{}` CSS**: overrides dark de tokens consumidos sólo
   por CSS — hoy `--shadow-sm/md/lg/xl` + reglas ad hoc por componente
   (`.pill-*`, `.fb-stog`, etc.).

### Categorías de tokens

| Categoría | Tokens | Theme-dependent | Override en |
|---|---|---|---|
| Tipografías | `--font-display`, `--font-body`, `--font-mono` | no | — |
| Tamaños texto | `--text-2xs` ... `--text-5xl` (11 niveles) | no | — |
| Radios | `--radius-xs/sm/md/lg/xl` + `--radius-pill` | no | — |
| Sombras | `--shadow-sm/md/lg/xl` | sí | `body.theme-dark{}` (CSS-consumed) |
| Tooltip | `--tooltip-bg` (literal) + `--tooltip-text/border/font` (vía vars theme-aware) | sí | JS `THEMES.paper/.slate` (`--tooltip-bg` se consume por `cssVar()`) |
| Bg/text/border/color-* | (existentes) | sí | JS `THEMES.paper/.slate` |
| Chart EMBI (Riesgo País) | `--chart-color-*` (10 países), `--chart-grid`, `--chart-axis-text`, `--chart-spike` | sí | JS `THEMES.paper/.slate` |
| Bandas riesgo EMBI (Riesgo País) | `--chart-band-low/mid/high` (fills rect, alpha baked-in) + `--chart-band-label-low/mid/high` (texto annotations) | sí | JS `THEMES.paper/.slate` |
| Chart heatmap (P2P + Activity) | `--chart-heatmap-0/25/50/75/100` (gradient stops), `--chart-heatmap-text-high/low` (per-cell text) | sí | JS `THEMES.paper/.slate` |
| Chart DPF scatter | `--chart-dpf-bancos-multiples/microfinanzas/bancos-pyme/ent-vivienda/cooperativas/ifd` (6 categóricos) | sí | JS `THEMES.paper/.slate` |
| Chart spread evo P2P | `--chart-spread-line` (color de la línea única) | sí | JS `THEMES.paper/.slate` |
| Chart inflación (IPC/IPP) | `--chart-ipc-general`, `--chart-ipp-general`, `--chart-infl-total`, 12 `--chart-ipc-*`, 6 `--chart-ipp-*` | sí | JS `THEMES.paper/.slate` |
| Chart deuda soberana (Riesgo País) | `--chart-debt-em2017/em2022/em2026` (3 categóricos por emisión) | sí | JS `THEMES.paper/.slate` |
| Chart markers (shared) | `--chart-marker-outline` (halo decorativo α=.6, color = bg-secondary del tema) | sí | JS `THEMES.paper/.slate` |
| Noticias (tab) | `--cat-*` (6 categorías), `--src-*` (24 portales), `--impact-*` (3 niveles) | sí | JS `THEMES.paper/.slate` (consumidos por CSS via `var()`; ver nota en Delivery) |

### Tech debt residual

- **Migración de colores hardcodeados en CSS/HTML (fuera de Plotly JS)**:
  literales hex `#1e4d7a`, `#6b7d92`, `#5589c0`, `#8c8c8c` aparecen en
  `style="--fb-trace-color:..."` inline en los toggles del panel VWAP
  ([template.html:847](template.html#L847); los hex concretos rotaron con el
  recoloreo del panel — el patrón inline-hardcodeado persiste), y hex en CSS puro
  (`.fb-pill.active`, `.fb-dpf-bar`, `.pill-yellow/.pill-red`, `.fb-stog*`,
  `.error-banner`). No bloqueante — los valores coinciden con tokens
  semánticos existentes (`color-buy/sell/bcb-*`), pero la migración requiere
  o reescribir HTML generado por `dashboard.py` (para inline) o refactor de
  las reglas CSS para que consuman `var(--token)`.
- **Heatmap per-cell text en la frontera value≈0.6**: el threshold de
  `heatmapTextColors()` ([template.html:1878](template.html#L1878)) clasifica cada celda como
  high/low según valor normalizado ≥0.6. En la frontera exacta, el texto
  de "low" sobre celda de luminosidad mid-alta (y el de "high" sobre celda
  mid-baja en su lado) da contraste ~3:1, sub-WCAG-AA 4.5:1 para texto. El
  problema existe simétricamente en ambos temas y resolverlo requiere mover
  el threshold (cambia clasificación visual de las celdas, decisión de
  diseño). No bloqueante mientras los valores en la frontera sean infrecuentes.

**Estado actual de tooltips Plotly:** todos los charts (VWAP P2P, Spread,
Depth, Ratio, Conc, Heatmap, Activity Heatmap, SpreadEvo, OrderBook, Offer,
DPF scatter, EMBI Riesgo País) comparten estilo via `cssVar('--tooltip-*')`.
`--tooltip-bg` se entrega desde `THEMES.paper/.slate` (`#dde8ef` light,
`#1c2632` dark sólido). Helper `cssVar()` vive a scope módulo (cerca de
`getC()`), reutilizable por cualquier chart.

**Estado actual de chrome Plotly (axis text, grid, line/marker colors):**
los charts que pasan por `BL(c)` (VWAP, Spread, Depth, Ratio, Conc, Heatmap,
ActivityHm, SpreadEvo, OrderBook, Offer) heredan font/tickfont/gridcolor
desde `getC()` que lee `text-secondary/text-muted/border-color` de
`activeThemeValues`. El DPF scatter define layout propio (no pasa por
`BL`) y consume `cssVar('--text-muted')` / `cssVar('--chart-grid')` /
`cssVar('--chart-marker-outline')` directo. El EMBI define layout propio
y consume `cssVar('--chart-axis-text')` / `cssVar('--chart-grid')` /
`cssVar('--chart-spike')`.

### Reglas de uso

- **Cuándo agregar un token**: valor literal repetido ≥2 veces, con razón
  funcional/semántica (no accidental), con override potencial por tema.
- **Cuándo NO**: uso único (literal directo OK), valor derivable (composiciones
  como `var(--radius-sm) 0 0 var(--radius-sm)`), valores intencionalmente
  contextuales (`rgba(0,0,0,0)` transparente Plotly).
- **Plotly hoverlabel**: siempre via `cssVar('--tooltip-*')`. Todos los
  charts ya consumen este patrón.
- **Para retocar paleta de un chart**: editar `THEMES.paper/.slate` en el JS.
  - Chart EMBI: `--chart-color-*` (países), `--chart-grid`, `--chart-axis-text`, `--chart-spike`; bandas de régimen de riesgo: `--chart-band-low/mid/high` + `--chart-band-label-low/mid/high`.
  - Heatmap (P2P + Activity): `--chart-heatmap-0/25/50/75/100`, `--chart-heatmap-text-high/low`.
  - DPF scatter: `--chart-dpf-*` (6 categóricos) — chrome (`--text-muted`, `--chart-grid`, `--chart-marker-outline`) se hereda.
  - Spread evo P2P: `--chart-spread-line`.
  - Cualquier scatter con marker outline: `--chart-marker-outline`.

  Para retocar el layout (legenda, tickformats, márgenes) editar el JS del
  chart correspondiente.
- **Helper compartido para heatmaps**: `heatmapColorscale()` y
  `heatmapTextColors(zNorm)` ([template.html](template.html)) son scope módulo y consumen los
  tokens `--chart-heatmap-*` via `cssVar()`. Ambos heatmaps (P2P por hora,
  Activity por día×hora) los usan — la rampa y el threshold 0.6 quedan
  garantizados-idénticos por construcción. Cualquier nuevo heatmap debe
  pasar por estos helpers en lugar de definir colorscale propia.
- **Delivery de tokens theme-dependent**: depende de quién los consume.
  - **Consumidos por JS via `cssVar()`** (que lee de `documentElement`) →
    viven en `THEMES.paper/.slate`. `applyTheme()` los escribe sobre
    `documentElement` via `root.style.setProperty()`, donde `cssVar()` los
    encuentra. Hoy en `THEMES` (81 tokens chart/tooltip/noticias/inflación):
    - Tooltip: `--tooltip-bg`.
    - EMBI: `--chart-grid`, `--chart-axis-text`, `--chart-spike`, los 10 `--chart-color-*`,
      y 6 de bandas de riesgo (`--chart-band-low/mid/high` + `--chart-band-label-low/mid/high`).
    - Heatmap (P2P + Activity): `--chart-heatmap-0/25/50/75/100`, `--chart-heatmap-text-high/low`.
    - DPF scatter: 6 `--chart-dpf-*`.
    - Spread evo P2P: `--chart-spread-line`.
    - Inflación: `--chart-ipc-general`, `--chart-ipp-general`, `--chart-infl-total`,
      12 `--chart-ipc-*` (divisiones COICOP) y 6 `--chart-ipp-*` (secciones).
    - Deuda soberana (Riesgo País): 3 `--chart-debt-em*`.
    - Markers (shared): `--chart-marker-outline`.
    - Noticias: 6 `--cat-*`, 13 `--src-*`, 3 `--impact-*`. Caso especial:
      los consume **CSS** (reglas `.nt-*` + custom prop `--nt-c` inline),
      no `cssVar()`, pero viven en `THEMES` igual — el inline style de
      `documentElement` hereda hacia abajo, así light y dark quedan en
      un solo lugar en vez de partirse entre `:root{}` y
      `body.theme-dark{}`.
  - **Consumidos sólo por CSS** (selectores `var(--token)` en reglas que
    aplican a descendientes del `<body>`) → pueden vivir en `:root` para
    el default light + `body.theme-dark{}` para el override dark. Hoy en
    `body.theme-dark{}`: `--shadow-sm/md/lg/xl`, más overrides ad hoc
    (`.pill-yellow/.pill-red`, `.fb-stog*`, etc.).
  - **Razón**: las CSS vars no cascadean hacia arriba — un override en
    `body.theme-dark{}` no alcanza a `documentElement`, así que `cssVar()`
    leería el default light en dark mode.

### Tokens deprecados / alias

- `--kpi-value-size` → alias de `--text-5xl` (`--kpi-value-size: var(--text-5xl)`
  en L25). Se mantiene para no romper `.kpi .value` ni los entries actuales
  en `THEMES.paper/.slate` JS (que escriben `'kpi-value-size':'28px'`).
  Marcar para futura limpieza cuando se migre la regla `.kpi .value` y los
  entries JS.

---

## 8. Ingest INE Bolivia (macro: PIB + IPC + IPP)

Ingesta de cuadros estadísticos del **Instituto Nacional de Estadística** de
Bolivia (PIB, IPC, IPP) desde el Nextcloud/Owncloud público del INE
(`nimbus.ine.gob.bo` + `nube.ine.gob.bo`, dos hosts conviviendo). Espeja la
estructura de `ingest_embi.py` con dos adaptaciones por características
distintas de la fuente: (a) no hay ETag/Last-Modified, (b) hay múltiples
cuadros por familia.

**Estado de deploy (2026-06-08): solo inflación desplegada.** IPC e IPP
corren en cron VPS y tienen tablas pobladas (`ine_ipc`, `ine_ipp`). PIB
quedó **PAUSADO por decisión estratégica** — el código está en main, la
tabla `ine_pib` se creó vacía durante la migración (para facilitar reanudar
sin re-migrar), pero el ingest NO está scheduleado y `HC_INE_PIB` está
pausado en la UI de healthchecks.io. Reanudar es: agregar 5 líneas cron +
1 env var `HC_INE_PIB` + primer `ingest_ine_pib.py` manual.

### Componentes

| Archivo | Rol |
|---|---|
| `ingest_ine_pib.py` | Entry point de la familia **PIB** (5 cuadros) |
| `ingest_ine_ipc.py` | Entry point de la familia **IPC** (3 cuadros) |
| `ingest_ine_ipp.py` | Entry point de la familia **IPP** (2 cuadros) |
| `ine_parser.py` | Adapters de parsing por layout (5 funciones, 7 keys vía aliases) |
| `config.INE_CUADROS` | Registry de cuadros: host primario, token, family, layout, metadata |
| `scripts/migrations/0001_ine_tables.sql` | DDL idempotente de las 4 tablas |

### Catálogo V1

8 cuadros. Detalles: `config.INE_CUADROS`.

- **PIB Trimestral** (host nimbus, layout `pib_trim_vertical`): `pib_trim_01_01_01`
  (PIB cte por actividad), `pib_trim_01_01_04` (var YoY actividad),
  `pib_trim_02_01_01` (PIB cte por gasto). Cobertura 1990 Q1–presente.
- **PIB Anual Serie Histórica** (host nube, layout `pib_anual_wide`):
  `pib_anual_serie_actividad`, `pib_anual_serie_gasto`. Cobertura 1980–presente.
- **IPC** (host nube): `ipc_nacional_general` (layout `ipc_nacional`),
  `ipc_division_coicop` (layout `ipc_coicop_doubleheader`), `ipc_empalmada`
  (layout `ipc_empalmada`). Cobertura IPC nacional 2018–presente; serie
  empalmada 1937–presente.
- **IPP** (Índice de Precios al Productor, host nube): `ipp_nacional`
  (layout `ipp_nacional`), `ipp_grandes_grupos` (layout `ipp_grandes_grupos`).
  Cobertura 2017-01 a presente, base 2016=100. Estructuralmente idéntico al
  IPC, los layouts son aliases en `LAYOUT_DISPATCH` que reutilizan
  `parse_ipc_nacional` y `parse_ipc_coicop` respectivamente.

Fuera del scope: IPM, PIB departamental, IPC por ciudad, Referencia 2017.

### Layouts de parsing

| Layout | Forma | Cuadros |
|---|---|---|
| `pib_trim_vertical` | Periodo en filas (5 filas/año), dimensiones en columnas | PIB Trimestral (3) |
| `pib_anual_wide` | Series en filas, años en columnas C-AU | PIB Anual Serie Histórica (2) |
| `ipc_nacional` / `ipp_nacional` (alias) | Mes en filas, años en columnas (4 hojas = 4 indicadores) | IPC Nacional general, IPP Nacional |
| `ipc_coicop_doubleheader` / `ipp_grandes_grupos` (alias) | División en filas, doble header (año mergeado + mes), 4 hojas | IPC División COICOP (13 divs), IPP Grandes Grupos (7 grupos actividad) |
| `ipc_empalmada` | Mes en filas, 90 años en columnas (4 hojas) | IPC Empalmada |

Quirks comunes que el parser maneja: mojibake CP1252-en-UTF-8, sufijo `(p)`
preliminar, filas separadoras vacías, filas total trailing (`PROM. ANUAL`,
`ACUMULADA`), labels multi-línea (PIB anual), unidad declarada en fila
aparte (no en headers), año mergeado en header del COICOP.

### Schema (4 tablas, ver `scripts/migrations/0001_ine_tables.sql`)

- **`ine_pib`** — PK `(cuadro, periodo, dimension)`. `periodo` es `'YYYY-Qn'`
  para trim o `'YYYY'` para anual. `dimension` es sector económico o
  componente del gasto (slugified). `unidad` ∈ {`miles_bs_1990`, `pct_yoy`, …}.
  `is_preliminary` flagea años con `(p)` en el header.
- **`ine_ipc`** — PK `(cuadro, periodo, indicador)`. `periodo` es `'YYYY-MM'`.
  Para IPC nacional/empalmada: `indicador` ∈ {`indice`, `var_mensual`,
  `var_acumulada`, `var_12m`}. Para IPC COICOP: `indicador` es compound
  `<metric>_<division_slug>` (52 combinaciones únicas).
  `unidad` ∈ {`indice_base_2016`, `pct_mensual`, `pct_acumulada`, `pct_12m`}.
- **`ine_ipp`** — misma forma que `ine_ipc`. PK `(cuadro, periodo, indicador)`.
  Para `ipp_nacional`: `indicador` ∈ {`indice`, `var_mensual`, `var_acumulada`,
  `var_12m`}. Para `ipp_grandes_grupos`: `indicador` es compound
  `<metric>_<grupo_slug>` (28 combinaciones = 4 × 7), con `_total` para
  div 0 (grupo "ÍNDICE GENERAL"). Tabla separada de `ine_ipc` porque IPP
  mide precios al productor industrial, no del consumidor — los dashboards
  los modelan como series independientes.
- **`ine_ingest_state`** — PK `cuadro`. 1 fila por cuadro_id (10 total con IPP).
  Sustituye al patrón `.last_etag`-en-disco de EMBI porque el Nextcloud del
  INE no emite ETag ni Last-Modified.

### Detección de release (asimétrica por familia)

- **IPC / IPP**: el filename del `Content-Disposition` trae `YYYY_MM` (ej.
  `Nal-2026_05_…` para IPC, `IPP-2026_04_…` para IPP). El campo `release_id`
  se extrae del filename. Detección barata a futuro vía HEAD si el dataset
  crece, hoy GET completo.
- **PIB**: filename estático (`01.01.01.xlsx`). La fecha vive **dentro** del
  XLSX (título R8). `release_id` = prefijo del MD5 del body. Siempre se
  descarga y se compara MD5 contra `ine_ingest_state` antes de re-parsear.

Si MD5 no cambió → `mode=skip` instantáneo, no toca DB ni audit.

### Idempotencia y backfill

Cada XLSX trae la serie completa desde el inicio del cuadro. `INSERT OR
REPLACE` por la PK hace upsert idempotente. Si INE publica una revisión
retroactiva (ej. corrige un trimestre viejo), el cambio entra
automáticamente sin migración. No hay backfill incremental separado.

**Guardia anti-collapse:** antes del `INSERT OR REPLACE`, los 3 scripts
(PIB, IPC, IPP) validan que no haya dos filas del batch con la misma PK
con valores distintos. Si las hubiera, el script falla con `RuntimeError`
antes de tocar la DB. Esto detecta typos del INE en labels de año/dimensión
que en otra circunstancia colapsarían silenciosamente datos del año A sobre
el año B (caso real observado: cuadro `pib_trim_02_01_01` release 2026-05
trae el label `'2022p)'` sin paréntesis abrir; el parser tolera ese caso
específico via regex, y la guardia cubre cualquier variante futura).

### PIB Trimestral — lag estructural del XLSX

INE publica los cuadros XLSX del hub PIB Trimestral con ~17 meses de lag
respecto al trimestre más reciente (al 2026-06-08, el XLSX más fresco
llega hasta Q4 2024). Las **notas de prensa PDF** sí adelantan ~12 meses
respecto al XLSX — ej. la nota Q4 2025 se publicó el 2026-04-21 antes
de que los cuadros oficiales se refresquen. Apuesta razonable: los XLSX
saltarán a "1990-2025" entre julio-octubre 2026 (patrón histórico).
**No es bug** del ingest — el lag es del INE, no nuestro. Si en algún
momento se decide ingerir las cifras de las notas PDF, sería un alcance
nuevo (PDF table extraction, no XLSX).

### Audit folder

`/opt/binance_p2p/ine_audit/{pib,ipc,ipp}/<cuadro_id>_<release_id>.xlsx`.
Rotación 60 días (vs 7 de EMBI — los releases INE son infrecuentes).
Namespaceo obligatorio por familia y por cuadro_id porque INE reusa el
filename `01.01.01.xlsx` para PIB Trimestral Y PIB Anual con contenido
distinto.

### Healthchecks

- `HC_INE_PIB` y `HC_INE_IPC` — UUIDs en `healthchecks.io`, leídos como env
  vars del crontab. Si la env var falta, el script loguea warning y sigue
  (no aborta). Cubre `start` / éxito (con body resumen) / `fail` con
  stacktrace.
- Diferencia vs EMBI: el HC_EMBI quedó sin registrar por mucho tiempo —
  para INE el ping se cablea desde el día 1, pero arranca solo cuando los
  UUIDs estén en el entorno (no requiere re-deploy).

### Hosts y fallback

Los share tokens del INE en general resuelven en ambos hosts (`nimbus` y
`nube`). El fetch primero prueba el host primario declarado en
`config.INE_CUADROS`; si devuelve 4xx/5xx, prueba el secundario con el
mismo token. Si ambos fallan → error claro.

### Pendientes / TODO

- **Re-scrape del hub HTML como fallback** cuando el token rota
  (`bs4` + `lxml` pendientes de instalar en VPS). No bloquea V1 — el HC
  alerta si un cuadro 404ea.
- **Frontend (tab Macro / sub-toggles PIB / IPC / etc)**: no se toca en V1
  del backend. Diseño separado (megarun siguiente).
- **Threshold de detección de release para PIB**: hoy siempre descarga el
  XLSX para comparar MD5. Si el ancho de banda llegara a ser problema, se
  puede agregar HEAD con `Range: bytes=0-0` + comparación de
  `Content-Length` (cambio implica contenido nuevo).

---

## 9. Módulo ASFI — Hechos Relevantes del Mercado de Valores

**Qué es.** Cada día hábil la Dirección de Supervisión de Valores de ASFI
publica un "Reporte Informativo" (PDF, 7-9 págs) con los hechos relevantes del
RMV: comunicados de emisores/agencias/SAFIs (juntas, personal, préstamos),
pagos de cupones, compromisos financieros de bancos emisores (CAP/liquidez),
calificaciones de riesgo, resoluciones (emisiones autorizadas) y cartas.
La ruta `finanzasbo.com/asfi` lo muestra condensado, navegable por día o rango.

**Restricción de red (crítica).** El listado y los PDFs viven en
`appweb2.asfi.gob.bo` (app ASP.NET aparte del Drupal `www.asfi.gob.bo`), que
**geo-bloquea a nivel de red toda IP no boliviana** (validado 2026-07-05:
directo desde Hetzner = connect timeout; DataImpulse exit default = 502 del
gateway; DataImpulse con sufijo `__cr.bo` en el usuario = 200 vía exit
residencial La Paz/Cobija). `asfi_ingest/fetch.py` deriva el proxy BO del
mismo `PROXY_URL` del `.env` (PR #146) — sin tocar el flujo de noticias.
El `www` (Drupal/CDN) sí acepta cualquier IP, pero solo tiene el iframe.

**Piezas.**
| Pieza | Qué hace |
|---|---|
| `asfi_ingest/parser.py` | PDF → items `{seccion, categoria, entidad, texto, tags}`. Clasificación por fuente bold (visitor pypdf) + vocabulario fijo de secciones/categorías + heurísticas anti-tabla (las tablas de calificadoras/compromisos también usan bold). Tags por keywords (emision/cupon/personal/junta/…). Validado contra los 122 reportes ene–jul 2026: 0 fallas, ~26 items/día. |
| `asfi_ingest/fetch.py` | Listado (`Gestion=YYYY`) + PDFs vía proxy `__cr.bo`, con reintentos (el pool rota exit y puede dar 502 transitorio). Fail-safe sin `PROXY_URL`. |
| `asfi_ingest/resumen.py` | Titular telegráfico IA (Haiku, ≤90 chars estilo cable — prompt V2, `RESUMEN_V` versiona: `aplicar()` re-procesa solo items de versión vieja, bajo el cap). Mismo contrato que `resumen_ia.py`: candado `autorizado=True` + cap mensual propio en tabla `asfi_api_spend` (self-create; default $1/mes, decisión Diego: SIN override). Fallback extractivo = origen B con asterisco (taxonomía A/B). `ASFI_RESUMEN=0` lo apaga sin tocar noticias. |
| `ingest_asfi.py` | Orquestador. Default = corrida diaria de cron (dedupe por FECHA del título del listado — robusto entre backfill sin guid y cron con guid). `--backfill DIR` parsea PDFs locales. `--resumir` re-pasa la IA sobre items no-A (idempotente, cap-bounded — backfill de resúmenes en tandas). `--sin-ia`. |
| `asfi_ingest/extract.py` | Conserva `grupo` + `campos` V3 como compatibilidad y, en la rama `feat/asfi-taxonomy-v4`, llama a la capa V4. `ingest_asfi.py --reextraer` recomputa sobre la data existente; **no ejecutar para V4 hasta autorización expresa de Diego**. |
| `asfi_ingest/taxonomy_v4.py` | Taxonomía V4 propuesta local: 17 tipos visibles, 120 subtipos con clave estable `type_id.subtype_id`, un evento dominante, eventos secundarios, tags, campos estructurados y contrato de tabla fuente. Integra financiamiento bancario/no bancario en el único tipo `financiamiento`. No usa red, API ni IA. |
| `static/asfi_YYYY-MM.json` + `static/asfi_index.json` | Data committeada al repo (patrón data-BCB). `publish_dashboard.py` ya copia los archivos sueltos de `static/` a la raíz de `gh-pages` (y de ahí suben al edge Cloudflare Pages en el mismo dual-publish) — la publicación sale gratis en el ciclo normal (*/12). |
| Tab "ASFI" del SPA (`template.html` + `static/asfi-taxonomy-v4-ui.js`) | Frontend V4 local, todavía no publicado: tipo organiza; subtipo divide tablas por rango; día muestra subtipo por fila. Filtros de tipo/subtipo múltiple, búsqueda que incluye eventos/tags, conteos dinámicos, orden y hash compartible sin perder fechas. Tablas anchas viven solo dentro de `.table-scroll`; el detalle rotula los datos estructurados y el estado de tabla fuente. |
| `scripts/asfi_v4_dry_run.py` | Pase in-memory sobre 30.267 items, conciliación contra Fase 1, auditorías 509/488/2.972, residual anual, muestras estratificadas y guard de hashes de JSON productivos. Solo escribe diagnóstico en `tmp/`. |
| `scripts/build_asfi_v4_preview.py` | Genera bajo `tmp/` un bake local con copias enriquecidas; nunca modifica `static/` ni publica. |
| `scripts/test_asfi_parser.py`, `scripts/test_asfi_taxonomy_v4.py`, `scripts/test_asfi_v4_ui_contract.py` | Parser y regresión V4: catálogo, precedencias, casos de aceptación, corpus completo, filtros/URL/estados de tabla y contrato responsive. |

**Nota operativa reextraer.** El procedimiento histórico sigue siendo
`.venv/bin/python ingest_asfi.py --reextraer` + wrapper, pero para V4 queda
bloqueado por el gate de Fase 2A. Primero revisar el diagnóstico dry-run y la
preview; solo una autorización posterior de Diego habilita persistir JSON,
committear datos regenerados y publicar. Ver `docs/asfi_taxonomy_v4.md`.

**Estado de publicación.** El módulo ASFI V3, sus dependencias y sus cron ya
están desplegados (ver § 0 y tabla de cron). La taxonomía/frontend **V4 de esta
rama no está publicada**, no fue persistida en los JSON y no debe describirse
como productiva. Sigue pendiente únicamente el gate de Diego para Fase 2A y,
por separado, el UUID opcional `HC_ASFI`.

**Gasto API.** Autorizado por Diego (sesión 2026-07-05, brief del módulo:
elección explícita "Extracción + resumen IA"). Cap confirmado por Diego en la
misma sesión: **$1/mes, default del código, SIN override** (`ASFI_RESUMEN_CAP_USD`
no debe estar en el `.env`). Techo total de IA del sitio = noticias $1 + ASFI $1
= $2/mes. Corrida diaria ≈ 26 items ≈ $0.03/día — entra cómoda bajo el $1.
