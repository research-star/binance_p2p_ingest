# INE Bolivia — Reporte de datos macro (PIB + IPC)

Insumo para diseño de la futura tab Macroeconomía en el dashboard.
Generado contra `ine_test.db` (DB local de prueba, ignorada via `.gitignore`)
tras la primera corrida exitosa de `ingest_ine_pib.py` + `ingest_ine_ipc.py`
el **2026-06-03**.

Para reproducir los conteos y valores que aparecen abajo:
```bash
rm -f ./ine_test.db
python ingest_ine_pib.py --db ./ine_test.db
python ingest_ine_ipc.py --db ./ine_test.db
# Queries puntuales con sqlite3 ./ine_test.db
```

Release vigente: **Mayo 2026** (IPC) y **2024 Q4** (PIB).

---

## En 90 segundos: qué tenemos

- **10 cuadros** ingeridos del INE Bolivia (5 PIB + 3 IPC + 2 IPP),
  persistidos en 4 tablas SQLite (`ine_pib`, `ine_ipc`, `ine_ipp`,
  `ine_ingest_state`).
- **21 640 filas** de data real (8 020 PIB + 10 004 IPC + 3 616 IPP) cubriendo:
  - **PIB:** 1980-2024 anual + 1990 Q1 - 2024 Q4 trimestral
  - **IPC:** 1937-presente (serie empalmada) y 2018-2026 (Base 2016 vigente)
  - **IPP:** 2017-2026 (Base 2016, 2 cuadros)
- **Última inflación interanual al consumidor (IPC May 2026): +12.51%** —
  Bolivia atraviesa el segundo año consecutivo con inflación >10%, tras
  décadas en rango 0-6%.
- **Inflación al productor (IPP Abr 2026): +13.94% YoY**, pero **desacelerando**
  fuerte (-1.81% mensual, -1.60% YTD acumulado) — primera señal de
  compresión de costos productivos que suele anticipar enfriamiento del IPC
  en 1-3 meses.
- **Sectores IPC con presión fuerte** (May 2026 var 12m): Transporte +31.3%,
  Alimentos +16.3%, Salud +13.1%. Único con deflación: Comunicaciones -4.8%.
- **Sectores IPP líderes** (Abr 2026 var 12m): Pecuaria +25.76%, Industria
  manufacturera +18.92%. Deflación productor: Pesca -5.07%, Agricolas -1.36%.
- **PIB Q4 2024 (preliminar) cayó 2.6% YoY**. Petróleo crudo y gas: -15%.
  Industria manufacturera: -5%. Minería: +10% (único en alza). Señal de
  recesión sectorial difundida. **Nota:** INE publicó Q4 2025 vía PDF de
  prensa (caída acumulada anual -1.58%) pero el XLSX oficial todavía está
  en Q4 2024 — lag estructural ~17 meses, esperamos refresh entre julio-
  octubre 2026.

---

## 1. Catálogo de indicadores

| Cuadro DB | Qué mide | Unidad | Periodicidad | Cobertura | Filas |
|---|---|---|---|---|---|
| `pib_trim_01_01_01` | PIB por actividad económica, precios constantes | Miles de Bs 1990 | Trimestral + roll-up anual | 1990 Q1 → 2024 Q4 | 2 625 |
| `pib_trim_01_01_04` | Variación interanual del PIB por actividad | % YoY | Trimestral + anual | 1991 → 2024 Q4 | 2 550 |
| `pib_trim_02_01_01` | PIB por componente del gasto, precios constantes | Miles de Bs 1990 | Trimestral + anual | 1990 Q1 → 2024 Q4 | 1 225 |
| `pib_anual_serie_actividad` | Serie histórica PIB anual por actividad | Miles de Bs 1990 | Anual | 1980 → 2024 | 1 305 |
| `pib_anual_serie_gasto` | Serie histórica PIB anual por gasto | Miles de Bs 1990 | Anual | 1980 → 2024 | 315 |
| `ipc_nacional_general` | IPC Bolivia (índice + 3 variaciones) | índice 2016=100 / % | Mensual | 2018-01 → 2026-05 | 404 non-null |
| `ipc_division_coicop` | IPC por división COICOP (12 divisiones COICOP + 1 fila "ÍNDICE GENERAL" / total Bolivia) | índice 2016=100 / % | Mensual | 2018-01 → 2026-05 | 5 252 |
| `ipc_empalmada` | Serie histórica IPC empalmada (incluye hiperinflación 1985) | índice 2016=100 / % | Mensual | 1937-01 → 2026-05 | 4 267 non-null |
| `ipp_nacional` | IPP Bolivia agregado (índice + 3 variaciones) | índice 2016=100 / % | Mensual | 2017-01 → 2026-04 | 448 non-null |
| `ipp_grandes_grupos` | IPP por Grandes Grupos (6 sectores actividad + 1 total) | índice 2016=100 / % | Mensual | 2017-01 → 2026-04 | 3 136 |

