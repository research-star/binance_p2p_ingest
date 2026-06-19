-- 0005_noticias_clasificacion_v1.sql — Clasificación v1 + carril (FASE 3).
-- Aplicar a mano en el VPS (VPS-write, lo gatea Diego tras el merge):
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0005_noticias_clasificacion_v1.sql
--
-- Columnas aditivas y nullables:
--   carril     'bolivia'|'latam' — carril del feed. Antes el carril Latam era
--              implícito en category=='latam'; ahora category se colapsó a
--              {economia,politica} (Capa 2) y el carril vive en su propia col.
--   tema_hits  INTEGER — confianza del tema (clasificación v1, Capa 1):
--              strong*10 + weak-con-contexto. Gate sugerido: imagen específica
--              si tema_hits >= 10. Filas legacy quedan NULL (sin re-scrapear).
--   entidades  TEXT — JSON array de entidades canónicas (BCB, YPFB, YLB, FMI…).
--              Filas legacy quedan NULL → dashboard lo lee como '[]'.
--
-- NO es idempotente: SQLite no soporta ADD COLUMN IF NOT EXISTS, así que
-- re-aplicar (o aplicar tras el self-migrate de ingest/dashboard) tira
-- "duplicate column name" — INOCUO: el cliente sqlite3 reporta el error y SIGUE
-- con las sentencias siguientes (el UPDATE de backfill corre igual). La inertness
-- del build NO depende de aplicar esta migración antes del merge: ingest_noticias
-- (init_schema) y dashboard.py self-migran estas columnas en runtime. Mergear a
-- main no la crea en el VPS.

ALTER TABLE noticias ADD COLUMN carril TEXT;
ALTER TABLE noticias ADD COLUMN tema_hits INTEGER;
ALTER TABLE noticias ADD COLUMN entidades TEXT;

-- Backfill de filas legacy (carril NULL): deriva el carril de la category vieja.
-- Idempotente (solo toca NULLs). Las filas nuevas ya traen carril del código.
-- tema_hits/entidades NO se backfillean (requeriría re-clasificar): quedan NULL.
UPDATE noticias
   SET carril = CASE WHEN category = 'latam' THEN 'latam' ELSE 'bolivia' END
 WHERE carril IS NULL;
