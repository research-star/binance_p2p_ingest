# Cuaderno — Hechos Relevantes (taxonomía source-agnostic)

Journal **append-only** de la clasificación de hechos relevantes. Nace con ASFI/RMV
pero está pensado para cualquier fuente futura de comunicados regulatorios (BBV,
APS, etc.): las lecciones sobre *cómo* separar "acta de reunión" de "evento
standalone", cómo evitar que un tag genérico infle un cajón, y cuándo degradar una
clasificación tentativa, se generalizan más allá de ASFI.

**Cómo usarlo (learn-loop):** antes de tocar un regex de clasificación, leé las
entradas previas. Cuando ajustes una regla y aparezca un falso positivo, anotá el
patrón ANTES de re-intentar — así el próximo pase no vuelve a caer en el mismo pozo.
Cada entrada: fecha · disparador · patrón/error · causa raíz · regla aplicada ·
generalización.

Convenciones vivas del clasificador viven en el código
(`asfi_ingest/extract.py`, `clasificar_grupo`); este archivo es el *por qué*.

---

## 2026-07-12 — Fase 2a: re-taxonomía + split Compromisos (`TAXONOMIA_V = 2`)

**Disparador.** "Otros comunicados" estaba inflado: 1.836 / 3.325 items (55%) sobre la
data ene–jul 2026. El brief pidió promover a grupos concretos la señal que YA existía
en tags/texto, partir Compromisos, y sembrar infraestructura (`grupo_v`, `revisado`,
cuaderno) para que el proceso sea incremental. Todo vía `--reextraer`, sin re-scrapear
ni IA. Resultado: **otros 1.836 → 750** (1.086 promovidos), cero regresión de conteo en
el split (102 reportados + 75 anunciados = 177 = total viejo).

Distribución final (data ene–jul 2026):
`juntas 849 · otros 750 · cupones 608 · personal 521 · prestamos 102 ·
compromisos_reportados 102 · compromisos_anunciados 75 · titularizacion 74 ·
emisiones 70 · uso_fondos 61 · dividendos 45 · auditorias 25 · calificaciones 23 ·
directorio 20`.

### Hallazgos y decisiones de calibración

**1. El cuello de botella era un `return "otros"` explícito.**
La regla `if "junta" in tags: return "otros"` cortaba ~691 items ANTES de llegar a
personal/prestamos/etc. Quitarla y rutear el frame de junta al FINAL (regla 13) liberó
la mayor parte del cajón. *Generalización:* un `return <cajón>` a media cadena de
prioridad es una fuga silenciosa — el cajón crece sin que ninguna regla "gane".

**2. El frame de reunión va ÚLTIMO, no primero.** Probé rutear "reunión de
Directorio … determinó lo siguiente" a `juntas` con prioridad ALTA. Falso positivo
masivo: robaba 115 personal, 8 préstamos, 16 auditorías que tenían un evento
específico extraíble (persona, monto, firma) → filas ricas degradadas a filas de
"reunión" sin campos. **Regla:** el evento específico (con su campo económico) gana;
el frame de acta multi-decisión (`_RE_REUNION_ACTA`) es el último recurso, solo captura
reuniones SIN evento dominante. *Generalización:* clasificá por el dato más
extraíble/accionable, no por el envoltorio formal del comunicado.

**3. Asamblea de accionistas (tag `junta`) ≠ acta de Directorio.** Distinción clave:
el tag `junta` sólo dispara con "junta general / asamblea general" (reuniones de
accionistas), NO con "reunión de Directorio". Las asambleas de accionistas son
multi-tema por naturaleza y se rutean a `juntas` (regla 13); las actas de Directorio
sí se rutean por evento dominante. Esta asimetría es intencional.

**4. Auditorías: FP por mención en agenda.** El tag `auditoria` dispara con "auditoría
externa" — que aparece en la agenda de MUCHAS juntas ("Consideración del Informe de
Auditoría Externa"). Con la condición vieja, auditorías saltaba de 17 → 116, y 92 de
esos eran juntas que solo mencionaban al auditor. **Fix:** `"auditoria" in tags and
"junta" not in tags` — las designaciones genuinas de auditor son actas de "reunión de
Directorio" (sin tag `junta`) o notas standalone. Bajó a 25 (16 con firma extraída).
*Generalización:* un tag de keyword que aparece en agendas necesita gate contra el
frame de junta.

