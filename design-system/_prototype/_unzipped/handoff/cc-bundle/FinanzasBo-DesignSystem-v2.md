# FinanzasBo · Design System v2 — "Dashboard navy + Outfit"

> **Estilo congelado.** Los Tweaks finales quedaron fijados en:
> **Paleta → `Dashboard (B)`** (navy frío sobre blanco) · **Titulares → `Outfit`** (display sans).
> Este documento convierte esa combinación de Tweaks en el **baseline único** del producto y le
> da a Claude Code (CC) las instrucciones para llevar **toda la página** a este estilo.
>
> **Alcance del cambio:** _cambio total_ en **Noticias** (hoy arranca en la paleta cálida "Editorial");
> _cambios mínimos_ en **Macro / Dólar / DPF / BBV** (su hoja `finanzasbo.css` ya vive en esta misma
> paleta navy — sólo hay que quitarle la capa de continuidad por `localStorage`).
>
> **Slots de imagen:** quedan como placeholders `.ft-imgph` (vacíos, con glifo de "foto"). Es lo esperado;
> la maqueta no trae imágenes reales. El markup del slot está documentado abajo para rellenarlo después.

---

## 0 · TL;DR para CC

1. **Congelar tokens:** en `ft-style.css`, reemplazar los defaults cálidos de `.ft-root` por el set navy de
   la sección **§2**. En `finanzasbo.css` no hay que tocar tokens (ya coinciden).
2. **Tipografía:** Outfit pasa a ser permanente. Añadir la clase `ft-font-sans` de forma fija al nodo raíz
   `.ft-root` **o** plegar las reglas de peso de §3 al baseline.
3. **Eliminar la capa de Tweaks:** borrar `tweaks-panel.jsx`, el bloque `PALETTES_A` / `BODY_BG` /
   `TWEAK_DEFAULTS` del entry de Noticias y el script de continuidad por `localStorage` en las páginas Macro.
4. **Fondo del lienzo:** `body { background:#eef1f5 }` (canvas interno = `--ft-paper:#f5f7fa`).
5. **Verificar** contra el checklist de §7.

---

## 1 · Qué cambia y qué no

| Zona | Archivo(s) | Estado hoy | Acción | Esfuerzo |
|---|---|---|---|---|
| **Noticias** (portada editorial) | `ft-style.css`, `a-noticias.html`, `ft-frontpage.jsx`, `ft-components.jsx` | Default = paleta cálida **Editorial** (parchment + tinta `#1B365D`), titulares serif **Newsreader** | **Cambio total:** baseline → navy frío + Outfit | Medio |
| **Macro / Dólar / DPF / BBV** | `finanzasbo.css`, `a-macro.html`, `Macroeconomia.html` | `:root` ya en navy frío (`#2c4a6b` / `#f5f7fa` / `#ffffff`); titulares Outfit | **Mínimo:** quitar el script de continuidad por `localStorage`; confirmar que la paleta de las series Plotly (`paper`) lee bien | Bajo |
| **Capa de Tweaks** | `tweaks-panel.jsx` y bloques `EDITMODE` | Activa (toggle de paleta/fuente) | **Eliminar** (ya no es configurable) | Bajo |

> La razón de fondo: la maqueta tenía **dos hojas**. `finanzasbo.css` (dashboard) ya nació navy; el toggle
> `Dashboard (B)` simplemente **proyectaba esa misma paleta sobre la capa editorial** `ft-style.css`. Congelar
> el sistema = hacer que `ft-style.css` arranque en esa proyección en lugar de en parchment.

---

## 2 · Tokens (valores congelados)

### 2.1 Capa editorial — `ft-style.css` → `.ft-root`

Estos son los valores **resueltos** de `Dashboard (B)`. Reemplazar el bloque de tokens de `.ft-root`
por exactamente esto:

