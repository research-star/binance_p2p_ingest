-- 0005_noticias_clasificacion_v1.sql — Clasificación v1 + carril (FASE 3).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0005_noticias_clasificacion_v1.sql
--
-- Columnas aditivas y nullables:
--   carril     'bolivia'|'latam' — carril del feed. Antes el carril Latam era
--              implícito en category=='latam'; ahora category se colapsó a
--              {economia,politica} (Capa 2) y el carril vive en su propia col.
--   (Capa 1 agrega tema_hits + entidades más abajo.)
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que
-- re-aplicar (o aplicar tras el self-migrate de ingest/dashboard) tira
-- "duplicate column name" — INOCUO: el cliente sqlite3 reporta el error y SIGUE
-- con las sentencias siguientes (el UPDATE de backfill corre igual). La inertness
-- del build NO depende de aplicar esta migración antes del merge: ingest_noticias
-- (init_schema) y dashboard.py self-migran estas columnas en runtime. Mergear a
-- main no la crea en el VPS.

ALTER TABLE noticias ADD COLUMN carril TEXT;

-- Backfill de filas legacy (carril NULL): deriva el carril de la category vieja.
-- Idempotente (solo toca NULLs). Las filas nuevas ya traen carril del código.
UPDATE noticias
   SET carril = CASE WHEN category = 'latam' THEN 'latam' ELSE 'bolivia' END
 WHERE carril IS NULL;
