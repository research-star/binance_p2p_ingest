# FinanzasBo — Design System (paquete para attachear a Claude)

Dashboard financiero del USDT/BOB en Bolivia (Binance P2P + Banco Central + BBV).
Esta carpeta es un **extracto curado del frontend** — la fuente canónica del design
system para explorar layouts on-brand (futuro sync con Claude Design). No es el repo
completo a propósito: el repo trae una DB de >1 GB y HTML generados de 2 MB que solo
son ruido.

> **Regenerado contra `main` (navbar v3 / chrome editorial incluido).** La galería y el
> snapshot reflejan el estado real de `template.html`; ver `STATUS.md`.

## Archivos de esta carpeta

| Archivo | Qué es | Cómo usarlo |
|---|---|---|
| `design-reference.html` | **Galería de componentes renderizable.** Abrila en el navegador: muestra el chrome editorial **navbar v3** (utility + masthead + nav + buscador), KPIs, cards, tablas, pills, tipografía con el CSS y los temas reales. Botón de tema alterna claro/oscuro. | Referencia visual rápida + base para extender. Trae un sandbox de exploración al final. |
| `template.snapshot.html` | **Copia fiel del template real** (`template.html`) que genera la página. Single source of truth del HTML/CSS/JS. | Ground truth. Para ver cómo están implementadas las otras tabs (Dólar, DPF, BBV) y replicar el patrón exacto. |
| `DESIGN-SYSTEM.md` | Este documento. | Orientación + spec de tokens y componentes. |

> El CSS (`<style>`) y el objeto `THEMES` de `design-reference.html` están copiados
> **verbatim** de `template.html` (main) — byte-idénticos, no una aproximación. El
> `template.snapshot.html` es la copia fiel completa del mismo template.

## Identidad visual (respetar)

- **Sobria, institucional, azul petróleo.** El color primario, el texto principal y el
  accent son el mismo azul `#2c4a6b`; el texto secundario es gris-azulado `#6b7d92`. El
  fondo de página es un blanco frío `#fafbfe`. NO usar verdes/rojos saturados tipo "trading app".
- Densidad de información alta pero ordenada; tipografía chica (11–14px base).
- Dos temas: **`paper`** (claro, default) y **`slate`** (oscuro). Todo componente
  debe verse bien en ambos → usá **siempre variables CSS** (`var(--...)`), nunca
  colores literales hardcodeados.
- Números y datos en mono con `font-variant-numeric:tabular-nums`.

## Tipografía

| Rol | Familia | Variable | Uso |
|---|---|---|---|
| Display / títulos | **Outfit** | `--font-display` | h1, h2, labels, tabs, botones |
| Body / párrafos | **Inter** | `--font-body` | texto corrido, subtítulos |
| Mono / números | **IBM Plex Mono** | `--font-mono` | KPIs, tablas, timestamps |

Pesos cargados (un solo `<link>` Google Fonts): **Outfit** 300/400/500/600/700 ·
**Inter** 400/500/600/700 · **IBM Plex Mono** 400/500/600.

Escala de tamaños: `--text-2xs` (9.5px) · `--text-xs` (10.5) · `--text-sm` (11) ·
`--text-base` (12) · `--text-md` (13) · `--text-lg` (14) · `--text-xl` (16) ·
`--text-2xl` (18) · `--text-3xl` (22) · `--text-4xl` (26) · `--text-5xl` (28).
Token editorial extra: `--lead-size` (46px, titular líder de portada).

## Colores (tokens clave — `paper` / `slate`)

| Token | paper (claro) | slate (oscuro) | Uso |
|---|---|---|---|
| `--bg-primary` | `#fafbfe` | `#0a1424` | fondo de página |
| `--bg-secondary` | `#ffffff` | `#122237` | cards, navbar, headers |
| `--bg-tertiary` | `#dde8ef` | `rgba(110,163,217,.15)` | hover, chips, tooltips |
| `--border-color` | `rgba(44,74,107,.12)` | `rgba(255,255,255,.10)` | bordes |
| `--text-primary` | `#2c4a6b` | `#e6ebf2` | texto principal |
| `--text-secondary` | `#6b7d92` | `#e6ebf2` | texto secundario (navbar v3: navy→gris) |
| `--text-muted` | `#6b7d92` | `#8a96aa` | labels / metadata |
| `--blue-accent` | `#2c4a6b` | `#6ea3d9` | acentos, links, logo |
| `--color-buy` | `#1e4d7a` | `#5a8cc4` | lado compra |
| `--color-sell` | `#6b7d92` | `#8a9caf` | lado venta |

