-- 0002_noticias.sql — Tabla de la tab Noticias (feed real).
-- Idempotente. Aplicar a mano en el VPS:
--   sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0002_noticias.sql
-- Espejo del DDL inline de ingest_noticias.py (que también la crea si falta).
-- Escribe: ingest_noticias.py (cron diario). Lee: dashboard.py (últimos 30 días).

CREATE TABLE IF NOT EXISTS noticias (
    id              TEXT PRIMARY KEY,   -- hash MD5 corto del link normalizado
    date            TEXT NOT NULL,      -- YYYY-MM-DD (hora Bolivia): corrida (carril BO) / pubDate (latam)
    time            TEXT NOT NULL,      -- HH:MM (hora Bolivia): corrida (carril BO) / pubDate (latam)
    source          TEXT NOT NULL,      -- slug del portal (key de NOTICIAS_PORTALS)
    category        TEXT NOT NULL,      -- economia|hidrocarburos|agro|mineria|latam|politica
    title           TEXT NOT NULL,
    summary         TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT '',
    topics          TEXT NOT NULL DEFAULT '[]',  -- JSON array (tema original de boletines)
    impact          TEXT NOT NULL,      -- alto|medio|bajo (bandas sobre puntaje; latam: medio fijo)
    source_note     TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL,
    portal          TEXT NOT NULL,      -- nombre original del portal
    tema            TEXT NOT NULL DEFAULT '',
    puntaje         REAL NOT NULL,      -- TF-IDF x10 (carril BO); 0.0 = sentinela latam sin scoring
    score_crudo     REAL,
    score_ajustado  REAL,
    created_at_utc  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_noticias_date ON noticias(date);