```css
.ft-root{
  /* —— PALETA (congelada: Dashboard navy) —— */
  --ft-paper:      #f5f7fa;            /* lienzo / fondo de la portada */
  --ft-paper-2:    #ffffff;            /* banda / hover / superficies elevadas */
  --ft-ink:        #2c4a6b;            /* tinta de titulares (navy) */
  --ft-ink-2:      #2c4a6b;            /* navy secundario (== ink) */
  --ft-warm:       #6b7d92;            /* gris-azulado — deks / metadata */
  --ft-warm-soft:  #8c9aab;            /* gris-azulado suave — timestamps */
  --ft-accent:     #2c4a6b;            /* acento navy — kickers / puntos */
  --ft-accent-ink: #2c4a6b;            /* navy para enlaces sobre papel */
  --ft-line:       rgba(44,74,107,.12);
  --ft-line-strong:rgba(44,74,107,.24);
  --ft-up:         #7d9a86;            /* verde desaturado (sólo flechas ▲) */
  --ft-down:       #b08a82;            /* rojo desaturado (sólo flechas ▼)  */

  /* —— TIPOGRAFÍA (congelada: Outfit display) —— */
  --ft-headline:'Outfit',system-ui,sans-serif;
  --ft-ui:'Inter',-apple-system,system-ui,sans-serif;

  --ft-lead-size:46px;
  --ft-river-gap:14px;

  background:var(--ft-paper);
  color:var(--ft-ink);
  font-family:var(--ft-headline);
  -webkit-font-smoothing:antialiased;
  text-rendering:optimizeLegibility;
}
```

> ⚠️ **Diferencia clave vs Editorial:** antes `--ft-ink` era `#1B365D` (marino oscuro) distinto de
> `--ft-accent` `#2c4a6b`. En v2 **todo el navy colapsa a `#2c4a6b`** — titulares, acentos y enlaces
> comparten un solo tono. Es intencional (lo que se ve en la maqueta congelada). Si más adelante se
> quiere recuperar contraste en titulares, subir `--ft-ink` a `#1f3a5c` es el único cambio necesario.

### 2.2 Fondo de página

```css
html, body { background:#eef1f5; }   /* el lienzo .ft-root usa --ft-paper:#f5f7fa por dentro */
```

### 2.3 Capa dashboard — `finanzasbo.css` → `:root` (ya correcta, NO tocar)

Confirmar que estos valores siguen presentes (son los que el toggle replicaba). **No requieren cambios:**

```css
:root{
  --bg-primary:#f5f7fa; --bg-secondary:#ffffff; --bg-tertiary:#dde8ef;
  --border-color:rgba(44,74,107,0.10);
  --text-primary:#2c4a6b; --text-secondary:#2c4a6b; --text-muted:#6b7d92; --text-soft:#8c9aab;
  --blue-accent:#2c4a6b;
  --font-display:'Outfit',system-ui,sans-serif;
  --font-body:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  --font-mono:'IBM Plex Mono',monospace;
}
```

> El modo `body.theme-dark` de `finanzasbo.css` se conserva tal cual (es ortogonal al congelamiento; el
> claro es el default y es lo que pide la maqueta).

### 2.4 Tabla de referencia rápida

| Rol | Token editorial | Token dashboard | Hex |
|---|---|---|---|
| Lienzo | `--ft-paper` | `--bg-primary` | `#f5f7fa` |
| Superficie / card | `--ft-paper-2` | `--bg-secondary` | `#ffffff` |
| Fondo de página | — | — | `#eef1f5` |
| Tinta / titular | `--ft-ink` / `--ft-ink-2` | `--text-primary` | `#2c4a6b` |
| Acento / enlace | `--ft-accent` / `--ft-accent-ink` | `--blue-accent` | `#2c4a6b` |
| Texto secundario | `--ft-warm` | `--text-muted` | `#6b7d92` |
| Texto terciario | `--ft-warm-soft` | `--text-soft` | `#8c9aab` |
| Regla fina | `--ft-line` | `--border-color` | `rgba(44,74,107,.12)` |
| Regla fuerte | `--ft-line-strong` | — | `rgba(44,74,107,.24)` |
| Sube (▲) | `--ft-up` | — | `#7d9a86` |
| Baja (▼) | `--ft-down` | — | `#b08a82` |

---

## 3 · Tipografía

| Familia | Uso | Carga (Google Fonts) |
|---|---|---|
| **Outfit** (400/500/600/700) | **Titulares, nameplate, KPIs grandes, números de ranking** | display |
| **Inter** (400/500/600/700) | UI: kickers, chips, nav, metadata, dateline, labels | body / UI |
| **IBM Plex Mono** (400/500/600) | Cifras tabulares en tablas densas / terminal (donde aplique) | mono |

Tag de carga (mantener en `<head>` de cada página):

```html
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
```

> Newsreader (serif) **ya no se carga**. Se puede borrar del `<link>` de fuentes en todas las páginas.

### 3.1 Ajustes de peso al usar Outfit (importante)

