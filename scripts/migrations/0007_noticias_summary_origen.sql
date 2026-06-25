-- 0007_noticias_summary_origen.sql — Origen del summary (IA vs extractivo).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0007_noticias_summary_origen.sql
--
-- Columna aditiva y nullable:
--   summary_origen  TEXT — 'ia' si el summary lo generó resumen_ia.py (Claude
--                   Haiku); 'extractivo' si es el extracto del cuerpo/descripción
--                   (transform._resumen_extractivo, fallback cuando la IA no corre
--                   o degrada a None). El frontend marca con asterisco todo lo que
--                   NO sea 'ia'. Filas legacy quedan NULL → el dashboard/frontend
--                   lo tratan como 'extractivo' (con asterisco), sin re-resumir.
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que re-aplicar
-- (o aplicar tras el self-migrate de ingest/dashboard) tira "duplicate column name"
-- — INOCUO: el cliente sqlite3 reporta el error y sigue. La inertness del build NO
-- depende de aplicar esta migración antes del merge: ingest_noticias (init_schema) y
-- dashboard.py self-migran esta columna en runtime. Mergear a main no la crea en el VPS.

ALTER TABLE noticias ADD COLUMN summary_origen TEXT;