**5. Emisiones: gate por sección FORMAL.** Ampliar emisiones para captar
"autoriza/inscribe … Bonos" sin exigir el tag `emision` (caso Carta ASFI/DSV/R-9688,
que sólo traía tag `tramite`) robaba cupones/compromisos/convocatorias que también
nombran "Bonos". **Fix:** el recovery exige `seccion in (Resoluciones, Cartas de
Autorización)` — cupones/compromisos/convocatorias viven en Hechos Relevantes/Noticias,
así que el gate de sección elimina la colisión. La inscripción vía Comité/Bolsa
(`_RE_INSCRIPCION`) sí es inequívoca y va sin gate.

**6. Personal sin persona en asamblea = fila inútil → degradar a juntas.** Una
asamblea (tag `junta`) que designa un síndico entre 8 puntos de agenda extrae, a lo
sumo, UNA persona arbitraria (la primera "señor X"). Degradación en `enriquecer`: si
`grupo == personal` y `junta in tags` y NO se extrajo `persona` → `juntas`. Mantiene
las filas de personal ricas (84% con persona) y manda las vacías al frame de junta.

**7. Titularización va DESPUÉS de directorio.** Un cambio de composición de directorio
de una titularizadora es más valioso como `directorio` (persona×silla) que como
`titularizacion`. Orden: directorio (6) antes que titularización (7). Pero
titularización va ANTES del frame de junta (13) porque el brief quiere las
convocatorias de tenedores de patrimonios autónomos en `titularizacion`.

**8. Split Compromisos determinístico.** `campos.indicadores` no vacío →
`compromisos_reportados` (tabla de indicadores parseada); vacío →
`compromisos_anunciados`. De los 75 anunciados, **28 traen una tabla presente pero
rota por el aplanado pypdf** (FANCESA, BFC, SAN LUCAS…): quedan marcados
`campos.tabla_no_parseada = true` para que el P2 (re-parseo de tablas del PDF) los
recupere. NO se intentó re-parsear acá (fuera de scope).

### Notas de infraestructura

- **`grupo_v` / `revisado`.** Cada item gana `grupo_v = TAXONOMIA_V` (=2; V1 = implícito,
  items sin el campo) y `revisado` (default `'provisional'`; `enriquecer` respeta un
  `'revisado'` previo vía `setdefault` — curación humana no se pisa). Habilita un pase
  futuro que re-clasifique selectivamente por versión.
- **`--reextraer` idempotente.** Verificado: dos corridas → archivos mensuales
  byte-idénticos (sólo cambia el timestamp `generado` del índice derivado).
- **pypdf lazy (parser.py).** `--reextraer` no baja ni parsea PDFs, pero importar
  `parser` traía `pypdf` a nivel de módulo → bloqueaba el pase en entornos sin la dep.
  Se movió el `import pypdf` adentro de `extraer_reporte()`. Esto NO afecta el fetch
  real; sólo permite re-clasificar sin la dependencia (y sin red).

### Bug pre-existente encontrado (fuera del alcance nominal, arreglado por aceptación)

- **`personal` no renderizaba.** El grupo `personal` estaba en el dropdown de temas
  (`TEMAS_LABEL`) pero NO tenía entrada en el array `GRUPOS` de `renderAsfi`. Como
  `renderGrupos` sólo pinta ids de `GRUPOS` + `otros`, los ~443 items `personal` de
  producción **desaparecían** del render (ni card ni lista Otros). La aceptación de este
  brief exige "ningún grupo desaparece", y esta tanda sube personal a 521 → se agregó la
  entrada `personal` a `GRUPOS` (cols entidad/persona/cargo/movimiento, `badgeMov`).

### Pendientes que deja esta tanda (para próximas)

- **Render de juntas realizadas.** 426/849 filas de `juntas` no extraen tipo/fecha/
  agenda (actas de Directorio); se pintan con fallback al resumen (`<td-span3>`). Es
  FUNCIONAL, no el diseño final — gate visual de Diego.