Outfit es más ligero ópticamente que la serif, así que los titulares suben de peso. Antes vivían bajo
`.ft-root.ft-font-sans`; al congelar, deben ser **baseline**. Dos caminos (elegir uno):

**Opción A (recomendada, mínima):** añadir la clase `ft-font-sans` de forma permanente al nodo raíz.
- En `ft-frontpage.jsx` el wrapper ya es `<div className={…}>`; fijarlo a `"ft-root ft-font-sans"`.
- En `a-macro.html` / `Macroeconomia.html`, el `<div class="ft-root">` pasa a `<div class="ft-root ft-font-sans">`.

**Opción B (limpieza):** plegar estas reglas al baseline y borrar el prefijo `.ft-font-sans`:

```css
.ft-nameplate   { font-weight:700; letter-spacing:-.03em; }
.ft-ml-title    { font-weight:600; letter-spacing:-.02em; }
.ft-lead-title  { font-weight:600; letter-spacing:-.03em; }
.ft-sec-title   { font-weight:600; }
.ft-story-title { font-weight:600; }
.ft-card-title  { font-weight:600; letter-spacing:-.02em; }
```

### 3.2 Escala (ya definida en las hojas, sin cambios)

`--text-2xs:9.5 · --text-xs:10.5 · --text-sm:11 · --text-base:12 · --text-md:13 · --text-lg:14 · --text-xl:16 · --text-2xl:18 · --text-3xl:22 · --text-4xl:26 · --text-5xl:28` (px).
Titular líder editorial `--ft-lead-size:46px`. Mínimo de cuerpo en pantalla: 11px (metadata) / 13–16px (lectura).

---

## 4 · Componentes (referencia de la portada Noticias)

Todos viven bajo `.ft-root` en `ft-style.css`. **No cambia la estructura, sólo heredan los tokens nuevos.**
Lista para que CC verifique que cada bloque sigue leyendo correctamente tras el swap:

- **Franja utilitaria** `.ft-utility` — fecha · "Actualizado HH:MM" con punto live `--ft-up` · toggle ES/EN.
- **Masthead** `.ft-masthead` / `.ft-nameplate` — "Finanzas**Bo**", reglas `.r1` (2px navy) + `.r2` (1px línea).
- **Nav** `.ft-nav` — tabs `Noticias · Macro · Dólar · Rendimientos DPF · BBV · Guía`; activo con subrayado 2px navy.
- **Chips de categoría** `.ft-chips` / `.ft-chip` — pill outline; estado `.on` = relleno navy, texto papel.
- **Markets strip** `.ft-markets` — grid de indicadores, borde inferior 2px navy; flechas `--ft-up/--ft-down`.
- **Bloque líder + secundarias** `.ft-top` / `.ft-lead` / `.ft-secs` — titular `--ft-lead-size`, dek, dateline, slot de imagen.
- **Río en tarjetas** `.ft-river-cards` / `.ft-card` — grilla 3-col (4 en denso); kicker Inter, título Outfit 600.
- **Right rail** `.ft-rail` — "Más leídas" (ranking con número Outfit), "Agenda", "Digest Latam".
- **Banda Latam** `.ft-latam` — fondo `--ft-paper-2`, 5 columnas con borde-izq de regla.
- **Footer** `.ft-footer` — portales de prensa + nota metodológica.
- **Macro** (`finanzasbo.css` + `a-macro.html`): subheader serif→Outfit, sub-nav `Riesgo | Inflación | PIB`,
  KPI cards `.fb-kpi-*`, chart card `.fb-chart-*`, toggles de serie `.fb-stog`, rango `.ds-chip`, gráfico Plotly.

---

## 5 · Slots de imagen (placeholders vacíos)

Es correcto que queden **vacíos**. El placeholder es `.ft-imgph`: gradiente navy + glifo de cámara + etiqueta.
Markup actual (componente `ImgPh` en `ft-components.jsx`):

```html
<figure class="ft-figure">
  <div class="ft-imgph">                       <!-- añadir .sm para 4:3, p.ej. en secundarias -->
    <span class="ft-imglabel">Mercado cambiario · La Paz</span>
  </div>
  <figcaption class="ft-figcap">Texto de epígrafe opcional.</figcaption>
</figure>
```

**Para rellenar con foto real más adelante** (no requerido ahora): reemplazar el `<div class="ft-imgph">`
por `<img src="…" class="ft-img" alt="…">` con el mismo `aspect-ratio`, o setear la imagen como
`background-image` del propio `.ft-imgph` (el glifo `::after` se oculta solo si hay imagen). Conservar
`aspect-ratio:16/9` (cards/lead) y `1/1` (slot cuadrado de secundarias) para no romper la grilla.