**Indicador** dentro de cada cuadro IPC:
- `indice` — nivel del IPC, base 2016=100
- `var_mensual` — variación % vs mes anterior
- `var_acumulada` — variación % YTD (desde diciembre del año anterior)
- `var_12m` — variación % vs mismo mes año anterior (inflación interanual)

Para `ipc_division_coicop` los indicadores vienen compuestos:
- División 0 (total Bolivia, "ÍNDICE GENERAL"): `<metric>_total`
  (ej. `var_12m_total`).
- Divisiones 1-12 (subgrupos COICOP): `<metric>_<division_slug>`
  (ej. `var_12m_alimentos_y_bebidas_no_alcoholicas`).

Eso da 4 métricas × (1 total + 12 divisiones) = 52 indicadores únicos. Para
graficar solo las 12 divisiones: `WHERE indicador LIKE 'var_12m_%' AND
indicador != 'var_12m_total'`.

**Semántica de `base_year`:** sólo el indicador `indice` (nivel del índice)
lleva `base_year='2016'`. Los 3 indicadores de variación (`var_mensual`,
`var_acumulada`, `var_12m`) son porcentajes; su `base_year` es `NULL`
porque conceptualmente no aplica.

---

## 2. Snapshot reciente: IPC Nacional 2026

Índice general Bolivia (base 2016=100), últimos 12 meses:

| Mes | Índice | Var mensual | Var acumulada YTD | Var 12 meses (inflación) |
|---|---:|---:|---:|---:|
| 2025-06 | 141.19 | +5.21% | 15.53% | **+23.96%** |
| 2025-07 | 142.88 | +1.20% | 16.92% | +24.86% |
| 2025-08 | 144.32 | +1.01% | 18.09% | +24.15% |
| 2025-09 | 144.61 | +0.20% | 18.33% | +23.32% |
| 2025-10 | 145.70 | +0.75% | 19.22% | +22.23% |
| 2025-11 | 146.27 | +0.40% | 19.69% | +20.96% |
| 2025-12 | 147.14 | +0.59% | **20.40%** (cierre anual) | +20.40% |
| 2026-01 | 149.06 | +1.31% | 1.31% | +19.64% |
| 2026-02 | 148.14 | -0.62% | 0.68% | +17.41% |
| 2026-03 | 147.63 | -0.34% | 0.34% | +15.05% |
| 2026-04 | 147.84 | +0.14% | 0.47% | +14.18% |
| **2026-05** | **150.98** | **+2.13%** | **2.62%** | **+12.51%** |

**Observaciones:**
- Inflación acumulada 2025 cerró en **20.40%** — la mayor desde la
  estabilización de mediados de los 80.
- Pico de Junio 2025 (+5.21% mensual) corresponde probablemente al ajuste de
  combustibles / shock cambiario paralelo. Validar contra dataset de
  Riesgo País y del USDT/BOB del proyecto.
- En 2026 Enero hubo rebote (+1.31%) seguido por dos meses de leve deflación
  (Feb -0.62%, Mar -0.34%). Mayo (+2.13%) sugiere reactivación de presión.

---

## 3. Snapshot reciente: IPC por División COICOP, Mayo 2026

Variación interanual (12 meses) por las 12 divisiones + total Bolivia:

| Ranking | División | Var 12m (May 2026) |
|---|---|---:|
| 1 | Transporte | **+31.35%** |
| 2 | Alimentos y bebidas no alcohólicas | +16.28% |
| 3 | Alimentos y bebidas consumidos fuera del hogar | +15.68% |
| 4 | Salud | +13.07% |
| 5 | Bebidas alcohólicas y tabaco | +13.00% |
| — | **Índice General Bolivia** | **+12.51%** |
| 6 | Prendas de vestir y calzado | +9.28% |
| 7 | Vivienda y servicios básicos | +8.24% |
| 8 | Educación | +5.48% |
| 9 | Muebles, bienes y servicios domésticos | +4.87% |
| 10 | Bienes y servicios diversos | +4.58% |
| 11 | Recreación y cultura | +3.32% |
| 12 | **Comunicaciones** | **-4.83%** (única deflación) |

