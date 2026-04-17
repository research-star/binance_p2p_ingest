# HANDOFF.md — Estado detallado del proyecto

Última actualización: 2026-04-10

---

## Fase 1: Ingesta cruda

**Estado:** ✅ Completa y funcionando.

- `ingest.py` captura snapshots completos (BUY + SELL) del libro P2P USDT/BOB.
- Guarda JSON crudo gzipeado en `snapshots/YYYY-MM-DD/`.
- Primer snapshot real: 2026-04-09, 482 anuncios (170 BUY + 309 SELL), 68.7 KB, 0 errores.
- 13 snapshots acumulados (9 abr + 10 abr), corriendo cada 10 min en local.
- Modos: una captura, `--loop` (cada 10 min), `--dry-run`.
- Corre en local por ahora. Hosting pendiente.

---

## Fase 2: Normalización

**Estado:** ✅ Completa (2026-04-10).

`normalize.py` lee snapshots crudos y produce `p2p_normalized.db` (SQLite).
1 fila = 1 anuncio en 1 snapshot. PK: `(snapshot_ts_utc, side, adv_no)`.
Idempotente. Exporta CSV opcional con `--export-csv`.

### Aplanado base ✅

- 13 snapshots procesados, ~5,700 filas en DB.
- BUY: ~160-193 ads/snapshot, precio [9.28 – 20.73], depth ~1.3-2.3M USDT
- SELL: ~231-309 ads/snapshot, precio [6.50 – 9.33], depth ~3.6-5.8M USDT
- Merchants: ~65% | Users: ~35%

### quality_tier (A/B/C) ✅

- **Tier A:** merchant + ≥100 órdenes/mes + ≥95% completado + ≥500 USDT surplus → 50%
- **Tier B:** merchant que no llega a A, o user con ≥20 órdenes/mes → 27%
- **Tier C:** todo lo demás → 23%
- Cortes aceptados. Calibrados con data real boliviana.

### banks como tags ✅

- Bancos extraídos de `tradeMethods`, guardados como JSON array + `n_banks`.

### Restricciones estructuradas al taker ✅

- Confirmado: **0 en 5,707 registros**. Ningún anuncio boliviano usa campos de restricción estructurada.

### KYC keywords en remarks/auto_reply ✅

- Confirmado: **0 en 5,707 registros**. Bolivia no usa estos campos.

### Validación y sanity checks ✅

- Sin nulls en price/surplus. Índices en ts, side, advertiser, price.

### Pendientes no-bloqueantes (se resuelven en Fase 3 si hacen falta)

- `minSingleTransAmount` como flag en VWAP → decisión: ignorar en métrica principal.
- VWAP alternativo usando `maxSingleTransAmount` → postpuesto a final del proyecto.

---

## Fase 3: Análisis

**Estado:** 🔄 Iniciada (2026-04-10).

`dashboard.py` genera un HTML autocontenido (`p2p_dashboard.html`) con Plotly
desde `p2p_normalized.db`. Se abre en cualquier navegador. Opción `--csv` para
exportar métricas tabuladas.

### Métricas incluidas

- **VWAP por profundidad** (5% / 10% / 25% / 50%) — BUY y SELL con bandas
- **Spread efectivo** a cada nivel de profundidad
- **Profundidad por lado** — USDT totales en BUY vs SELL
- **Curva de precio por decil** (tijera) — evidencia anuncios trampa en la cola
- **Ratio SELL/BUY** — asimetría de oferta/demanda
- **Concentración top-5** — % de profundidad controlado por los 5 mayores
- **Cobertura por banco** — anuncios y profundidad por método de pago
- **KPIs de cabecera** — VWAP 10% ambos lados, spread, profundidad, asimetría, prima vs BCB

---

## Decisiones pendientes

- **Hosting:** Oracle Free Tier vs Hetzner €4/mes. Acumular unos días de data local primero.
- **Carpeta .json espuria:** En `snapshots/2026-04-09/` hay un snapshot descomprimido manualmente dentro de una carpeta `.json`. No afecta (normalize deduplica), pero conviene limpiarla.

---

## TODO acumulados

- [ ] Decidir hosting y automatizar ingesta
- [ ] Iniciar repo Git + .gitignore
- [ ] Limpiar carpeta .json espuria en snapshots/
- [ ] Fase 3: iterar dashboard (filtros por tier, rango de fechas, etc.)
