-- 0009_api_spend.sql — Contador de gasto API mensual (cap de runaway de Haiku).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0009_api_spend.sql
--
-- Tabla nueva (no es ALTER): acumula el gasto estimado de resumen_ia.py por mes
-- UTC. La lee el cap (2ª condición de aborto en resumir(): si est_usd del mes
-- corriente >= CAP_USD_MENSUAL → NO se hace el POST, degrada a extractivo) y la
-- escribe la captura de usage tras cada POST exitoso (en la MISMA transacción que
-- persiste la nota → atómico con el commit por nota).
--
--   mes         TEXT PK 'YYYY-MM' — partición mensual en UTC (matchea cron/logs).
--   est_usd     REAL — costo estimado acumulado ($1/MTok in + $5/MTok out, Haiku 4.5).
--   llamadas    INTEGER — nº de POSTs facturados (incluye respuestas INSUFICIENTE).
--   in_tokens   INTEGER — input_tokens acumulados (data["usage"]).
--   out_tokens  INTEGER — output_tokens acumulados.
--
-- IDEMPOTENTE (a diferencia de 0007/0008): CREATE TABLE IF NOT EXISTS no falla al
-- re-aplicar. Igual NO depende de aplicar esto antes del merge: resumen_ia.init_spend_schema
-- (lo invoca ingest_noticias.init_schema en cada corrida) la self-crea en runtime.
-- Sin la tabla, la lectura del cap fail-closed bloquearía TODO resumen en prod →
-- por eso se autocrea (mismo patrón self-apply que el column-migrate de 0005+).

CREATE TABLE IF NOT EXISTS api_spend (
    mes         TEXT PRIMARY KEY,
    est_usd     REAL    NOT NULL DEFAULT 0,
    llamadas    INTEGER NOT NULL DEFAULT 0,
    in_tokens   INTEGER NOT NULL DEFAULT 0,
    out_tokens  INTEGER NOT NULL DEFAULT 0
);
