# Plan de mejoras — Dashboard P2P USDT/BOB (DDR Capital Partners)

## Contexto del proyecto

Trabajás sobre el dashboard estático del pipeline P2P USDT/BOB (Bolivia). Stack: Python (`dashboard.py`, 380 líneas) que renderiza `template.html` (~608 líneas, HTML + CSS + JS inline) consumiendo SQLite con ~610k filas. Charts en **Plotly.js vía CDN** (no Chart.js — confirmar en Discovery). Sirve como `index.html` por GitHub Pages.

Tres vistas temporales: Cada snapshot / Por hora / Por día. Sistema de temas existente (Claro / Beige / Oscuro / Negro / custom hasta 5). Paneles drag & drop con persistencia en `localStorage`. KPI row de 9 cards. 11 paneles + 2 tablas.

**No introducir frameworks nuevos ni dependencias.** Mantener HTML autocontenido + Plotly por CDN. JS vanilla. Si necesitás un helper, hacelo inline.

## Objetivo de esta tanda

Implementar 28 cambios + 1 gráfica nueva, en 7 fases con commits granulares. **Esperá OK antes de pasar de fase.** Después de Discovery, parás y reportás. Después del Plan detallado, parás y reportás. Implementás solo cuando confirme.

---

## Fase 1 — Discovery (sin cambios al código)

Leé y reportá:

1. **Librería de charts confirmada** (presumo Plotly por el contexto del proyecto, confirmá leyendo `template.html`).
2. **Inventario de paneles**: para cada uno de los 11 charts + 2 tablas listá: id/clase, qué series tiene (Compra / Venta / ambas / ninguna), qué función JS lo renderiza, si responde a la vista temporal activa.
3. **Mapa de data flow**: cómo `dashboard.py` arma el JSON que inyecta en `__DATA_PLACEHOLDER__`, qué tablas/queries usa de SQLite, dónde se aplican los agregados temporales (hourly/daily/per-snapshot).
4. **Estado de íconos**: ⤡ (ancho) y ⠿ (drag) — funcionan? Tienen handler? Cómo persisten estado.
5. **Auditoría visual del 29-abr** (commit `1dff213`): qué de lo que pide este plan ya está cubierto. Reportá colisiones.

**Reportá hallazgos en formato lista. Si encontrás inconsistencia con lo descrito acá, frená y preguntá.** No avanzar sin OK.

---

## Fase 2 — Plan detallado (sin cambios al código)

Una vez confirmado el Discovery, devolvé:

1. **Diff conceptual por archivo** (`dashboard.py`, `template.html`, posibles helpers nuevos): qué se agrega, qué se modifica, qué se borra.
2. **Firmas actuales → nuevas** para funciones JS que cambian.
3. **Riesgos identificados**: qué puede romper, qué tests manuales necesito hacer yo.
4. **Lista de commits propuestos** en orden, con mensajes en formato `tipo(scope): mensaje`.

Esperá OK antes de implementar.

---

## Fase 3 — Implementación: Bugs cosméticos sin dependencias

Estos son commits chicos, riesgo nulo. Hacelos en este orden:

### 3.1 Normalización de bancos (Ítem 9)

Mapeo en `dashboard.py` antes de inyectar el JSON:

```
"de Credito" → "Banco de Crédito BCP"
"de Bolivia" → "Banco de Bolivia"
"SantaCruz" → "Banco SantaCruz"
"TigoMoney" → "Tigo Money"
"SoliPagos" → "SoliPagos"
```

Si encontrás otros nombres mal formateados durante Discovery, sumalos al mapeo y reportá.

### 3.2 Formato de números (Ítems 8, 10, 25)

- Locale `es-BO` para todos los números: separador de miles `.`, decimal `,`. Pero como el dashboard ya usa formato con coma de miles inglesa en algunos lados, **confirmá en Discovery cuál es el estándar actual y unificá a uno solo** (preferencia: `1.203` estilo es-BO si no hay razón fuerte para mantener inglés).
- Trades/mes con miles consistente.
- Fassil y cualquier banco con cobertura `<0.05%` se muestra como `<0.1%` (Ítem 8).
- Columnas numéricas en tablas: `text-align: right` + `font-variant-numeric: tabular-nums` (Ítem 25).

### 3.3 Meta tags + footer profesional (Ítems 26, 28)

- `<meta name="description">` con descripción del dashboard.
- Open Graph tags (`og:title`, `og:description`, `og:type`).
- Footer con: "Fuente: Binance P2P · Última actualización del dataset: {timestamp} · DDR Capital Partners · v{version}". Versión hardcodeada por ahora (ej `v0.3.0`).

### 3.4 Tooltips en íconos + estados de carga (Ítems 20, 27)

