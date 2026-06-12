# PASO 0 — RIN histórica con bandas de rating (subtab Riesgo País)

> Investigación de viabilidad, 2026-06-12. Sin implementación. Perímetro:
> repo solo lectura + web pública. VPS no tocado (info de cron relevada de
> `HANDOFF.md`). Convención: **[V]** = verificado con request/parseo real;
> **[I]** = inferido de página/búsqueda. CONFIRMADO = fuente primaria o ≥2
> secundarias coincidentes; INFERIDO = una sola secundaria o fecha aproximada.

## Veredicto en una línea

**Viable con el patrón de ingest existente.** La fuente primaria (Estadística
Semanal del BCB) trae en un solo XLSX el histórico mensual completo
1987→presente + el dato de la semana en curso, así que backfill y actualización
incremental son el mismo code path (igual que EMBI). El historial de ratings es
un dataset curado chico (~20 acciones S&P en 28 años) → literal estático en
`template.html`, patrón `DEBT_SCHEDULE` del PR #55.

---

## A. Ficha de la fuente RIN

### Primaria — BCB "Información Estadística Semanal"

| Campo | Valor |
|---|---|
| Página índice | `https://www.bcb.gob.bo/?q=estad-sticas-semanales` **[V]** — HTML estático, responde a curl sin JS; links extraíbles con regex `webdocs/05_estadisticassemanales/[^"]+` |
| Archivo | XLSX ~830 KB, 1 hoja (ej. `Semanal 24_2026.xlsx`, "AL 03 DE JUNIO DE 2026") **[V]** |
| Contenido | Fila "1. Reservas internacionales netas del BCB" con **histórico mensual completo desde dic-1987** (452 obs verificadas) + columnas diarias de la semana en curso. También reservas brutas desagregadas (Oro, DEG, Divisas, Posición FMI). Unidad: millones de $us **[V]** |
| Frecuencia / lag | Semanal; archivo vigente al 12-jun cubre "al 03-jun" → lag ~7-9 días **[V/I]** |
| Estabilidad del link | **URL cambia por semana y el naming es inconsistente** (uploads manuales: `Semanal 23_2026t.xlsx`, `Semanal 21_2026_0.xlsx`, `Semanal 18_2026 (1).xlsx`; `23_2026.xlsx` da 404). NO construir la URL: scrapear el primer link del índice **[V]** |
| Acceso desde fuera | bcb.gob.bo detrás de CloudFront, TLS válido, HTTP 200 a curl pelado sin UA/cookies/JS **[V]**. Sin geo-block detectado (verificado desde IP EE.UU.; falta el curl de 1 minuto desde el VPS Hetzner). Antecedente favorable: `bcb_referencial.py` ya scrapea `www.bcb.gob.bo` desde el VPS 8×/día sin fricción |
| Quirk crítico | **Layout interno NO estable entre semanas**: fila/col de RIN y profundidad histórica cambian (fila 83/col 4 e historia desde 1987 en sem. 24 vs fila 12/col 3 desde 2008 en sem. 1). Parser por búsqueda de label + lectura de fechas de la fila de headers, nunca coordenadas fijas **[V]** |
| Otros quirks | Encoding roto en labels de todos los Excel BCB (matchear con regex tolerante, no igualdad exacta) **[V]** · break metodológico jun-2003 (recomendación FMI, notado en el propio archivo) **[V]** · datos "(p)" preliminares se revisan retroactivamente → upsert total, no append **[V]** |

### Secundaria — BCB "RIN por componentes" (cross-check)

URL **fija** que se sobreescribe (modelo EMBI-BCRD), XLSX 25 KB, mensual,
**solo 2022→presente** (ventana móvil ~4 años, no sirve para backfill).
Emite ETag y responde 304 a `If-None-Match` **[V]** → polling barato.
Desagregación limpia Oro/Divisas/DEG/Tramo FMI/Obligaciones. Ideal como
validación del último dato mensual o futura ampliación por componentes.
`https://www.bcb.gob.bo/webdocs/sector_externo/F%20Reservas%20Internacionales%20Netas/Reservas_Internacionales_Netas_del_Banco_Central_de_Bolivia_por_componentes.xlsx`