**Hallazgos clave:**
- Transporte lidera con casi 2.5x el índice general — combustibles +
  fletes son el driver dominante. Conecta con la narrativa del proyecto:
  shock de combustibles → presión sobre el USDT/BOB paralelo.
- Comunicaciones es el único bien/servicio con deflación interanual
  (-4.83%) — competencia entre operadores telcom + commoditización de
  data. Patrón sostenido históricamente, no específico de 2026.

---

## 4. Snapshot reciente: PIB Bolivia, 2024 Q3-Q4 (preliminar)

PIB por **actividad económica** (millones de Bs constantes de 1990) — Q4 2024:

| Sector | Q4 2024 | YoY (var_12m) |
|---|---:|---:|
| **PIB a precios de mercado** | **13 624.7** | **-2.60%** |
| PIB a precios básicos | 11 899.9 | -1.97% |
| Industria manufacturera | 2 216.3 | -5.06% |
| Derechos de importación, IVA, IT y otros | 1 724.8 | -6.74% |
| Establecimientos financieros, seguros, inmuebles | 1 666.0 | +3.68% |
| Transporte y comunicaciones | 1 595.4 | -1.50% |
| Servicios de la administración pública | 1 466.6 | -4.80% |
| Agricultura, silvicultura, caza y pesca | 1 463.4 | -3.71% |
| Comercio | 1 013.4 | -2.72% |
| Otros servicios | 922.5 | +2.03% |
| Construcción | 803.7 | +2.96% |
| **Minerales metálicos y no metálicos** | **600.5** | **+10.00%** |
| Electricidad, gas y agua | 381.6 | -0.45% |
| **Petróleo crudo y gas natural** | **381.5** | **-15.05%** |
| Servicios bancarios imputados (deducción) | -611.0 | +4.14% |

PIB por **componente del gasto** (Q4 2024, todos preliminares):

| Componente | Q4 2024 |
|---|---:|
| PIB a precios de mercado | 13 624.7 |
| Gasto de consumo final de los hogares e IPSFL | 10 575.9 |
| Formación bruta de capital fijo (inversión) | 3 042.7 |
| Importaciones de bienes y servicios (resta) | -2 849.9 |
| Exportaciones de bienes y servicios | 2 766.5 |
| Gasto de consumo final de la administración pública | 1 872.5 |
| Variación de existencias | -1 783.0 |

**Hallazgos:**
- Caída del PIB total **-2.6%** Q4 2024 (preliminar) — primera caída
  trimestral significativa desde la pandemia. Hidrocarburos (-15%) y
  manufactura (-5%) explican la mayor parte; minería (+10%) compensa
  parcialmente.
- Inversión sigue débil (~22% del PIB). Variación de existencias
  fuertemente negativa (-1 783) sugiere desacumulación — consistente con
  contracción de la demanda.
- Hogares (consumo) representan ~78% del PIB, muy típico para Bolivia.

---

## 5. Snapshot reciente: IPP Bolivia, Abril 2026 (último release)

El IPP (Índice de Precios al Productor) mide precios en la **boca de
fábrica / origen del productor**, antes de llegar al consumidor final.
Sirve para anticipar movimientos del IPC (cuando un shock en costos
productivos sube el IPP, el IPC suele seguir con 1-3 meses de lag) y
para diagnosticar qué sectores están comprimiendo márgenes.

**IPP Bolivia agregado nacional, últimos 12 meses + abril 2026:**

| Mes | Índice (base 2016=100) | Var mensual | Var acumulada YTD | Var 12 meses |
|---|---:|---:|---:|---:|
| 2025-05 | 137.65 | +0.39% | +9.06% | **+21.13%** |
| 2025-06 | 144.46 | +4.95% | +14.45% | +25.96% |
| 2025-07 | 145.04 | +0.40% | +14.91% | +25.62% |
| 2025-08 | 146.71 | +1.15% | +16.23% | +24.69% |
| 2025-09 | 145.97 | -0.50% | +15.65% | +23.07% |
| 2025-10 | 147.30 | +0.91% | +16.71% | +22.05% |
| 2025-11 | 147.86 | +0.38% | +17.16% | +20.84% |
| 2025-12 | 148.06 | +0.13% | **+17.31%** | +20.39% |
| 2026-01 | 152.55 | +3.03% | +3.03% | +20.96% |
| 2026-02 | 154.42 | +1.23% | +4.30% | +20.42% |
| 2026-03 | 154.24 | -0.12% | +4.18% | +17.96% |
| **2026-04** | **151.45** | **-1.81%** | **-1.60%** | **+13.94%** |

