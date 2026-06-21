-- 0006_noticias_tambien_en.sql — Columna tambien_en ("También en…", calibración 2026-06-21).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0006_noticias_tambien_en.sql
--
-- Columna aditiva y nullable:
--   tambien_en  TEXT — JSON array [{source, portal, url}] de los OTROS medios que
--               cubrieron el mismo evento. La nota visible es la REPRESENTANTE del
--               grupo (elegida por tier de fuente: oficiales/gremios T1 > grandes
--               T2 > resto T3); las demás se listan en el feed como "También en: …".
--               El agrupamiento por evento corre en ingest_noticias.agrupar_eventos.
--               Filas legacy quedan NULL → dashboard lo lee como [] (sin "También en").
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que re-aplicar
-- (o aplicar tras el self-migrate de ingest/dashboard) tira "duplicate column name"
-- — INOCUO: el cliente sqlite3 reporta el error y sigue. La inertness del build NO
-- depende de aplicar esta migración antes del merge: ingest_noticias (init_schema) y
-- dashboard.py self-migran esta columna en runtime. Mergear a main no la crea en el VPS.

ALTER TABLE noticias ADD COLUMN tambien_en TEXT;