Paleta completa (incl. ~20 colores de charts por tema) en el objeto `THEMES` de
`design-reference.html` / `template.snapshot.html`.

Otros tokens: radios `--radius-xs`(3) · `--radius-sm`(4) · `--radius-md`(6) ·
**`--radius-lg`(2 — sharp editorial, FASE 3)** · `--radius-xl`(10) · `--radius-pill`(9999);
sombras `--shadow-sm/md/lg/xl`.

## Componentes (referencias a `template.html` = `template.snapshot.html`)

| Componente | Clases | Línea aprox. (markup / CSS) |
|---|---|---|
| **Chrome v3** (utility + masthead) | `.fb-chrome`, `.fb-utility`, `.fb-masthead`, `.fb-nameplate`, `.fb-tagline` | 629–646 / CSS 255–267 |
| Navbar + tabs | `.fb-navbar`, `.fb-tabs`, `.fb-tab`, `.fb-tab.active` (subrayado 2px) | 647–655 / CSS 269–275 |
| Buscador (disabled) | `.fb-nav-search`, `.fb-search` | 656–661 / CSS 276–280 |
| Subheader de tab | `.fb-subheader`, `.fb-subtitle`, `.fb-stat` | 665–674 / CSS 285–291 |
| Fila de KPIs | `.fb-kpi-wrap`, `.fb-kpi-grid` (+ `--5`), `.fb-kpi-card` | CSS 294–305 |
| Card / panel | `.section`, `.section-header`, `.sh-left`, `.section-body` | CSS 100–121 |
| Tabla de datos | `.fb-data-table` (+ `.issuer`, `.rate-cell`, `.num`) | CSS 393–409 |
| Pills / etiquetas | `.pill` (`.pill-red`, `.pill-yellow`) | CSS 136 |
| Tooltip de ayuda | `.help-tip`, `.help-icon`, `.help-pop` | CSS 193–199 |
| Chips / toggles | `.ds-chip`, `.side-chk` | CSS 307 / 232 |

## Cómo se arma una tab (gramática de layout)

```
<button class="fb-tab" data-tab="XXX">…</button>   ← botón en la navbar (.fb-tabs)
…
<div id="tab-XXX" style="display:none;">           ← contenedor, hermano de #tab-dolar
  <div class="fb-subheader"> h1 + subtitle + stats </div>
  <div id="kpis"></div>                            ← opcional
  <div class="content">
    <div class="panel-grid">
      <div class="section [full-width]"> … </div>   ← una o más cards
    </div>
  </div>
  <div class="footer"></div>
</div>
```

El JS togglea la visibilidad por `data-tab` (ver `ROUTE_MAP` / `activateTab` en el JS de `template.html`).

## 👉 La tab Noticias (ya en producción)

- La tab Noticias está **activa y es el landing**:
  `<button class="fb-tab active" data-tab="noticias">Noticias</button>` (`template.html:649`);
  su contenedor es `<div id="tab-noticias">`, hermano de `#tab-dolar`.
- Ruteo: `/` y `/noticias` mapean a la tab Noticias (`ROUTE_MAP` en el JS del template).
- El **buscador** del navbar v3 es net-new y está **deshabilitado**:
  `<input type="search" disabled placeholder="Buscar — próximamente">` (`template.html:659`).
- Para explorar nuevos layouts de portada on-brand, usá el **sandbox** de `design-reference.html`.

## Qué NO replicar / ignorar

- `index.html` y `p2p_dashboard.html` del repo → output generado con data (2 MB), ruido.
- Plotly y la config de charts → solo si la tab Noticias necesita gráficos; para una
  feed de noticias probablemente no.
- Cualquier color literal en hex → preferí siempre los tokens `var(--...)`.