**Observaciones clave:**
- **El IPP YTD 2026 cayó -1.60%** (vs cierre 2025) — primera deflación
  acumulada significativa post-shock 2024-2025. Esto suele anticipar
  desaceleración del IPC en los meses siguientes (compresión de
  márgenes corriendo abajo en la cadena).
- **Var 12m bajando** de +25.96% (Jun 2025) a +13.94% (Abr 2026) →
  desaceleración productor está corriendo MÁS RÁPIDO que la del IPC
  (que también baja pero más despacio). Brecha consumidor-productor
  posiblemente se está cerrando.

### Por sector de actividad (Grandes Grupos), abril 2026

7 grupos. División 0 (ÍNDICE GENERAL) replica el agregado nacional.

| Ranking | Grandes Grupos | Var 12m (Abr 2026) |
|---|---|---:|
| 1 | Pecuaria | **+25.76%** |
| 2 | Industria Manufacturera | +18.92% |
| — | **Índice General** | **+13.94%** |
| 3 | Servicios | +13.49% |
| 4 | Otros Minerales y Gas Natural | +4.81% |
| 5 | Agricolas | -1.36% (deflación) |
| 6 | **Pesca** | **-5.07%** (mayor deflación) |

**Hallazgos:**
- **Pecuaria (+25.76%) e Industria Manufacturera (+18.92%) lideran**
  la inflación productor. Pecuaria conecta con el shock de Alimentos
  del IPC (+16.28% en Mayo 2026) — un trimestre delay típico.
- **Agricolas y Pesca con deflación interanual.** Producción primaria
  pre-procesada está bajando precio mientras alimentos procesados
  suben — sugiere apreciación del valor agregado de la cadena.
- **Servicios (+13.49%) ≈ IPC Servicios** — el componente menos volátil
  de la cesta de precios.

### Cobertura y notas

- Cobertura IPP: 2017-01 a 2026-04 (~9 años, 112 meses). Mucho más
  corta que el IPC empalmada — no hay serie empalmada de IPP.
- Base year: 2016=100 (mismo que IPC).
- "Agricolas" en el XLSX del INE está escrito sin tilde (typo en
  source). El parser lo slugifica a `agricolas` literal — preservamos
  el typo del INE para no romper la trazabilidad.
- Indicador del grupo 0 = `<metric>_total` (mismo patrón que IPC COICOP).
  Query "las 6 actividades productivas": `WHERE indicador LIKE
  'var_12m_%' AND indicador != 'var_12m_total'`.

---

## 6. Serie larga: IPC Empalmada 1937-2026

La serie empalmada del INE encadena 3 bases (1936, 2007, 2016) → cada mes
está expresado en términos comparables a base 2016=100. Hace posible
graficar 90 años de IPC en un solo eje.

**Hitos del nivel del índice** (Dic de cada año salvo May 2026):

| Año | IPC (base 2016=100) |
|---|---:|
| 1937 Dic | ~0.0 (10⁻⁵, valor microscópico por la cadena de retropolación) |
| 1985 Dic | 6.62 |
| 2000 Dic | 44.07 |
| 2015 Dic | 94.42 |
| 2025 Dic | 147.14 |
| 2026 May | 150.98 |

**Picos históricos de inflación interanual (var_12m):**

| Periodo | Var 12m | Contexto |
|---|---:|---|
| 1985-09 | **+23 447%** | Pico de la hiperinflación |
| 1985-08 | +20 561% | Pre-estabilización (Decreto 21060) |
| 1985-10 | +14 422% | Inicio del programa de ajuste de Paz Estenssoro |
| 1985-07 | +14 173% | |
| 1985-11 | +11 292% | |

**Pisos históricos (deflación):**

| Periodo | Var 12m |
|---|---:|
| 1958-01 | -13.83% |
| 1957-12 | -13.76% |
| 1958-03 | -8.22% |

La serie permite contrastar **el régimen pre-1985** (volatilidad enorme,
hiperinflación) con el **post-1986** (estabilización, inflación de 1
dígito) y el **post-2024** (re-aceleración a >10% YoY). Material narrativo
fuerte para storytelling.

---

## 7. Cobertura, calidad, gaps

