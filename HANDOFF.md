# HANDOFF.md — Estado detallado del proyecto

Última actualización: 2026-04-27

---

## Fase 1: Ingesta cruda

**Estado:** ✅ Completa y funcionando.

- `ingest.py` captura snapshots completos (BUY + SELL) del libro P2P USDT/BOB.
- Guarda JSON crudo gzipeado en `snapshots/YYYY-MM-DD/`.
- **~1,500 snapshots acumulados** (9 abr → 27 abr 2026), cadencia ~10 min.
  Días recientes: 138/día (cobertura ~96% del esperado, gap mínimo por jitter).
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
| `watchdog.py` | Relanzar loop de ingesta si se cae |
| `update.bat` | Pipeline: bcb → normalize → dashboard (con `PYTHONIOENCODING=utf-8`) |
| `sync_snapshots.bat` | `robocopy /MIR` snapshots → `$P2P_BACKUP_DIR` |
| `watchdog.bat` | Wrapper para Task Scheduler (no usado actualmente: la tarea corre `pythonw.exe watchdog.py` directo) |
| `p2p_normalized.db` | SQLite generado (reconstruible, no trackeado) |
| `bcb_referencial.json` | Histórico acumulado del BCB (sí trackeado, ~106 entradas) |
| `index.html` | Dashboard final (regenerado por update.bat, servido por GitHub Pages) |

---

## Operación diaria

1. **`ingest.py --loop`** corre 24/7 en background.
2. **Watchdog** (Task Scheduler "P2P Watchdog", cada 5 min) lo relanza si cae.
3. Para refrescar el dashboard publicado: `update.bat` + `git add . && git commit -m "..." && git push`.
   - El push gatilla rebuild de GitHub Pages (~30-60s).
   - Pages a veces deja deployments atascados — se desbloquean marcándolos
     `inactive` vía API y empujando un commit nuevo.

---

## Auditoría pendiente (2026-04-27)

Hallazgos detectados, sin corregir todavía. Prioridades sugeridas:

**Alta** (rompen coherencia visual):
- Mezcla **BUY/SELL en inglés** dentro de un dashboard español: legendas de
  Volatilidad, Merchants activos, Ratio, Spread (descripción), sub-headers de
  Merchants principales. Debería ser Compra/Venta consistente.
- KPIs ambiguos: "Asimetría 1.6× → más oferta que demanda" (interpretativo,
  no informativo); "TC Referencial BCB X.XX" no aclara que es venta;
  "prima paralela +X%" sin contexto de qué vs qué.

**Media** (usabilidad directa):
- Headers de tabla **Merchants principales** crípticos: `USDT`, `%`, `VWAP`,
  `Trades/mes` — sin unidad ni contexto. Debería ser `Profundidad (USDT)`,
  `% del lado`, `VWAP (BOB)`, `Órdenes/mes`.
- Falta unidad en ejes Y de VWAP, Profundidad, Ratio.
- Tooltips Plotly no muestran unidades (depende de `hovertemplate` explícito).

**Baja** (pulido):
- Capitalización inconsistente ("Por día" vs "por día").
- Decimales mixtos (4 en gráficos, 2 en KPIs).
- Descripción de Curva de deciles perdió la frase "tijera = anuncios trampa".

---

## Pendientes

- [ ] **Hosting de la ingesta** (Oracle Free vs Hetzner €4/mes) — postpuesto,
      el loop corre en local con watchdog estable.
- [x] **GitHub Pages** — publicado en `research-star.github.io/binance_p2p_ingest/`.
- [x] **Repo Git + `.gitignore`** — inicializado. Historial saneado con
      `git filter-repo` (sin datos personales).
- [x] **Watchdog operativo** — Task Scheduler corriendo cada 5 min.
- [x] **Histórico BCB compra+venta scrapeado** — 106 días reales del BCB.
- [ ] **Auditoría visual** — corregir hallazgos (ver sección anterior).
- [ ] **VWAP alternativo con `maxSingleTransAmount`** — postpuesto a final.
- [ ] **Análisis de reacción a eventos macro** (feriados, anuncios BCB,
      quincenas de pago, etc.).
- [ ] **Automatizar `update.bat` + push** vía Task Scheduler (cada N horas)
      para que Pages se refresque sin intervención manual.
- [ ] Limpiar carpeta `.json` espuria en `snapshots/2026-04-09/`.