### Descartadas

- **UDAPE** `dossier.udape.gob.bo` (cuadro `c01020302`): XLS legacy anual
  1980-2024, actualizado 1×/año, fuente secundaria que cita al BCB. Solo
  cross-check anual **[V]**.
- **FMI** (IRFCL/SDMX): **Bolivia dejó de reportar al FMI — última obs
  oct-2021** en todo el dataset; además es reservas brutas, no RIN **[V]**.
- **Banco Mundial**: anual, lag >1 año, replica el dato BCB **[V]**.

### Veredicto ingest

**Patrón existente aplica, híbrido EMBI+INE**: descarga programada + parse
openpyxl + UPSERT idempotente a SQLite (EMBI), pero sin ETag útil en la
primaria (URL nueva cada semana) → detección de release estilo INE: scrape
del índice, primer link como `release_id`, skip si ya ingerido (tabla de
estado). **No hace falta carga única + append**: cada archivo trae la serie
completa, el upsert total absorbe revisiones retroactivas de los "(p)" gratis
(misma propiedad que INE, HANDOFF §8 "Idempotencia y backfill").

---

## B. Cronología de ratings soberanos (LP, moneda extranjera)

Fuentes cruzadas: TradingEconomics, countryeconomy, theglobaleconomy, cbonds,
títulos de comunicados primarios S&P (spglobal.com), prensa (Reuters/Bloomberg/
Infobae/El Deber/La Razón/Los Tiempos/MercoPress). **Vigente a jun-2026: S&P
CCC+/estable · Moody's Caa3/positiva · Fitch CCC** — las tres mejoraron a
Bolivia post-elección de Rodrigo Paz.

### S&P (escala para las bandas del chart)

| Fecha | Nota | Acción | Outlook | Estatus |
|---|---|---|---|---|
| jul-1998 | BB- | primera calificación | estable | INFERIDO |
| oct-2000 | B+ | downgrade | estable | INFERIDO |
| dic-2002 | B+ | outlook | negativa | INFERIDO |
| feb-2003 | B | downgrade (febrero negro) | negativa | INFERIDO |
| ago-2003 | B | outlook | estable | INFERIDO |
| oct-2003 | B- | downgrade (guerra del gas) | negativa | INFERIDO |
| 25-ago-2004 | B- | outlook | estable | INFERIDO |
| jun-2005 | B- | outlook | negativa | INFERIDO |
| nov-2005 | B- | outlook | estable | INFERIDO |
| abr-2006 | B- | outlook | negativa | INFERIDO |
| nov-2007 | B- | outlook | estable | INFERIDO |
| 06-may-2010 | B | upgrade | positiva | CONFIRMADO |
| 19-may-2011 | B+ | upgrade | estable | CONFIRMADO |
| 22-ago-2011 | B+ | outlook | positiva | CONFIRMADO |
| 18-may-2012 | BB- | upgrade | estable | CONFIRMADO |
| 15-may-2014 | BB | upgrade — **pico histórico** | estable | CONFIRMADO |
| 25-may-2017 | BB | outlook | negativa | CONFIRMADO |
| 23-may-2018 | BB- | downgrade | estable | CONFIRMADO (Infobae + TE) |
| 16-dic-2019 | BB- | outlook | negativa | CONFIRMADO |
| 17-abr-2020 | B+ | downgrade | estable | CONFIRMADO |
| 22-mar-2021 | B+ | outlook | negativa | CONFIRMADO |
| 06-dic-2022 | B | downgrade | estable | CONFIRMADO (El Deber + TE + ABI) |
| 15-mar-2023 | B | afirmación + CreditWatch neg | watch neg | CONFIRMADO (La Razón + TE) |
| 19-abr-2023 | B- | downgrade | negativa | CONFIRMADO |
| 22-nov-2023 | CCC+ | downgrade | negativa | CONFIRMADO (comunicado S&P id 3093731 + Reuters + cbonds) |
| 25-jun-2025 | CCC- | downgrade (2 escalones) | negativa | CONFIRMADO (comunicado S&P id 3397129 + TE + MercoPress) |
| **23-mar-2026** | **CCC+** | **upgrade (2 escalones)** | **estable** | CONFIRMADO (comunicado S&P id 3534901 + Reuters) — **VIGENTE** |

