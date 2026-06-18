-- 0004_noticias_image_url.sql — og:image real de la nota (carril Bolivia, FASE 2a).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0004_noticias_image_url.sql
--
-- ADD COLUMN aditivo y nullable: distinto de `url` (link al artículo). Guarda la URL
-- del og:image hotlinkeable (img src directo, sin re-host). NULL cuando el portal no
-- expone og:image o no baja HTML (El Deber → placeholder). Las filas viejas quedan en
-- NULL (no hay backfill). Latam = FASE 2b: sus filas también quedan NULL.
-- Escribe: scraper.py/transform.py (fase cuerpo, carril BO). Lee: dashboard.py.
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que re-aplicar
-- tira "duplicate column name: image_url" (inocuo — la columna ya está). La inertness
-- del build NO depende de aplicar esta migración antes del merge: dashboard.py hace el
-- mismo ALTER defensivo en runtime (self-migrate, traga el duplicate-column), igual que
-- el self-create de noticias_hidden de 0003. Mergear a main no la crea en el VPS.

ALTER TABLE noticias ADD COLUMN image_url TEXT;
