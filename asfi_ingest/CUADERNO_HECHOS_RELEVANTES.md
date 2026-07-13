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
