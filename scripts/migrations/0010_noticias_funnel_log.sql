-- 0010_noticias_funnel_log.sql — Log de salidas del funnel de noticias (PR1).
--
-- Registra TODA nota que entra al funnel del carril Bolivia y NO termina publicada,
-- con su score y la razón, para hacer auditable PR2 (16 categorías nuevas + rescate y
-- la bajada de UMBRAL_PUNTAJE). Poblaciones registradas (col `salida`):
--   keyword_excluida / falta_bolivia / umbral_modelo  — kills de scraper.evaluar (puntaje 0)
--   no_calificada                                     — pasó evaluar pero < UMBRAL_PUNTAJE
--   evento_absorbida                                  — colapsada por agrupar_eventos (con representante_id)
--   dedupe_inter_dia                                  — gemela de una nota ya publicada (es_repetida)
--   evictada                                          — desplazada del cupo diario por una de mayor score
-- Las colisiones de id (URL ya en `noticias`) NO se registran: no son pérdida.
--
-- PK = (url, fecha) → dedup DENTRO del día: los kills de evaluar y las absorbidas se
-- re-evalúan ~14×/día pero dejan 1 fila/día (INSERT OR REPLACE, última corrida del día
-- gana), y la serie cross-día se conserva (re-avistada el día 20 = fila nueva). TTL 30
-- días (purga idempotente en ingest_noticias.purgar_funnel_log). La escritura es NO-FATAL
-- y gateada por FUNNEL_LOG_ENABLED (default '1'). Espejo runtime idempotente en
-- ingest_noticias.DDL_FUNNEL_LOG (el cron lo autocrea; esta migración es el canon).

CREATE TABLE IF NOT EXISTS noticias_funnel_log (
    url              TEXT NOT NULL,      -- URL de la nota
    fecha            TEXT NOT NULL,      -- YYYY-MM-DD (Bolivia UTC-4) de la corrida
    hora             TEXT NOT NULL,      -- HH:MM (Bolivia UTC-4)
    portal           TEXT NOT NULL,
    titulo           TEXT NOT NULL,
    tema             TEXT NOT NULL DEFAULT '',
    score_crudo      REAL,               -- prob TF-IDF cruda (NULL si no hubo modelo / kill pre-scoring)
    score_ajustado   REAL,               -- prob tras la escala editorial
    puntaje          REAL NOT NULL,      -- 0-10 final (0 = kill de evaluar)
    salida           TEXT NOT NULL,      -- razón de salida (ver arriba)
    penalizado_por   TEXT NOT NULL DEFAULT '',  -- slug de la penalización (atribución de causa); '' si ninguna
    taxonomia_v      INTEGER,            -- versión de la escala editorial vigente al evaluar
    representante_id TEXT,               -- solo evento_absorbida: id del representante que la absorbió
    created_at_utc   TEXT NOT NULL,
    PRIMARY KEY (url, fecha)             -- dedup dentro del día; serie cross-día preservada
);
CREATE INDEX IF NOT EXISTS idx_funnel_log_fecha ON noticias_funnel_log(fecha);