- **Preliminares (`is_preliminary=1`):** todos los años PIB 2017-2024 están
  marcados como preliminares (sufijo `(p)` en el header del XLSX del INE).
  El consumidor decide cómo tratarlos — no los filtramos en origen.
- **IPC Mayo 2026 es el último mes oficial.** Los meses Jun-Dic 2026 quedan
  como filas con `valor IS NULL` en la DB (no extrapolamos). El frontend
  debe filtrar `WHERE valor IS NOT NULL` para gráficos.
- **IPC Empalmada base 2016:** los valores 1937-2008 son matemáticamente
  microscópicos (orden 10⁻⁸ a 10⁻¹) por la retropolación. **No son bug**:
  son el reescalamiento legítimo. Para gráficos sobre el nivel, **usar
  escala logarítmica**. Para gráficos sobre variaciones (% YoY, mensual)
  no hace falta — esas magnitudes son comparables directamente.
- **Inflación 1986-1987:** los `var_12m` muestran transición abrupta de
  hiperinflación a inflación de 2 dígitos. Confirmar visualmente cuando
  se grafique — son auténticos, no artefacto de empalme.
- **PIB trimestral antes de 1990:** la cobertura empieza en 1990 Q1
  (cuadros 01.01.01 y 02.01.01). El cuadro de variaciones (01.01.04)
  empieza en 1991 porque necesita un año previo para calcular el YoY.

---

## 8. Series candidatas para la UI

Lista jerarquizada por valor narrativo. **No prioriza** — Diego decide qué
entra en V1 del tab Macroeconomía.

### Tier A — historia central de FinanzasBo

1. **Inflación interanual Bolivia 1937-presente** (`ipc_empalmada` →
   `indicador='var_12m'`). Una sola serie monthly, eje X 90 años. Marca
   visualmente la zona 1984-1986 (hiperinflación) y la actual >10% YoY.
   Storytelling de "la otra vez que esto pasó". Probable hero chart.
2. **Inflación interanual Bolivia 2018-presente** (`ipc_nacional_general`
   → `indicador='var_12m'`). Versión zoom-in del anterior, sin el ruido
   pre-2018. Foco en el ciclo actual.
3. **Variación mensual del IPC, 12 meses rolling** (`ipc_nacional_general`
   → `var_mensual`). Útil para detectar pulsos (Junio 2025: +5.21%
   mensual). Combinable con dataset del USDT/BOB del proyecto.

### Tier B — desagregación accionable

4. **IPC por división COICOP, var 12m, último mes** (`ipc_division_coicop`
   → `WHERE indicador LIKE 'var_12m_%' AND indicador != 'var_12m_total'`).
   Bar chart horizontal con 12 divisiones ordenadas. Diagnóstico de "qué
   está caro este mes" — Transporte, Alimentos, Salud.
5. **IPC por división COICOP, evolución 2018-presente** (mismo cuadro,
   serie tiempo). Comparar drivers entre periodos.

### Tier C — PIB

6. **PIB Bolivia anual 1980-2024** (`pib_anual_serie_actividad` →
   `dimension='producto_interno_bruto_a_precios_de_mercado'`). Una línea,
   44 años. Eje Y en miles de millones Bs 1990.
7. **PIB por sector, share del total, último año** (`pib_anual_serie_actividad`
   → último periodo, todas las dimensiones). Treemap o pie. Visualiza la
   estructura productiva boliviana.
8. **PIB trimestral var 12m por sector, último año** (`pib_trim_01_01_04`
   → último Q). Bar chart con 14 sectores, separar los positivos de los
   negativos. Diagnóstico de "qué se está contrayendo".

### Tier C-bis — IPP

9. **IPP vs IPC interanual, overlay 2017-presente** (`ipp_nacional`
   `indicador='var_12m'` + `ipc_nacional_general` `indicador='var_12m'`).
   Doble línea, eje X mensual. Útil para anticipar dirección del IPC:
   históricamente el IPP cambia de signo / pendiente antes que el IPC.
10. **IPP por Grandes Grupos, var 12m, último mes** (`ipp_grandes_grupos`
    → `WHERE indicador LIKE 'var_12m_%' AND indicador != 'var_12m_total'`).
    Bar chart con 6 sectores (Pecuaria, Industria Manufacturera, Servicios,
    Otros Minerales y Gas Natural, Agricolas, Pesca). Análogo al IPC COICOP
    pero del lado productor — diagnóstico de "qué cadena de costos está
    presionando".

### Tier D — bridges con el resto del dashboard

