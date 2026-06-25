# FinanzasBo — Design System (paquete para attachear a Claude)

Dashboard financiero del USDT/BOB en Bolivia (Binance P2P + Banco Central + BBV).
Esta carpeta es un **extracto curado del frontend** — la fuente canónica del design
system para explorar layouts on-brand (futuro sync con Claude Design). No es el repo
completo a propósito: el repo trae una DB de >1 GB y HTML generados de 2 MB que solo
son ruido.

> **Spec sincronizado al reskin editorial cálido (#81/#83).** Las tablas de identidad,
> paleta y tokens de abajo reflejan el estado real de `template.html` (paleta CÁLIDA,
> tema único `paper`, sin slate/dark-mode). ⚠️ La galería (`design-reference.html`) y el
> snapshot (`template.snapshot.html`) siguen **congelados en navbar v3 (paleta fría)** y
> quedan **pendientes de regenerar** (requiere tocar HTML, fuera de este sync de docs);
> ver `STATUS.md`.

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

- **Editorial cálida, broadsheet — tinta sobre papel.** El fondo de página es un papel
  cálido `#FBEDE3`; las superficies (cards, navbar, headers) `#FFF7F0`; los hovers/chips
  `#F3E0D2`. La tinta principal es un casi-negro cálido `#211E1B`. El ticker "El día en
  cifras" y los paneles editoriales `.np-*` usan una franja oscura **cálida** `#2A251F`
  (chrome scopeado, **no** un tema oscuro). El acento de marca / links sigue siendo azul
  petróleo `#2c4a6b`. Las flechas de mercado van en verde/rojo **desaturados**; NO usar
  verdes/rojos saturados tipo "trading app".
- Densidad de información alta pero ordenada; tipografía chica (11–14px base).
- **Tema único `paper`** (claro). El modo oscuro / `slate` fue **eliminado** —
  `applyTheme()` fuerza `paper` siempre ([template.html:1445](template.html#L1445)). Todo
  componente usa **variables CSS** (`var(--...)`), nunca colores literales hardcodeados.
- Números y datos en mono con `font-variant-numeric:tabular-nums`.

## Tipografía

| Rol | Familia | Variable | Uso |
|---|---|---|---|
| Display / titulares | **Newsreader** (serif) | `--font-display` | h1, h2, titulares, labels, tabs |
| Body / párrafos | **Inter** | `--font-body` | texto corrido, subtítulos |
| Mono / números | **IBM Plex Mono** | `--font-mono` | KPIs, tablas, timestamps |

Pesos cargados (un solo `<link>` Google Fonts, [template.html:25](template.html#L25)):
**Newsreader** 400/500/600/700 · **Inter** 400/500/600/700 · **IBM Plex Mono** 400/500/600 ·
**Outfit** 400 — relegado a labels/leyendas de Plotly; ya no es la cara tipográfica principal.

Escala de tamaños: `--text-2xs` (9.5px) · `--text-xs` (10.5) · `--text-sm` (11) ·
`--text-base` (12) · `--text-md` (13) · `--text-lg` (14) · `--text-xl` (16) ·
`--text-2xl` (18) · `--text-3xl` (22) · `--text-4xl` (26) · `--text-5xl` (28).
Token editorial extra: `--lead-size` (39px, titular hero de portada Noticias).

## Colores (tokens clave — tema único `paper`, valores de `THEMES.paper`)

Tema único `paper`; los valores son los que `applyTheme()` escribe en runtime desde
`THEMES.paper` ([template.html:1390](template.html#L1390)). La columna slate quedó eliminada
con el dark-mode.

**Paleta de página (cálida):**

| Token | Valor | Uso |
|---|---|---|
| `--bg-primary` | `#FBEDE3` | fondo de página (papel cálido) |
| `--bg-secondary` | `#FFF7F0` | cards, navbar, headers |
| `--bg-tertiary` | `#F3E0D2` | hover, chips, tooltips |
| `--border-color` | `rgba(33,30,27,.12)` | bordes |
| `--text-primary` | `#211E1B` | texto principal (tinta casi-negra cálida) |
| `--text-secondary` | `#6B6256` | texto secundario |
| `--text-muted` | `#766C5C` | labels / metadata |
| `--text-soft` | `#9E927C` | timestamps / texto terciario |

**Chrome oscuro cálido** (scopeado a componentes, NO es un tema): `#2A251F` en el ticker
(`.fb-ticker --tk-bg`) y en los paneles editoriales `.np-*` (hero Latam, placeholders de
imagen, rail/rank-band, botones admin).

**Acentos y mercado:**

| Token | Valor | Uso |
|---|---|---|
| `--blue-accent` | `#2c4a6b` | acentos UI, links, logo (azul petróleo — sobrevive el reskin) |
| `--color-buy` | `#0F5499` | lado compra |
| `--color-sell` | `#990F3D` | lado venta (claret) |
| `--up` / `--down` | `#688470` / `#A57067` | flechas de mercado (verde/rojo desaturados) |
| `--color-accent-warm` | `#FF8833` | acento cálido (realces) |

**Tokens de chart (conservan la paleta azul — VIGENTES, no son drift):** los gráficos
Plotly mantienen su paleta cromática propia dentro de `THEMES.paper` — p. ej.
`--chart-spread-line` `#2c4a6b`, rampa heatmap `--chart-heatmap-0..100` (`#dde8ef`→`#162844`),
`--chart-color-*` (EMBI, 10 países), `--chart-dpf-*`, `--chart-debt-*`, `--chart-ipc-*` /
`--chart-ipp-*`. Son la identidad cromática de los charts y se preservan tal cual.

Paleta completa (~80 tokens chart/tooltip/noticias del tema `paper`) en el objeto `THEMES`
de `template.html` ([L1390](template.html#L1390)).

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