- `aria-label` y `title` en ⤡ y ⠿ (aunque en Fase 5 ⤡ desaparece — ponéselos igual de paso para consistencia mientras viven).
- Banner/toast no intrusivo en top del dashboard si falla el fetch del JSON. Texto: "No se pudo cargar el dataset. Reintentando..." con retry automático cada 30s.

### 3.5 Tipografía y jerarquía (Ítems 13, 24)

- Unificar case en labels: o todo MAYÚSCULAS o todo sentence case. **Recomiendo sentence case en títulos de paneles, MAYÚSCULAS solo en labels de KPI** — definí en CSS y aplicá uniforme.
- Header del dashboard: bajar peso del título principal, subir contraste del subtítulo. Agregar línea adicional debajo del bloque "1565 snapshots..." con `Última snapshot: dd MMM, hh:mm` formato es-BO.

### 3.6 KPI grid responsive (Ítem 14)

`grid-template-columns: repeat(auto-fit, minmax(160px, 1fr))` reemplazando el grid fijo. Validar que no rompe layouts <1100px ni desktops grandes.

### 3.7 KPI Spread efectivo con unidad (Ítem 23)

Número grande: `0.0470 BOB`. Subtítulo: `0.46% del precio`.

### 3.8 Detalles tablas y heatmap (Ítems 21, 22)

- Heatmap: números dentro de celdas → contraste WCAG AA o moverlos a tooltip on hover (lo que sea más legible — decidí vos y reportá).
- Tabla "Cobertura por banco": barra de profundidad con color de acento + opacidad ~0.15-0.2 (no el mismo que el texto).

### 3.9 Franjas grises (Ítem 17)

Períodos sin captura: subir opacidad en oscuro a algo legible o usar patrón diagonal con SVG inline.

### 3.10 Theme switcher: editor en vivo + dedup (Ítem 18)

- Eliminar redundancia "Negro" vs "Oscuro" del submenú Otros (mantener uno, el otro fuera).
- Editor de temas: cada cambio de color se aplica con debounce 300ms a CSS vars + Plotly.react. **NO botón Guardar**: cambios persisten automáticamente al cerrar el editor o cambiar de tema.

**Commit cada subgrupo.** Mensajes propuestos:

```
fix(data): normalizar nombres de bancos a formato canónico
fix(format): unificar separadores de miles a es-BO + tabular-nums
feat(seo): meta description, og tags y footer profesional
feat(a11y): tooltips en iconos y estado de error con retry
style(typography): unificar case y mejorar jerarquía del header
fix(layout): KPI grid responsive con auto-fit
fix(kpi): unidad BOB visible en spread efectivo
style(panels): legibilidad heatmap y barras de cobertura
style(theme): franjas sin captura legibles en oscuro
feat(theme-editor): aplicar cambios en vivo, dedup Negro/Oscuro
```

---

## Fase 4 — Paleta semántica canónica (Ítems 15, 16)

Antes de tocar paneles nuevos, definí en `template.html` un bloque de CSS vars semánticas:

```css
--color-buy: <verde>;        /* Compra (taker compra USDT, maker vende) */
--color-sell: <naranja>;     /* Venta (taker vende USDT, maker compra) */
--color-bcb-oficial: <gris claro>;       /* punteado dashed */
--color-bcb-ref-compra: <azul oscuro>;
--color-bcb-ref-venta: <azul claro>;
--color-neutral: <gris>;     /* spread, ratio, métricas no direccionales */
```

Aplicar a TODOS los charts. Particularmente:
- Spread efectivo y Ratio Venta/Compra: dejar de usar azul, usar `--color-neutral` o un acento del tema.
- Las 3 líneas BCB en VWAP: aplicar las 3 vars con dash patterns distintos (`dash`, `dot`, `solid`) para diferenciarlas además del color.

**Cada tema (Claro / Beige / Oscuro / Negro / custom) debe definir estas vars.** El theme switcher las cambia.

Commit:
```
refactor(theme): paleta semántica canónica buy/sell/bcb/neutral
```

---

## Fase 5 — Bugs de cálculo

### 5.1 Columna "Anuncios" en Cobertura por banco (Ítem 7)

Confirmá en Discovery qué representa hoy (suma de todos los snapshots, último snapshot, etc.). **Decisión correcta: filtrar al último snapshot** para que cuadre con los KPIs activos arriba. Cambiar la query y el header de la columna a "Anuncios (último snapshot)" para que sea autoexplicativo.

### 5.2 Outlier detection en ranking de merchants (Ítem 11)

Para cada merchant en la tabla:
- Calcular VWAP global del lado correspondiente (Compra o Venta) sobre el rango activo.
- Calcular desviación absoluta % del merchant vs ese VWAP.
- Si `|desviación| ≥ 15%` → pill amarillo "outlier suave" en la fila.
- Si `|desviación| ≥ 20%` → pill rojo "outlier" en la fila.
- **No filtrar.** La data sigue visible. El usuario decide.