11. **Tipo de cambio paralelo USDT/BOB (existente) vs inflación interanual
    (nueva).** Doble eje. Argumento natural: el shock de combustibles
    2025 alimenta tanto la inflación como la prima paralela del USDT.
12. **EMBI Bolivia (existente) vs PIB var 12m (nuevo).** Doble eje. La
    correlación negativa (riesgo soberano sube cuando el PIB cae) es un
    relato canónico del análisis macro emergente.

---

## 9. Notas operativas

- **Detección de release:**
  - IPC / IPP: el filename del Content-Disposition incluye `YYYY_MM` (ej.
    `Nal-2026_05_…`, `IPP-2026_04_…`) → release_id viene del filename,
    barato de detectar.
  - PIB: filename estático (`01.01.01.xlsx`) → release_id = prefix MD5 del
    body. Más caro (hay que descargar) pero PIB se publica con baja
    frecuencia (trimestral con ~90 días de lag), así que está bien.
- **Idempotencia:** re-correr cualquier ingest con la misma DB y el MD5 no
  cambiado → `mode=skip` instantáneo (~1-2 segundos por cuadro), sin
  re-insertar nada. Verificado.
- **Tiempos primer-run (laptop local):** PIB total ~230 s (dominado por
  nimbus que tarda ~90 s/cuadro), IPC total ~190 s. Subsecuentes (skip):
  ~3 s y ~5 s respectivamente.
- **Backfill:** no aplica — cada XLSX trae la serie completa desde el inicio.
  `INSERT OR REPLACE` por (cuadro, periodo, dimension|indicador) hace
  upsert idempotente. Si INE publica revisión retroactiva de un trimestre
  viejo, el cambio entra automáticamente.
- **Guardia contra collapse silencioso:** el upsert (PIB y IPC) verifica
  antes de insertar que no haya dos filas con la misma PK con valores
  distintos. Si las hubiera (típicamente por un typo del INE en el label
  de un año, ej. `'2022p)'` sin paréntesis abrir, observado en el cuadro
  `pib_trim_02_01_01` release 2026-05), falla loud con `RuntimeError` y
  pide inspeccionar el XLSX. El parser ya tolera ese caso específico; la
  guardia cubre futuras variantes.

---

## 10. Apéndice: schema SQLite vivo

```sql
-- ine_pib
periodo         TEXT NOT NULL       -- 'YYYY-Qn' (trim) | 'YYYY' (anual)
cuadro          TEXT NOT NULL       -- namespaced cuadro_id
dimension       TEXT NOT NULL       -- sector / componente, slugified
valor           REAL                -- nullable
unidad          TEXT NOT NULL       -- 'miles_bs_1990' | 'pct_yoy' | ...
is_preliminary  INTEGER NOT NULL    -- 0 | 1
PRIMARY KEY (cuadro, periodo, dimension)

-- ine_ipc
periodo     TEXT NOT NULL           -- 'YYYY-MM'
cuadro      TEXT NOT NULL
indicador   TEXT NOT NULL           -- 'indice' / 'var_*' / '<metric>_<div>'
valor       REAL
unidad      TEXT NOT NULL           -- 'indice_base_2016' | 'pct_*'
base_year   TEXT                    -- '2016' | NULL
PRIMARY KEY (cuadro, periodo, indicador)

-- ine_ipp (misma forma que ine_ipc, tabla separada por semántica)
periodo     TEXT NOT NULL           -- 'YYYY-MM'
cuadro      TEXT NOT NULL           -- 'ipp_nacional' | 'ipp_grandes_grupos'
indicador   TEXT NOT NULL           -- 'indice' / 'var_*' / '<metric>_<grupo>'
valor       REAL
unidad      TEXT NOT NULL           -- 'indice_base_2016' | 'pct_*'
base_year   TEXT                    -- '2016' | NULL
PRIMARY KEY (cuadro, periodo, indicador)

-- ine_ingest_state
cuadro             TEXT PRIMARY KEY
last_filename      TEXT             -- del Content-Disposition (IPC/IPP) o estático (PIB)
last_md5           TEXT             -- hex md5 del body
last_release_id    TEXT             -- 'YYYY_MM' (IPC/IPP) | prefix MD5 (PIB)
last_fetched_at    TEXT NOT NULL    -- ISO UTC
```

Queries de ejemplo para el frontend están en el código del próximo
megarun (Macro tab); por ahora cualquier `SELECT` ad-hoc sobre estas
4 tablas devuelve data clean.