- **Residual `otros` = 750**, no ~186. El resto es genuino administrativo/misceláneo:
  resoluciones ASFI (cambios de denominación, tasas), cartas circulares "Ver Adjunto",
  poderes notariales, colocaciones primarias, reestructuras organizacionales, pagos de
  préstamo. Bajarlo más pediría grupos nuevos (poderes, resoluciones-administrativas,
  colocaciones) fuera del scope de 2a, o heurísticas de menor precisión. Se priorizó
  precisión sobre el número (instrucción del brief).
- **28 `tabla_no_parseada`** esperando el re-parseo de tablas del P2.

---

## 2026-07-13 — Fase 2a.1: extracción firma_auditora / gestión (grupo auditorias)

**Disparador.** En el grupo `auditorias`, `firma_auditora` (y varias `gestión`) mostraba
"—" aunque el nombre de la firma estaba en `texto`. Clasificación OK; el defecto era la
EXTRACCIÓN (`_RE_AUDITORA` / `_RE_GESTION` en `extract.py`, branch `auditorias` de
`extraer_campos`). Métrica: de 25 auditorias, **firma vacía 9 → 1**, **gestión vacía 9 → 0**,
cero falsos-positivos, cero capturas sucias. El único residual de firma es ausencia
genuina (Compañía Boliviana de Energía: "designación de la firma … para la gestión 2026"
— delegada, sin firma elegida).

**Learn-loop (3 intentos, el patrón anotado ANTES de reintentar):**

1. **Causa raíz — case-sensitivity.** `_RE_AUDITORA` era case-sensitive y el texto real
   alterna "firma de **A**uditoría **E**xterna" (mayúsculas). La rama "de auditoría
   externa" no matcheaba → la captura no arrancaba. Fix: trigger case-insensitive scoped
   `(?i:…)`, manteniendo la captura del nombre case-SENSITIVE (arranque en mayúscula).
   Además faltaban disparadores: "firma auditora", "empresa de auditoría externa",
   "con la empresa X". *Generalización:* separar la sensibilidad a mayúsculas del
   disparador (variable) de la del dato capturado (nombre propio, siempre mayúscula) es
   un patrón reusable para "entidad + sufijo legal" de cualquier fuente.

