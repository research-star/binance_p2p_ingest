# HANDOFF.md — Estado detallado del proyecto

Última actualización: 2026-04-22

---

## Fase 1: Ingesta cruda

**Estado:** ✅ Completa y funcionando.

- `ingest.py` captura snapshots completos (BUY + SELL) del libro P2P USDT/BOB.
- Guarda JSON crudo gzipeado en `snapshots/YYYY-MM-DD/`.
- **~640 snapshots acumulados** (10–15 abr 2026), cadencia ~10 min.
- Modos: una captura, `--loop` (cada 10 min), `--dry-run`.
- **Watchdog:** `watchdog.py` chequea cada 5 min si el loop sigue vivo
  (último snapshot <15 min) y lo relanza si murió. Configurable vía Windows
  Task Scheduler con `watchdog.bat` (instrucciones en README).
- Corre en local por ahora. Hosting pendiente.

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

**Estado:** 🟢 Sustancialmente construida, dashboard funcional (~587 KB).
Publicado en GitHub Pages.

`dashboard.py` genera `index.html` autocontenido con Plotly.js (más un alias
`p2p_dashboard.html` local por compatibilidad, no trackeado).
Todo se recalcula desde `p2p_normalized.db`. Opcional `--csv` para exportar
métricas por snapshot.

### Métricas / Paneles implementados

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

- **Toggle temporal:** Por hora / Por día / Cada snapshot. Cada vista usa el
  último snapshot de cada período.
- **Sistema de temas:** 5 presets en la barra (Claro, Beige, Oscuro + Otros con
  Negro/ink) + temas custom guardables (import/export JSON, máx 5).
- **Paneles movibles y redimensionables:** drag & drop entre posiciones,
  toggle ancho completo/medio, layout persiste en `localStorage`.
- **Interacción Plotly:** drag-to-pan, scroll zoom, rangeslider en gráficos
  temporales, hover mode `x unified`.
- **BCB referencial (`bcb_referencial.py`):** scraper del SVG del BCB
  (/valor_referencial_compra_svg.php y venta_svg.php). Acumula histórico
  diario en `bcb_referencial.json`. Se muestra como KPI nuevo
  "TC Referencial BCB" y como serie temporal punteada en el VWAP (interpola
  entre días publicados).
- **3 líneas de referencia toggleables** en leyenda del VWAP: BCB oficial
  (6.96), BCB Ref Compra, BCB Ref Venta. Desactivadas por defecto.

---

## Archivos del proyecto

| Archivo | Rol |
|---|---|
| `ingest.py` | Captura snapshots del libro P2P |
| `normalize.py` | Aplanar snapshots a SQLite |
| `dashboard.py` | Generar HTML autocontenido |
| `bcb_referencial.py` | Scraper del valor referencial BCB |
| `watchdog.py` | Relanzar loop de ingesta si se cae |
| `update.bat` | Pipeline: bcb → normalize → dashboard |
| `sync_snapshots.bat` | `robocopy /MIR` snapshots → `$P2P_BACKUP_DIR` |
| `watchdog.bat` | Wrapper para Task Scheduler |
| `p2p_normalized.db` | SQLite generado (reconstruible, no trackeado) |
| `bcb_referencial.json` | Histórico acumulado del BCB (sí trackeado) |
| `index.html` | Dashboard final (regenerado por update.bat, servido por GitHub Pages) |

---

## Pendientes

- [ ] **Hosting de la ingesta** (Oracle Free vs Hetzner €4/mes) — postpuesto,
      el loop corre en local con watchdog.
- [x] **GitHub Pages** — publicado. `index.html` se sirve desde `main` /root.
      Remote: `github.com/research-star/binance_p2p_ingest`.
- [x] **Repo Git + `.gitignore`** — inicializado. Historial saneado con
      `git filter-repo` (sin datos personales).
- [ ] **VWAP alternativo con `maxSingleTransAmount`** — postpuesto a final.
- [ ] **Análisis de reacción a eventos macro** (feriados, anuncios BCB,
      quincenas de pago, etc.).
- [ ] Limpiar carpeta `.json` espuria en `snapshots/2026-04-09/`.