Tooltip en el pill: "VWAP {x} BOB — desviación {y}% vs mercado".

### 5.3 Decil 100 cae a 0 (Ítem 12)

**Decisión: toggle "Excluir percentiles extremos (1, 100)" activado por defecto.** Razón: los extremos son donde viven las trampas y los outliers, recortar el eje Y es disfrazar el problema. Toggle visible junto al título del panel para que el usuario pueda ver el data crudo si quiere.

### 5.4 Volatilidad intradiaria always-on (Ítem 5)

- Eliminar el mensaje "Cambiá a vista 'Por día'..." y la lógica que oculta el panel.
- Renderizar siempre, recalculando según vista activa:
  - Cada snapshot → desviación estándar rolling intra-día (ventana 6 snapshots ≈ 1h).
  - Por hora → desviación estándar de cada hora del día sobre el rango.
  - Por día → desviación estándar diaria sobre el rango.
- **Sin sub-selector de "desde qué día arranca"** — respeta el selector global de fechas (ver Fase 6).
- Empty-state si rango activo <3 días: "Necesita al menos 3 días de data en el rango seleccionado".

Commits:

```
fix(coverage): columna anuncios al último snapshot del rango
feat(merchants): outlier detection 15%/20% con pills semánticos
fix(deciles): excluir percentiles extremos por defecto + toggle
feat(volatility): renderizado always-on respetando vista activa
```

---

## Fase 6 — Estructura grande

Esta es la fase de mayor riesgo. Implementá **una sub-fase por vez** y reportá antes de la siguiente.

### 6.1 Selector global de fechas + presets

- UI: barra arriba del KPI row, antes del primer panel. Presets como chips: `24h | 7d | 30d | Todo` + calendario con `desde / hasta`.
- Valor por defecto: `Todo` (rango completo del dataset).
- Persistir en `localStorage` clave `dashboard-date-range` (formato `{from: ISO, to: ISO}` o `{preset: '7d'}`).
- Al cambiar el rango: recalcular TODOS los charts y KPIs (incluyendo VWAP fijos, KPI row, tablas, gráfica nueva).
- **Coherencia**: el "Última snapshot" del header siempre muestra la última snapshot del dataset completo, NO del rango seleccionado.

Commit:
```
feat(filter): selector global de fechas con presets y persistencia
```

### 6.2 VWAP fijos arriba del dashboard (Ítem 2)

- Bloque sticky o ancla, encima del KPI row.
- Dos cards grandes lado a lado: **VWAP 10% Compra** y **VWAP 10% Venta**, con cifra principal en BOB/USDT, debajo prima vs BCB Ref del lado correspondiente.
- Respeta selector global de fechas.
- NO forman parte del KPI grid de 9 cards (van fuera).

Commit:
```
feat(layout): VWAP 10% compra/venta fijos sobre el dashboard
```

### 6.3 Toggle sticky Compra / Venta / Ambas (Ítem 1)

- Componente flotante, sticky al scroll, esquina superior derecha por debajo del header.
- 3 checkboxes: `[ ] Compra  [ ] Venta  [ ] Ambas` (Ambas activa ambos otros).
- **Estado por defecto:** Ambas activas.
- Al cambiar: filtra series en TODOS los paneles donde apliquen Compra/Venta. Los paneles "neutros" (Spread, Ratio, Heatmap, Concentración) no responden al toggle.
- Persistir en `localStorage` clave `dashboard-side-filter`.
- Look profesional: acorde a la paleta canónica, no genérico.

Commit:
```
feat(filter): toggle sticky compra/venta con persistencia
```

### 6.4 Sistema unificado de panel: menú ⋮ + "Más gráficas" (Ítems 4, 19)

**Esta es la consolidación que acordamos.** Cambios:

- **Eliminar ícono ⤡** del header del panel.
- **⠿ se mantiene** como handle de drag, visible al hover sobre el header del panel.
- **⋮ es el menú único** con acciones:
  ```
  [Ocultar panel]
  [Ancho: ½ / completo]    ← toggle
  [Mover ↑]
  [Mover ↓]
  [Descargar PNG]
  [Descargar CSV]
  [Ordenar tabla...]        ← solo en paneles que son tablas (Ítem 19)
  ```