### Moody's (resumen; cronología completa disponible)

B1 (may-1998) → B3 (abr-2003) → B2 (sep-2009) → B1 (dic-2010) → **Ba3
(jun-2012, pico)** → B1 (mar-2020) → B2 (sep-2020) → Caa1 (mar-2023) → Caa3
(abr-2024) → Ca (17-abr-2025, Bloomberg) → **Caa3/positiva (18-mar-2026,
Bloomberg; día 18 TE vs 19 Bloomberg — se toma 18 como fecha de acción) —
VIGENTE**. Todas CONFIRMADO salvo afirmación oct-2024 (INFERIDO).

### Fitch (resumen)

B- (mar-2004, INFERIDO) → B (sep-2009) → B+ (oct-2010) → BB- (oct-2012) →
**BB (jul-2015, pico)** → BB- (jul-2016) → B+ (nov-2019) → B (sep-2020) →
B- (mar-2023) → CCC (feb-2024, Bloomberg) → CCC- (ene-2025, MercoPress) →
**CCC (16-ene-2026, Bloomberg + Reuters) — VIGENTE** (Fitch no asigna
outlook en zona CCC). Resto CONFIRMADO.

### Advertencias de calidad de datos

1. **Agregadores contaminados con Venezuela**: countryeconomy y
   theglobaleconomy mezclan filas del historial S&P de Venezuela (CCC+
   sep-2014, CC/SD nov-2017, etc.) en la tabla de Bolivia. Descartadas por
   imposibilidad lógica con la secuencia BB(2017)→BB-(2018) confirmada.
   **No usar esos agregadores a ciegas.**
2. La era S&P 1998-2007 se sostiene en una sola secundaria → INFERIDO en
   bloque. Para las bandas del chart es bajo riesgo (el chart RIN arranca
   ~2000 y esa era es toda B+/B/B- — un mes de error de frontera no cambia
   la lectura).
3. S&P sin acción registrada en todo 2024 (CCC+/neg se mantuvo nov-2023 →
   jun-2025). No es hueco de datos: no hubo acción.
4. Comunicados primarios de S&P confirmados por título + ≥2 secundarias
   (spglobal.com devuelve 403 a fetch programático; entran gratis desde
   browser con registro).

---

## C. Propuesta de forma

### Qué va por ingest (serie viva)

- **`ingest_rin.py`** nuevo, mismas convenciones que EMBI/INE (CLI con
  `--force`/`--dry-run`, HC pings start/success/fail, audit folder con
  rotación, guardia anti-collapse pre-upsert):
  1. GET al índice `?q=estad-sticas-semanales` (HTML estático).
  2. Extraer el primer link `webdocs/05_estadisticassemanales/*.xlsx`;
     filename = `release_id`. Si ya está en la tabla de estado → skip no-op.
  3. Descargar, snapshot a `/opt/binance_p2p/rin_audit/`, rotación 60 días
     (releases semanales, no diarios — ritmo INE, no EMBI).
  4. Parse openpyxl **por búsqueda de label** (regex tolerante a encoding
     roto: `[Rr]eservas internacionales netas`), fechas desde la fila de
     headers. Coordenadas fijas prohibidas (layout variable verificado).
  5. Sanity-check: RIN en (0, 20.000) M$us, continuidad de fechas.
  6. UPSERT de la serie completa (absorbe revisiones "(p)").
