# CLAUDE.md — Proyecto Binance P2P USDT/BOB

Este archivo es leído automáticamente por Claude Code cada sesión. Contiene
el contexto persistente del proyecto. El estado actual, decisiones históricas
y TODO list viven en `HANDOFF.md`.

---

## Perfil del usuario (aplica siempre)

- IQ ~135, TDAH. Capta rápido lo conceptual pero se pierde con respuestas densas
  o mal estructuradas. Necesita estructura visual clara y un resumen arriba.
- Background: Sabe finanzas, cursó econometría 1-4 con buenas notas, pero lleva
  ~1 año sin practicar. Sabe los conceptos, está oxidado en el detalle fino.
  Explica en sencillo primero, sin tratarlo como principiante.
- Idioma: Español siempre.
- Valora: excelencia, proactividad, honestidad, desacuerdos razonados, que le
  preguntes ante ambigüedad, criterio propio.
- Dislikes: respuestas genéricas, asumir sin preguntar, sumisión sin pensamiento
  propio.
- Contexto geográfico: vive en La Paz, Bolivia. Le interesa especialmente el
  mercado P2P boliviano y sus particularidades.

## Protocolo de comunicación (TODAS las respuestas)

1. **"En sencillo"** — 3-6 líneas: qué entendiste y qué vas a hacer. Sin jerga.
2. **Cuerpo** — el trabajo real (estado del proyecto, análisis, código, etc.).
3. **"Qué revisar tú"** — 1-3 puntos donde necesitas su criterio antes de seguir.

## Objetivo del proyecto (resumen ejecutivo)

Entender y mapear el mercado P2P de USDT/BOB en Binance a través de la captura
sistemática de snapshots del libro de anuncios. El foco es **comprender la
estructura del mercado**, no calcular "el precio justo" ni operar. Pipeline de
3 fases:

1. **Ingesta** — traer data cruda cada ~10 min, guardar sin transformar.
2. **Normalización** — aplanar los snapshots a una tabla larga consultable.
3. **Análisis** — métricas, VWAPs, series temporales, visualizaciones.

Principio clave: **lo crudo es irrecuperable, lo derivado se recalcula**. Fase 1
guarda todo, aunque no se use hoy, porque cualquier análisis futuro lo necesita.

## Filosofía técnica del proyecto

- **No filtrar en origen.** El usuario quiere ver todo el libro, no una vista
  sesgada. Los filtros (KYC, merchant-only, por banco, etc.) viven en Fase 2
  como vistas sobre la data cruda, no como parámetros del request.
- **Banco como tag, no como filtro.** El banco que acepta un anuncio es metadata
  para etiquetar y comparar, no un criterio para excluir. Un anuncio puede
  aceptar varios bancos a la vez.
- **Separación estricta de fases.** La ingesta es aburrida y estable; el análisis
  es caótico y experimental. Nunca mezclarlos. Bugs en fase N no deben contaminar
  data de fase N-1.
- **Huecos visibles, no silenciosos.** Si un request falla, se registra como
  hueco explícito con error. Nunca desaparece en silencio.
- **Calibración sobre el terreno.** Cualquier umbral numérico (percentiles, tiers
  de calidad de merchant, qué cuenta como "anuncio serio") debe calibrarse con
  data real boliviana, no con defaults copiados de otros mercados.

## Estado muy breve

- **Fase 1 (Ingesta):** ✅ Completa. ~640 snapshots acumulados (10–15 abr
  2026), corriendo en local con `ingest.py --loop`. `watchdog.py` detecta si
  el loop se cae y lo relanza (cada 5 min vía Task Scheduler).
- **Fase 2 (Normalización):** ✅ Completa. `normalize.py` lee de local +
  directorio de backup opcional (`$P2P_BACKUP_DIR`), deduplica, produce SQLite
  con `quality_tier` A/B/C.
  0 restricciones estructuradas y 0 KYC keywords en todo el libro boliviano.
- **Fase 3 (Dashboard):** 🟢 Sustancialmente construida. `dashboard.py`
  genera HTML autocontenido (~583 KB) con 11 paneles (VWAP, spread,
  profundidad, deciles, ratio, concentración, bancos, top merchants,
  volatilidad, flujo, heatmap). Features: 3 vistas temporales, sistema de
  temas con presets + custom guardables, paneles drag & drop, BCB referencial
  scrapeado (`bcb_referencial.py`) como KPI + serie temporal. Ver `HANDOFF.md`.
- **Hosting:** pendiente (Oracle Free vs Hetzner €4/mes). Corre en local por
  ahora. GitHub Pages para servir el dashboard también pendiente.

**Corrección importante:** El `tradeType` de Binance P2P es desde la
perspectiva del **taker**, no del maker. BUY = taker compra USDT (maker vende),
SELL = taker vende USDT (maker compra).

Para todo lo demás, leer `HANDOFF.md`.

---

## Reglas de coordinación (agregado automáticamente)

Sección agregada por un setup automatizado para habilitar colaboración vía GitHub. El contenido anterior de este archivo no fue modificado.

### ANTES de empezar a trabajar
1. Hacé `git pull` para tener la última versión
2. Creá una branch descriptiva: `feature/nombre-corto` o `fix/nombre-corto`
3. Revisá si hay branches activas de otros para no pisar trabajo

### MIENTRAS trabajás
- Commits frecuentes y descriptivos (no "changes" ni "update")
- Si tocás un archivo que otro podría estar editando, mencionalo en el commit
- NO modifiques este CLAUDE.md sin avisar al equipo

### AL TERMINAR
1. Pusheá tu branch: `git push origin tu-branch`
2. Abrí un Pull Request con descripción clara de qué hiciste y por qué
3. No mergees a main sin review de al menos una persona

### Qué NO hacer
- NO hagas push directo a `main`
- NO commitees archivos `.env`, credenciales, o secretos
- NO borres ni renombres archivos compartidos sin avisar
- NO instales dependencias nuevas sin documentarlo

### Convención de commits
Formato: `tipo: descripción corta`
Tipos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`
Ejemplo: `feat: agregar endpoint de autenticación`