- Sort por click en headers de tablas (Cobertura por banco, Top 10 merchants).
- "Descargar PNG" usa `Plotly.downloadImage`. "Descargar CSV" exporta la data del panel desde el JSON inyectado.
- **Botón "Más gráficas"**: visible al final del grid o como FAB en esquina. Al click, muestra lista de paneles ocultos con checkboxes para mostrar/ocultar.
- **Paneles ocultos por defecto** (según tu plan): *Merchants activos, Cobertura por banco, Ratio Venta/Compra, Spread efectivo, Profundidad por lado*. Resto visible.
- Estado completo (visibilidad + orden + ancho de cada panel) persiste en `localStorage` clave `dashboard-panel-state`.

Commit:
```
feat(panels): sistema unificado de menú ⋮ con acciones consolidadas
feat(panels): paneles ocultables y reordenables con persistencia
feat(tables): sort por columna en tablas
```

### 6.5 Nueva gráfica: Oferta USDT por rango de precios (referencia: Image 2 que vio el usuario)

Panel nuevo, render por defecto visible. Tipo: **histograma (barras) + serie de línea con segundo eje Y**. Plotly soporta esto con `yaxis2`.

**Datos**: usar el **último snapshot del rango global seleccionado** (no promedio).

- Eje X: precio en BOB, en bins de 0.10. Rango razonable según data (ej 9.50 a 12.50).
- Eje Y izquierdo: **Monto USDT disponible** (suma de USDT en anuncios cuyo precio cae en el bin). Barras.
- Eje Y derecho: **Nro. de oferentes** (count distinct de merchants con anuncio en el bin). Línea con marcadores.
- Toggle de lado: respeta el toggle global Compra/Venta/Ambas. Si Ambas → mostrar dos histogramas (Compra y Venta) en colores semánticos, o un único histograma combinando ambos según preferencia (decidí en el Plan y reportá).
- Título: `OFERTA USDT POR RANGO DE PRECIOS Y CANTIDAD DE OFERENTES`.
- Subtítulo: `Último snapshot del rango seleccionado · {timestamp}`.

Commit:
```
feat(panels): nueva gráfica oferta USDT por rango de precios
```

### 6.6 Curva por decil con eje X en % y zoom natural (Ítem 6)

- Eje X: `decil * 10` (0%, 10%, ..., 100%) o más fino si tenés percentiles más granulares.
- **Reemplazar el rangeslider horizontal del fondo** por zoom nativo de Plotly:
  - `dragmode: 'zoom'` para zoom rectangular.
  - `scrollZoom: true` en config para wheel zoom.
  - Doble click resetea.
- **Eje Y ajustable**: agregar dos handles laterales (sliders verticales en CSS sobre el panel) para ajustar `yaxis.range` interactivamente, o botones `[Y auto] [Y recortado]` con preset de rango razonable. **Decidí en Plan y reportá** cuál es más limpio.

Commit:
```
feat(deciles): eje X en %, zoom nativo y control de rango Y
```

---

## Fase 7 — DoD verificable

Al cerrar todo, antes del commit final:

1. **Comando**: `python dashboard.py && open index.html` (o `start` en Windows).
2. **Output esperado**:
   - HTML > 1.4 MB (creció por nuevos paneles).
   - Sin errores en consola del browser.
   - Selector de fechas funcional, presets cambian rango.
   - Toggle sticky filtra todos los paneles direccionales.
   - VWAP fijos arriba reaccionan al selector.
   - Outliers en tabla merchants con pills correctos.
   - Volatilidad renderiza en las 3 vistas.
   - Nueva gráfica de oferta USDT visible y reactiva.
   - Decil con zoom natural, sin rangeslider del fondo.
   - Menú ⋮ con todas las acciones, ⤡ ya no existe.
   - "Más gráficas" muestra paneles ocultos por defecto.
   - Sort en tablas funcional.
   - Persistencia: refrescar la página mantiene tema, layout, rango de fechas, toggle de lado.
   - Tema oscuro: franjas sin captura visibles, líneas BCB diferenciables.
   - Footer profesional con timestamp.
3. **Reporte final**: tabla de los 29 cambios con estado [✓ / ✗ / Δ], comentario donde aplique, tamaño del HTML, número de commits, archivos tocados.

Commit final:
```
docs: actualizar HANDOFF.md con cambios de la tanda visual
```

---

## Restricciones globales

- **Sin frameworks nuevos.** No React, no Alpine, no Vue. JS vanilla.
- **Sin dependencias nuevas.** Plotly por CDN se mantiene.
- **Limpiar temporales.** Si creás archivos auxiliares para Discovery, borrá antes del commit final.
- **Commits granulares.** No mezcles cambios de fases distintas en un commit.
- **Si encontrás algo inconsistente con este plan durante Discovery o Plan**, frená y preguntá. No improvisés.
- **Idioma del UI siempre español.** Mensajes de commit en español también.
- **Calibrar threshold de outliers** sobre la data real durante Plan: si 15%/20% deja a más del 5% de merchants como outliers, repórtalo y discutimos antes de implementar.
