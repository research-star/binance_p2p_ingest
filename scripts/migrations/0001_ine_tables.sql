-- 0001_ine_tables.sql — INE Bolivia macro ingest schema.
--
-- Crea las tres tablas necesarias para los ingests ingest_ine_pib.py y
-- ingest_ine_ipc.py. Idempotente — se puede correr varias veces sin efecto.
-- Aplicar: sqlite3 /opt/binance_p2p/p2p_normalized.db < scripts/migrations/0001_ine_tables.sql

-- PIB (trimestral + anual serie histórica).
-- `periodo` formato:
--   - 'YYYY-Qn' para trimestral (ej. '2024-Q1', '2024-A' para acumulado anual del trim)
--   - 'YYYY'    para anual serie histórica
-- `cuadro`: namespaceado para evitar colisión de filename `01.01.01.xlsx`
--   reusado por PIB Trimestral e Indicadores Anuales (ej. 'pib_trim_01_01_01' vs
--   'pib_anual_serie_actividad').
-- `dimension`: sector económico o componente del gasto, slugified (ascii lowercase, _).
-- `unidad`: 'miles_bs_1990' (constante base 1990) | 'miles_bs_corrientes' | 'pct_yoy' |
--   'incidencia' — depende del cuadro.
-- `is_preliminary`: 1 si la columna de año en el header lleva sufijo '(p)'.
CREATE TABLE IF NOT EXISTS ine_pib (
  periodo         TEXT NOT NULL,
  cuadro          TEXT NOT NULL,
  dimension       TEXT NOT NULL,
  valor           REAL,
  unidad          TEXT NOT NULL,
  is_preliminary  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (cuadro, periodo, dimension)
);
CREATE INDEX IF NOT EXISTS idx_ine_pib_dim
  ON ine_pib (cuadro, dimension, periodo);

-- IPC (nacional, COICOP, empalmada).
-- `periodo` formato 'YYYY-MM'.
-- `cuadro`: namespaceado por fuente (ej. 'ipc_nacional_general', 'ipc_division_coicop',
--   'ipc_empalmada').
-- `indicador`: para IPC nacional/empalmada → 'indice' | 'var_mensual' | 'var_acumulada' |
--   'var_12m'. Para IPC COICOP → '<metric>_<division_slug>' (4 métricas × 13 divisiones).
-- `unidad`: 'indice_base_2016' | 'pct_mensual' | 'pct_acumulada' | 'pct_12m'.
-- `base_year`: '2016' actualmente; NULL si la serie es empalmada multi-base.
CREATE TABLE IF NOT EXISTS ine_ipc (
  periodo     TEXT NOT NULL,
  cuadro      TEXT NOT NULL,
  indicador   TEXT NOT NULL,
  valor       REAL,
  unidad      TEXT NOT NULL,
  base_year   TEXT,
  PRIMARY KEY (cuadro, periodo, indicador)
);
CREATE INDEX IF NOT EXISTS idx_ine_ipc_ind
  ON ine_ipc (cuadro, indicador, periodo);

-- IPP (Índice de Precios al Productor).
-- Misma forma que `ine_ipc` (mensual, indicadores compuestos para el cuadro
-- sectorial), tabla separada porque IPP mide precios al productor industrial
-- y no es directamente comparable con el IPC de consumidor. base_year = '2016'.
-- `cuadro`: 'ipp_nacional' (Bolivia agregado) | 'ipp_grandes_grupos' (sector
--   actividad: 0=total, 1-6=Agricolas/Industria/Otros minerales y gas/
--   Pecuaria/Pesca/Servicios).
-- `indicador`: para ipp_nacional → {indice, var_mensual, var_acumulada, var_12m}.
--   Para ipp_grandes_grupos → '<metric>_<grupo_slug>' (28 = 4 × 7), con
--   '<metric>_total' para el grupo 0 (ÍNDICE GENERAL, replica del nacional).
CREATE TABLE IF NOT EXISTS ine_ipp (
  periodo     TEXT NOT NULL,
  cuadro      TEXT NOT NULL,
  indicador   TEXT NOT NULL,
  valor       REAL,
  unidad      TEXT NOT NULL,
  base_year   TEXT,
  PRIMARY KEY (cuadro, periodo, indicador)
);
CREATE INDEX IF NOT EXISTS idx_ine_ipp_ind
  ON ine_ipp (cuadro, indicador, periodo);

-- Ingest state (reemplaza el patrón .last_etag de EMBI porque el Nextcloud del INE
-- no emite ETag/Last-Modified). 1 fila por cuadro_id. Detección de release vía
-- (a) parsing de Content-Disposition para IPC/IPP (filename versionado YYYY_MM) y
-- (b) MD5 del body para PIB (filename estático, release dentro del XLSX).
CREATE TABLE IF NOT EXISTS ine_ingest_state (
  cuadro             TEXT PRIMARY KEY,
  last_filename      TEXT,
  last_md5           TEXT,
  last_release_id    TEXT,
  last_fetched_at    TEXT NOT NULL
);
