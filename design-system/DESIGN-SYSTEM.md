# FinanzasBo — Design System (paquete para attachear a Claude)

Dashboard financiero del USDT/BOB en Bolivia (Binance P2P + Banco Central + BBV).
Esta carpeta es un **extracto curado del frontend** para que diseñes una **nueva
tab de "Noticias"** que matchee el estilo de la página. No es el repo completo a
propósito: el repo trae una DB de >1 GB y HTML generados de 2 MB que solo son ruido.

## Archivos de esta carpeta

| Archivo | Qué es | Cómo usarlo |
|---|---|---|
| `design-reference.html` | **Galería de componentes renderizable.** Abrila en el navegador: muestra navbar, KPIs, cards, tablas, pills, tipografía con el CSS y los temas reales. Botón 🌙 alterna claro/oscuro. | Referencia visual rápida + base para extender. Tiene un placeholder marcado donde va la tab Noticias. |
| `template.snapshot.html` | **Copia fiel del template real** (`template.html`) que genera la página. Single source of truth del HTML/CSS/JS. | Ground truth. Para ver cómo están implementadas las otras tabs (Dólar, DPF, BBV) y replicar el patrón exacto. |
| `DESIGN-SYSTEM.md` | Este documento. | Orientación + spec de tokens y componentes. |

> El CSS (`<style>`) y el objeto `THEMES` de `design-reference.html` están copiados
> **verbatim** del template — son los valores reales, no una aproximación.

## Identidad visual (respetar)

- **Sobria, institucional, azul petróleo.** El color primario, el texto y el accent
  son el mismo azul `#2c4a6b`. NO usar verdes/rojos saturados tipo "trading app".
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

Escala de tamaños: `--text-2xs` (9.5px) · `--text-xs` (10.5) · `--text-sm` (11) ·
`--text-base` (12) · `--text-md` (13) · `--text-lg` (14) · `--text-xl` (16) ·
`--text-2xl` (18) · `--text-3xl` (22) · `--text-4xl` (26) · `--text-5xl` (28).

## Colores (tokens clave — `paper` / `slate`)

| Token | paper (claro) | slate (oscuro) | Uso |
|---|---|---|---|
| `--bg-primary` | `#f5f7fa` | `#0a1424` | fondo de página |
| `--bg-secondary` | `#ffffff` | `#122237` | cards, navbar, headers |
| `--bg-tertiary` | `#dde8ef` | `rgba(110,163,217,.15)` | hover, chips, tooltips |
| `--border-color` | `rgba(44,74,107,.10)` | `rgba(255,255,255,.10)` | bordes |
| `--text-primary` | `#2c4a6b` | `#e6ebf2` | texto principal |
| `--text-muted` | `#6b7d92` | `#8a96aa` | texto secundario / labels |
| `--blue-accent` | `#2c4a6b` | `#6ea3d9` | acentos, links, logo |
| `--color-buy` | `#1e4d7a` | `#5a8cc4` | lado compra |
| `--color-sell` | `#6b7d92` | `#8a9caf` | lado venta |

Paleta completa (incl. ~20 colores de charts por tema) en el objeto `THEMES` de
`design-reference.html` / `template.snapshot.html`.

Otros tokens: radios `--radius-xs`(3) → `--radius-xl`(10), `--radius-pill`(9999);
sombras `--shadow-sm/md/lg/xl`.

## Componentes (referencias a `template.snapshot.html`)

| Componente | Clases | Línea aprox. |
|---|---|---|
| Navbar + tabs | `.fb-navbar`, `.fb-tabs`, `.fb-tab`, `.fb-tab.active` | 458–477 / CSS 288–298 |
| Subheader de tab | `.fb-subheader`, `.fb-subtitle`, `.fb-stat` | 480–489 / CSS 302–308 |
| Fila de KPIs | `.kpi-row`, `.kpi`, `.kpi .label/.value/.sub` | 491 / CSS 118–126 |
| Card / panel | `.section`, `.section-header`, `.sh-left`, `.section-body` | 497–506 / CSS 134–137 |
| Tabla de datos | `.fb-data-table` (+ `.issuer`, `.rate-cell`, `.num`) | 566 / CSS 386–402 |
| Pills / etiquetas | `.pill` | CSS 170 |
| Tooltip de ayuda | `.help-tip`, `.help-icon`, `.help-pop` | CSS 228–232 |
| Chips / toggles | `.ds-chip`, `.side-chk` | CSS 268–279 |

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

El JS togglea la visibilidad por `data-tab` (ver `template.snapshot.html` ~2556–2575).

## 👉 Dónde enchufa la tab Noticias

- El botón **ya existe** en `template.snapshot.html:467`, hoy deshabilitado:
  `<button class="fb-tab" disabled>Noticias <span class="fb-soon">Soon</span></button>`
  → para activarla: quitar `disabled`, agregar `data-tab="noticias"`.
- Crear un `<div id="tab-noticias" style="display:none;">` hermano de `#tab-dolar`.
- Ruteo: `template.snapshot.html:2532` nota que `/noticias` cae al fallback porque la
  tab está disabled; al activarla habría que mapearla.
- **Concepto original** (`template.snapshot.html:784`): *"agregador de hechos
  relevantes ASFI/BBV y noticias macro relevantes para el contexto monetario
  boliviano."*

## Qué NO replicar / ignorar

- `index.html` y `p2p_dashboard.html` del repo → output generado con data (2 MB), ruido.
- Plotly y la config de charts → solo si la tab Noticias necesita gráficos; para una
  feed de noticias probablemente no.
- Cualquier color literal en hex → preferí siempre los tokens `var(--...)`.