---

## 6 · Instrucciones de migración para CC (paso a paso)

### Paso A — Tokens baseline
- [ ] `ft-style.css`: reemplazar el bloque de tokens de `.ft-root` por el de **§2.1**.
- [ ] Añadir `html,body{background:#eef1f5}` (§2.2).
- [ ] `finanzasbo.css`: **sin cambios de tokens** (§2.3). Sólo confirmar que `:root` mantiene navy.

### Paso B — Tipografía permanente
- [ ] Aplicar **Opción A o B** de §3.1 (Outfit fijo + pesos de titular).
- [ ] Actualizar el `<link>` de fuentes a §3 (quitar `Newsreader`, mantener Outfit/Inter/Plex Mono).

### Paso C — Eliminar la capa de Tweaks
- [ ] Borrar el `<script src=".../tweaks-panel.jsx">` y el archivo `tweaks-panel.jsx`.
- [ ] En el entry de Noticias (`a-noticias.html` → su equivalente en prod), borrar el bloque
      `TWEAK_DEFAULTS` / `PALETTES_A` / `BODY_BG` y el uso de `useTweaks` / `<TweaksPanel>`.
      El render queda simplemente:

```jsx
ReactDOM.createRoot(document.getElementById('root')).render(
  <div className="ft-root ft-font-sans">
    <window.FrontPage mode="desktop" layout="cards" />
  </div>
);
```

- [ ] En `a-macro.html` / `Macroeconomia.html`, **borrar el IIFE de continuidad** que lee
      `localStorage.getItem('fb-a-palette' / 'fb-a-font')` y aplica overrides — ya no hace falta,
      la paleta navy es el default. Dejar el `<div class="ft-root ft-font-sans">` fijo.

### Paso D — Noticias (cambio total): verificación visual
Tras Pasos A–C, la portada editorial ya hereda navy + Outfit. Revisar que:
- [ ] Titulares en Outfit 600/700, sin rastro de serif.
- [ ] Fondo `#f5f7fa`, cards/banda Latam en `#ffffff`, reglas navy translúcidas.
- [ ] Kicker/acentos/enlaces en `#2c4a6b`; flechas de mercado en sage/rose.
- [ ] Slots `.ft-imgph` vacíos con glifo (esperado).

### Paso E — Macro / Dólar (cambios mínimos)
- [ ] Confirmar que la paleta de series Plotly usa el set **`paper`** (claro), no `slate` (dark).
      (`palette(key)` selecciona por `body.theme-dark`; en claro devuelve `paper` → protagonista `#1B365D`,
      el resto navys/neutros). Se ve bien sobre `#f5f7fa`; **no cambiar**.
- [ ] KPI cards, toggles y chips ya usan `--ft-*` / `--text-*` → heredan automáticamente.
- [ ] El subheader `<h1>` usa `var(--ft-headline)` → ahora Outfit (correcto).

---

## 7 · Checklist de aceptación

- [ ] No queda ningún toggle de Tweaks visible ni en el DOM.
- [ ] No se carga la fuente Newsreader en ninguna página.
- [ ] Noticias y Macro comparten exactamente el mismo navy `#2c4a6b` y fondo `#f5f7fa` / página `#eef1f5`.
- [ ] Titulares en Outfit en ambas secciones; UI/metadata en Inter.
- [ ] Las páginas Macro ya **no** leen `localStorage` para la paleta.
- [ ] Slots de imagen presentes como placeholders (vacíos) sin romper grillas.
- [ ] Modo `theme-dark` del dashboard sigue intacto (no es parte del congelamiento).

---

### Anexo · Mapa de archivos del prototipo

| Archivo | Rol |
|---|---|
| `a-noticias.html` | Entry de la portada Noticias (React/Babel) — **fuente del estilo congelado** |
| `ft-style.css` | Capa editorial (tokens `--ft-*` + componentes de portada) |
| `ft-frontpage.jsx` / `ft-components.jsx` | Componentes de la portada |
| `news-data-2.js` | Data sintética de noticias |
| `a-macro.html` / `Macroeconomia.html` | Página Macro (Plotly) |
| `finanzasbo.css` | Tokens + componentes del dashboard (ya navy) |
| `tweaks-panel.jsx` | Capa de Tweaks — **a eliminar** |