2. **FN nuevo — el nombre puede seguir DIRECTO al verbo-acto.** Al soltar los triggers de
   verbo ("elección/contratación/designación de X"), se perdieron AESA ("elección de
   PricewaterhouseCoopers S.R.L.") y 3 BNB ("contratación de BERTHINASSURANCE … S.R.L."):
   el firm sigue al verbo sin sustantivo "firma/empresa" intermedio. Fix: re-agregar el
   verbo-acto a la alternación (`(?:elección|contratación|designación)\s+de(?:\s+la)?
   (?:\s+(?:firma|empresa|consultora))?`).

3. **FP nuevo — captura sucia arrancando en la palabra-trigger.** El verbo-acto permitía
   que la captura arrancara en "**F**irma de Auditoría Externa Ruizmier… S.R.L." (mayúscula
   inicial) → arrastraba el prefijo (GRUPO FINANCIERO BISA). Fix: lookahead negativo
   `(?!(?:Firma|Empresa|Consultora|Auditoría)\b)` justo antes de la captura → fuerza el
   backtrack hasta que el trigger-sustantivo consuma el prefijo y la captura arranque en el
   nombre real. *Generalización:* cuando un trigger y el dato comparten vocabulario, un
   lookahead anti-trigger en el arranque de la captura evita el arrastre.

**Corte del nombre.** La captura corta en el sufijo legal (S.R.L./S.A./S.A.M./Ltda./LTDA)
o en coma/comilla — así no arrastra "para auditar los EEFF…" ni captura la entidad
auditada (que aparece después, con su propio sufijo). Firmas reales verificadas: Ruizmier
Pelaez, BerthinAssurance Group Auditoría & Consultoría, PricewaterhouseCoopers, Ernst &
Young (Auditoría y Asesoría) Ltda., Summa Consulting Group, Tudela & TH Consulting Group.

**Gestión.** Fallback `_RE_GESTION_FECHA` = "al 31 de diciembre de YYYY" (cierre fiscal =
gestión auditada) cuando no hay "gestión YYYY" explícito. Restringido a 31-dic para no
capturar fechas sueltas (dictamen, reunión). Explícita tiene prioridad.

**Punto 5 (promociones).** Escaneé `otros` por designaciones de auditor genuinas (firma
detectable + "auditoría externa" + acto, sin tag `junta`): **0 candidatos**. La mejora de
extracción no destapó ningún auditor mal clasificado → cero promociones, `auditorias`
sigue en 25 (distribución de grupos SIN cambios).

---

## 2026-07-13 — Fase 2b.1: piloto backfill gestión 2025 (extractivo, sin API)

**Qué.** Primer año histórico completo corrido por el pipeline: 247 reportes de 2025
(el probe 2b.0 confirmó que el listado no pagina), titulado 100% EXTRACTIVO
(`resumen.extracto`, cero Haiku/API), `grupo_v=2` + `revisado='provisional'`. Objetivo:
validar que la taxonomía v2 (calibrada sobre 2026) generaliza a data de otra gestión.
**5.913 items** en 247 días (~24/día). Descarga ~22,5 min vía proxy DataImpulse (4
errores de red transitorios —Read timeout/SSL/ChunkedEncoding— todos recuperados por
los reintentos de `_get`; 0 fallos reales). Idempotente (re-run = 0 nuevos, md5 idéntico).

**Veredicto de generalización: v2 SE SOSTIENE.** Distribución 2025 vs 2026:
`otros 25% (2025) vs 22,6% (2026)` · `juntas 25% vs 25,5%` · `cupones 18% vs 18,3%` ·
`personal 13% vs 15,7%`. Formas casi idénticas — la taxonomía no se rompe con redacción
no-2026. `otros` NO se infla.

### Gap sistemático de redacción vieja (candidato de ajuste ANTES de 2020-2024)

La brecha de ~2,4 pp de `otros` (25% vs 22,6%) se explica casi entera por **UN** patrón:

- **Verbo de préstamo: 2025 usa "adquirió un préstamo" / "bajo línea de crédito"** donde
  2026 usa "obtuvo/suscribió". `extract._RE_PRESTAMO_TXT` (obtuvo/suscribió/desembolso/
  otorgó) **no cubre "adquirió un préstamo" ni "línea de crédito"** → **~80 items** de 2025
  caen en `otros` que deberían ser `prestamos` (ej. "adquirió un préstamo del Banco BISA
  S.A. bajo línea de crédito por Bs…"). Con ese verbo agregado, `otros` 2025 bajaría a
  ~24% (≈ 2026). **Es el ajuste #1 a hacer antes de comprometer 2020-2024.**
  *Generalización:* el vocabulario de verbos-acto driftea por gestión; conviene ampliar
  `_RE_PRESTAMO_TXT` con sinónimos ("adquirió/contrató un préstamo", "línea de crédito",
  "crédito/financiamiento") y re-medir sobre 2025 antes de escalar.

- **Fin de relación laboral (menor, ~4 items):** 2025 usa "finalizó la vinculación
  laboral", "dejó de ejercer/prestar funciones", "cese de funciones" — `_RE_PERSONAL_VERBO`
  cubre "culminó relación laboral" pero no estas variantes → caen en `otros`. Bajo impacto
  pero mismo fenómeno de drift léxico.

- **Split de compromisos limpio en 2025:** 119 `compromisos_anunciados`, solo **1 posible
  FP** (una convocatoria de junta cuyo agenda menciona compromisos). Sin gap.

- **Auditorías (2a.1) funciona en 2025:** extrae `firma` (RUIZMIER PELAEZ, PwC) y `gestion`
  correctamente sobre redacción 2025 — la mejora de 2a.1 no era 2026-específica.

**Decisión:** NO ajusté regex (fuera de scope de 2b.1 — solo reportar). El ajuste de
`_RE_PRESTAMO_TXT` (+ opcional `_RE_PERSONAL_VERBO`) es brief aparte antes de 2020-2024.

---

## 2026-07-13 — Fase 2b.1b: taxonomía v2.1 (`TAXONOMIA_V 2→3`) — cierra el gap de 2b.1

**Qué.** Cerré los dos gaps de drift léxico que detectó el piloto 2025, sobre TODA la
data existente (2026 prod + 2025 branch), para consistencia. Sin scraping, sin API,
sin tocar títulos. Efecto (reextraer, por año):

| año | otros antes | otros después | prestamos | personal |
|---|--:|--:|--:|--:|
| **2025** | 1493 (25%) | **1419 (24%)** | 161→230 (+69) | 792→798 (+6) |
| **2026** | 759 (22%) | **723 (21%)** | 102→131 (+29) | 526→533 (+7) |

`otros` baja hacia paridad; 2026 (prod) también tenía el FN (~29 préstamos) → el fix
lo corrige en ambos. `grupo_v=3` + `revisado='provisional'` al 100%; `resumen_origen`
intacto (3052 'ia' de 2026 preservados, 2025 sigue 100% extractivo). Idempotente.

### Cambios (extract.py)

- **`_RE_PRESTAMO_TXT`** += `adquiri[óo] (un) (préstamo|línea de crédito|crédito)` +
  `adquirir …`. 2025/2026 usan "adquirió un préstamo del Banco X por Bs…" donde el
  vocabulario viejo (v2) solo tenía "obtuvo/suscribió/desembolso". Corta el monto igual
  que las otras ramas (via `_RE_MONTO_BS` en `extraer_campos`).
- **`_RE_PERSONAL_VERBO`** += `finalizó/concluyó la (relación|vinculación) laboral`,
  `dejó de (ejercer|prestar|desempeñar|pertenecer)`, `cese de (sus) funciones`.

### Decisiones de precisión (learn-loop)

- **FP-risk descartado por prioridad:** el préstamo puede convivir con emisiones/
  compromisos en el mismo texto, pero esos grupos van ANTES (prioridad 1-3); `prestamos`
  es prioridad 10 → solo captura lo que hoy cae a `otros`. Verificado: de los 69+29
  candidatos, **0 tienen tag `junta`** (sin colisión con asambleas). Todos extraen monto.
- **No agregué `línea de crédito` a secas** (solo "adquirió/suscribió … línea de
  crédito"): bare "línea de crédito" aparece en agendas de junta y daría FP. El piloto
  contó ~80 con el patrón laxo; el tight (verbo + objeto) da **69** genuinos.
- **1 `juntas→personal` (Telefónica, "reunión de Directorio … cese de funciones de
  Roberto Andino Pinto, Gerente General"):** NO es FP — es un cese de un cargo específico
  (sin tag junta), correcto en `personal`. Único matiz: la persona no se extrae porque el
  nombre viene sin "señor" ("cese de funciones de Roberto Andino") → fila algo sparse.
  Gap de extracción de `_RE_PERSONA` (no de clasificación); candidato menor, 1 item.
- **Fin-laboral sin `movimiento`:** las variantes nuevas no mapean a `_MOVIMIENTOS`
  (renuncia/desvinculación/…), así que esos personal rinden persona+cargo sin badge de
  movimiento. Aceptable (persona es el dato clave); ampliar `_MOVIMIENTOS` con
  "cese/fin de relación laboral" es mejora opcional futura.

---

## 2026-07-14 — Fase 2b.2: backfill histórico 2020-2024 (extractivo, sin API)

**Qué.** Los 5 años restantes por el mismo pipeline del piloto 2b.1: descarga vía proxy BO
en el VPS a `/tmp` scratch (código de main @#236, `TAXONOMIA_V=3`), titulado 100%
EXTRACTIVO (`--sin-ia` → `resumen.extracto`, cero Haiku/API), `grupo_v=3` +
`revisado='provisional'`. **19.958 items en 1.039 días.** Descarga ~76 min wall-clock,
~198 MB RX vía proxy (holgadamente <$1). Idempotente (gap-fill re-run = 0 nuevos).

**Veredicto de generalización: v3 SE SOSTIENE en 2020-2024.** `otros` por año: 2020 25,3% ·
2021 25,8% · 2022 24,8% · 2023 24,2% · 2024 25,2%, contra la referencia 2025 24,0% /
2026 21,5%. Banda 24-26%, pegada al baseline 2025; **el freno de decisión del brief NO se
dispara** (ningún año infla `otros` claramente). El leve tilt de 2020/2021 (~+1,8 pp sobre
2025) es residual genuino, no misclasificación (spot-check abajo). La forma completa de la
distribución es idéntica a 2025/2026 (juntas/otros/cupones top-3, ningún grupo colapsa).

### Spot-check estratificado 2020-2021 (años más viejos = mayor riesgo de drift)

`otros` es misc genuino, **mismas categorías que el residual 2a de 2026**, sin patrón nuevo
sistemático: resoluciones sancionatorias ASFI (`ASFI/NNN/AAAA … RESUELVE: Sancionar…`),
colocaciones primarias de bonos, incrementos de capital suscrito y pagado, cambios de
denominación / adendas a contratos de calificación, "Ver Adjunto" (tasas de regulación),
transferencias de acciones. Todas son las categorías que 2a dejó explícitamente como
residual precisión-sobre-número; NO son gaps de v3.

`prestamos` clasifica bien sobre redacción vieja, incluida la variante v2.1 "adquirió un
préstamo" (Ferroviaria Oriental 2021-02-01) — el fix de 2b.1b no era 2025-específico.
`campos.monto`/`campos.banco` se pueblan OK. `personal` correcto (renuncia/designación/cese).

### Patrón de redacción nuevo (candidato menor, NO dispara freno)

- **"retomó sus funciones"** (reincorporación de un cargo tras licencia; ej. Banco Mercantil
  Santa Cruz 2020-05-11, "el señor … retomó sus funciones como Vicepresidente Ejecutivo")
  no está en `_RE_PERSONAL_VERBO` → cae a `otros`. Bajo volumen (≈unidades). Candidato a
  ampliar el verbo-acto de personal ("retomó/reasumió funciones") en un brief de regex
  futuro; no material para el número de `otros`.

### Hueco de descarga upstream (NO taxonomía — fetch/ASFI)

- **2020, 2021, 2022 completos** (246/250/251 días ≈ todos los hábiles).
- **2023: 131/248 días · 2024: 161/250 días.** Faltan **117 (2023, nov-dic + tramos)** y
  **89 (2024, ene-mar)**: el visor devuelve determinísticamente un doc de 604 B
  **"Operación no permitida"** (ASP.NET con `__VIEWSTATE`) para esos GUIDs específicos,
  mientras los GUIDs vecinos sirven el PDF real. Diagnóstico: 6/6 fallos por GUID cookieless,
  6 exits distintos del pool residencial, **y con sesión válida** (cookie `cookiesession1`
  seteada visitando el listado) → sigue fallando. Un GUID bueno baja 3/3 cookieless en
  simultáneo. **No es rate-limit, ni proxy, ni sesión, ni reintento** — es una restricción
  upstream de ASFI sobre esos documentos. `descargar_pdf` valida `%PDF` y descarta (correcto:
  no persiste basura); el hueco queda visible ("huecos visibles, no rellenados"). Los años
  parciales se shippean como tales; recuperarlos pediría otra vía de acceso al documento
  (fuera del pipeline actual) — decisión del IJ.
- **Marca de incompletitud (cierre 2b.2, dentro de #237).** Regla del proyecto "gaps se
  muestran o se omiten, nunca en silencio": `reescribir_index` emite un bloque `cobertura`
  por año derivado de `LISTADO_ESPERADO` (tamaño del listado completo, `{2023:248, 2024:250}`)
  vs. días presentes → `faltantes` + `parcial`. `renderAsfi` (`notaParcial`) muestra una nota
  cuando el año/vista tocado es parcial. **Data-driven y self-correcting:** si un re-probe
  futuro rellena días, `faltantes` baja y la nota se apaga sola al regenerar el índice — sin
  texto hardcodeado por año. Copy placeholder en `asfi.parcial_nota` (i18n es/en), definitivo
  a gate de Diego.