- **Tabla**: `rin (fecha TEXT NOT NULL, rin_musd REAL NOT NULL, PRIMARY KEY
  (fecha))` — molde `embi_spreads` sin la dimensión país. Grano: mensual
  (fin de mes, `YYYY-MM-DD`); las columnas diarias de la semana en curso
  pueden sumarse después como obs adicionales si el card las pide (decisión
  de diseño visual, fuera de este PASO 0). Estado de release: tabla
  `rin_ingest_state` espejo de `ine_ingest_state`.
- **Payload**: `dashboard.py` embebe `DATA.rin_data` (shape columnar estilo
  EMBI: `{fechas:[], valores:[], fecha_actualizado}`). ~460 obs mensuales
  → payload trivial (~15 KB vs 880 KB del EMBI).

### Qué va estático

- **Historial de ratings**: literal JS en `template.html` (ej. `const
  RATING_HISTORY`), patrón `DEBT_SCHEDULE` (PR #55): dataset curado que
  cambia pocas veces al año, se edita y redeploya. Arrancar con S&P
  (alimenta las bandas); Moody's/Fitch quedan documentadas acá para un
  eventual tooltip/tabla comparativa.
- Cada entrada: `{fecha, nota, outlook, accion}`. Las bandas verticales se
  derivan de los intervalos entre acciones (desde fecha de acción hasta la
  siguiente; la última corre hasta hoy).

### Cron (especificación, sin tocar el VPS)

- `ingest_rin.py`: **2×/semana** es suficiente (publicación semanal con lag
  ~7-9 días y naming errático) — ej. `0 12 * * 2,5` UTC (08:00 BO martes y
  viernes), fuera de las ventanas de INE (días 1-10, 05:15/05:30) y EMBI
  (10:00/22:00). La detección de release hace que las corridas sin archivo
  nuevo sean no-op.
- Healthcheck `HC_RIN` (UUID nuevo en healthchecks.io), con la alerta
  derivada clave: **fail si el release más nuevo tiene >10 días** (detecta
  tanto caída del cron como BCB dejando de publicar o rotando el patrón de
  URL).

### Orden de implementación sugerido

1. PASO 1: `ingest_rin.py` + tabla + corrida local de backfill verificada
   contra los valores publicados (PR).
2. PASO 2: cron + HC en VPS (brief de ops aparte; incluye el curl de
   validación de acceso desde Hetzner — test de 1 minuto).
3. PASO 3: `DATA.rin_data` en `dashboard.py` + card frontend con
   `RATING_HISTORY` y bandas verticales (PR, reusa patrón de bandas
   horizontales del PR #56 con `xref:'x'`/`yref:'paper'`).

---

## D. Blockers y riesgos

| # | Riesgo | Severidad | Mitigación |
|---|---|---|---|
| 1 | Acceso desde IP Hetzner no verificado (la investigación salió desde IP EE.UU./local) | Bajo — `bcb_referencial.py` ya pega a bcb.gob.bo desde el VPS sin fricción | curl de 1 min desde el VPS en el PASO de ops |
| 2 | Naming semanal errático + semanas con sufijos raros | Medio | Nunca construir URL; scrapear índice; alerta >10 días |
| 3 | Layout interno variable del XLSX | Medio | Parser por labels + sanity-checks; guardia anti-collapse |
| 4 | Encoding roto en labels | Bajo | Regex tolerante |
| 5 | Break metodológico jun-2003 | Bajo (cosmético) | Documentar; opcional nota al pie del card |
| 6 | Era S&P 1998-2007 INFERIDA | Bajo | Banda igual en toda la era (B±); marcar en el literal con `confirmado:false` si se quiere |

Sin blockers duros: **luz verde para PASO 1**.
