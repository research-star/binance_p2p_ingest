-- 0008_noticias_reresumen.sql — Soporte del mecanismo de re-resumen B→A.
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0008_noticias_reresumen.sql
--
-- Columnas aditivas y nullables:
--   extract_len        INTEGER — longitud (chars) del cuerpo/insumo que produjo el
--                      summary actual. La usa reresumir_pendientes para decidir si un
--                      re-fetch trajo cuerpo MATERIALMENTE más largo (vale re-llamar IA).
--                      NULL legacy = 0 (cualquier cuerpo nuevo cuenta como mejor).
--   resumen_reintentos INTEGER — nº de pasadas de re-resumen sobre la nota. Frena el
--                      bucle: tras el cap por nota deja de ser candidata (El Deber, cuyo
--                      cuerpo no baja por el WAF, topa sin quemar API). NULL legacy = 0.
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que re-aplicar
-- (o aplicar tras el self-migrate de ingest/dashboard) tira "duplicate column name"
-- — INOCUO: el cliente sqlite3 reporta el error y sigue. La inertness del build NO
-- depende de aplicar esta migración antes del merge: ingest_noticias (init_schema) y
-- dashboard.py self-migran estas columnas en runtime. Mergear a main no las crea en el VPS.

ALTER TABLE noticias ADD COLUMN extract_len INTEGER;
ALTER TABLE noticias ADD COLUMN resumen_reintentos INTEGER;
