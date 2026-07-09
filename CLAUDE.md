# CLAUDE.md — FinanzasBo

Plataforma de inteligencia económica de Bolivia. El USDT/BOB es un módulo entre varios (P2P, BCB oficial, riesgo país/EMBI, DPF, BBV, inflación IPC/IPP, feed de noticias). Pipeline de ingesta multi-fuente (Binance P2P + BCB + INE + EMBI + portales de noticias); publicación automática en finanzasbo.com.

## Source of truth

Este archivo describe el proyecto y sus convenciones — el "qué" y el "cómo se trabaja". Para estado vivo, topología y reglas operativas, leer `HANDOFF.md`. Para contexto histórico (cutover Hetzner, decisiones cerradas), `docs/history.md`. Para runbook backups, `docs/backups.md`.

## Filosofía técnica

- **No filtrar en origen.** Ingerimos todo el universo P2P y aplicamos quality_tier en normalización. Las decisiones de filtrado se pueden cambiar sin re-scrapear.
- **Banco como tag, no filtro.** El campo `bank` etiqueta, no decide quién entra. El consumidor decide.
- **Separación estricta de fases.** Ingesta → Normalización → Análisis. Cada fase tiene su responsabilidad, sus archivos, sus tests.
- **Huecos visibles, no rellenados.** Si un día falta data, se ve. No interpolamos silenciosamente.
- **Calibración con data real boliviana.** Las decisiones de diseño se validan contra el comportamiento del mercado local, no patrones genéricos.

## Resúmenes de noticias (taxonomía A/B/C)

Cada nota lleva un `summary` con un origen (`summary_origen`, migración 0007):

- **A = `'ia'`** — resumen generado por `resumen_ia.py` (Claude Haiku) sobre el cuerpo
  scrapeado. Estado deseado; el frontend NO le pone asterisco.
- **B = `'extractivo'`** — extracto del cuerpo/RSS (`transform._resumen_extractivo`),
  fallback cuando la IA degrada (INSUFICIENTE/rechazo) o no corre. El frontend lo marca con `*`.
- **C = colapso de render** — el dek queda vacío porque `summary ≈ título` (`ntDek` lo
  descarta) y `.np-card-dek:empty` colapsa. **NO es un estado de DB**: no hay columna ni
  migración para C; toda fila tiene `summary`/`detail` no vacíos. C es un outcome del render.

**Re-resumen B→A** (`ingest_noticias.reresumir_pendientes`): cada corrida del cron re-fetchea
el cuerpo de las notas no-A de HOY (carril Bolivia) y, con un **pre-gate de suficiencia** antes
de tocar la API, re-llama a la IA **solo si** el cuerpo nuevo (1) es más largo que el que produjo
el summary actual (`extract_len`, migración 0008) **y** (2) supera el piso absoluto
`UMBRAL_SUFICIENCIA` (~230, calibrado al detail mínimo de una A), para promover B→A. Cap por
corrida + por nota (`resumen_reintentos`, 0008)
para acotar gasto y frenar el bucle (El Deber, cuyo cuerpo no baja por WAF, topa sin quemar
API). El gasto API del re-resumen está gateado por el candado (`autorizado=True`) +
autorización de Diego en el brief (ver `CLAUDE.local.md` § Candado de gasto de API).

## Convenciones del repo

**Naming de branches**: `feat/...`, `fix/...`, `docs/...`, `chore/...`, `refactor/...`.

**Convención de commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. Data autocommiteada por VPS usa `chore(bcb):`.

**PR vs push directo**:
- **PR obligatorio** para features, refactors, fixes sustantivos, `template.html`, `dashboard.py`.
- **Push directo aceptable** para data BCB (autocommiteada), docs cortos, scripts temporales, workflow init via UI de GitHub.

**Convención recomendada**: si hay otro colaborador con PR abierto sobre archivos que toca tu trabajo, conviene coordinar antes de mergear. No es regla rígida — los colaboradores la manejan entre ellos.

