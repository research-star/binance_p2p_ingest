-- 0003_noticias_hidden.sql — Mirror/cache de ids de noticias ocultas.
-- Idempotente. Aplicar a mano en el VPS:
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0003_noticias_hidden.sql
-- Fuente canónica del schema. En runtime, dashboard.py hace el mismo CREATE TABLE
-- IF NOT EXISTS antes de leer noticias (self-create), así que la inertness NO
-- depende de aplicar esta migración antes del merge (no hay runner; mergear a main
-- no la crea en el VPS).
--
-- Fuente de verdad de los ocultos = KV de Cloudflare (PR-B). Esta tabla es solo un
-- cache local de ids para el filtro de build: dashboard.py excluye estos ids del
-- feed. Por eso solo guarda `id` — la metadata rica (quién/cuándo) vive en KV.
-- `id` = MD5(url_normalizado)[:16] (mismo TEXT PK que `noticias.id`; nunca se
-- recomputa el hash, se referencia el id ya persistido).
--
-- Escribe: sync de la mirror desde KV (PR de red, posterior) + self-create de
--   dashboard.py. Lee: dashboard.py (filtro del feed de noticias).

CREATE TABLE IF NOT EXISTS noticias_hidden (
    id  TEXT NOT NULL PRIMARY KEY   -- = noticias.id (MD5 del url normalizado, 16 hex)
);