**Verificación post-deploy**: tras merge a `main`, `finanzasbo.com` sirve desde el edge **Cloudflare Pages** (cutover 2026-07-06; el dual-publish sigue pusheando a `gh-pages`, que queda como carril de push + fallback caliente). La fuente de verdad de frescura es el **raw de `gh-pages`** (sin CDN delante) — NO `finanzasbo.com` directo, porque el edge cachea y puede servir HTML viejo (eso NO es deploy roto). Verificá contra el raw de `gh-pages`, o el edge con cache-buster nanosegundo + headers `no-cache`. `meta.generated_at` debe ser posterior al `mergedAt` del PR. Detalle y comandos: `HANDOFF.md` § Verificación post-deploy.

**Schema SQLite en DOS lugares**: `scripts/migrations/` NO es el schema canónico completo. Solo declara las tablas INE/noticias/gasto (`0001`–`0009`); el resto se crea **en runtime** por el script que las usa (`CREATE TABLE IF NOT EXISTS` al arrancar): `ads`/`normalize_state` (`normalize.py`), `embi_spreads` (`ingest_embi.py`), `bcb_dpf_rates` (`ingest_bcb_dpf.py`), `ine_ipc_comunicado` (`ingest_ine_comunicado.py`, sin `.sql`), `urls_vistas` (`scraper.py`, en `cache_urls.db`), `asfi_api_spend` (`asfi_ingest/resumen.py`). **Al tocar schema, verificar AMBOS lugares** (migrations/ y el `CREATE TABLE` del script). Partición completa: `HANDOFF.md` § Schema SQLite.

## Política de merge

- CC (Claude Code) **nunca mergea por iniciativa propia**: abre el PR y frena.
- Merge por CC **solo** con un brief que lo autorice explícitamente para ese PR.
- Mecánica autorizada: **merge commit** (`gh pr merge N --merge`), sin squash
  ni rebase; branch borrada post-merge (`--delete-branch`).
- Verificación obligatoria: `gh pr view N --json state,mergedAt` debe devolver
  `MERGED` + timestamp.

## Anti-patrones del proyecto

- NO tocar `p2p_normalized.db.pre-migration-*` (snapshots de rollback del cutover Hetzner).
- NO usar `git add -A` ni `git add .` — agregar archivos por nombre.
- NO bypassar hooks (`--no-verify`) ni firmas.
- NO commitear **cambios** fuera del alcance del brief que estás ejecutando.
  La unidad es el cambio, no el archivo: tocar un archivo listado no autoriza
  cualquier edición dentro de él. Cambio adyacente solo si evita shippear algo
  que el cambio principal vuelve falso (docs, copy de UI, contadores), y se
  reporta como decisión propia (precedente: entrada de la Guía en PR #48).
- NO modificar este `CLAUDE.md`, `HANDOFF.md`, ni `docs/*` sin un brief
  explícito que lo pida. **Excepción**: los briefs de implementación incluyen
  por regla actualizar las secciones de `HANDOFF.md` que el cambio vuelva
  falsas — el brief de implementación ES la autorización para ese
  mantenimiento (no hace falta brief aparte).
- NO ejecutar comandos destructivos (`rm -rf`, `git reset --hard`, force-push) sin confirmar.

## Referencias canónicas (orden de prioridad)

1. `HANDOFF.md` — estado vivo, reglas operativas, topología VPS, pendientes abiertos. **Al inicio de cualquier ticket: §0 (estado vivo) y §1 (reglas) siempre; del resto, las secciones que toque el scope del ticket.** Leerlo completo solo cuando el ticket lo amerite (cambios transversales, onboarding).
2. `docs/history.md` — contexto histórico (cutover, gotchas resueltos, decisiones cerradas).
3. `docs/backups.md` — runbook backup laptop-pull.
4. `README.md` — setup público, deploy Pages.
5. Código fuente — `ingest.py`, `normalize.py`, `dashboard.py`, `template.html`, `config.py`. Último recurso para resolver ambigüedades.
