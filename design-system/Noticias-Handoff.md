# FinanzasBo · Noticias — Handoff de implementación

> Export de referencia del mockup (artefacto HTML/React/Babel). **La variante elegida es la D ("Terminal · tabla densa")** — las variantes A/B/C/E se incluyen en el source porque forman parte del artefacto, pero la spec de interacciones describe la D, que es la tab a implementar.
>
> Nota: el archivo `design-canvas.jsx` (lienzo de artboards con pan/zoom) es tooling del entorno de diseño, **no** parte del diseño; se omite. En producción, el contenido de `VariantD` se monta directo como página.

---

## 1 · Source completo (verbatim)

### 1.1 `Noticias.html` — entry point (carga de la página y artboards)

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FinanzasBo — Noticias · variantes</title>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="finanzasbo.css">
<style>
  html,body{margin:0;height:100%}
  /* el canvas tiene su propio bg; las variables FinanzasBo viven en :root */
</style>
<template id="__bundler_thumbnail">
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" fill="#2c4a6b"/><g fill="#fff"><rect x="22" y="30" width="56" height="7" rx="2"/><rect x="22" y="44" width="56" height="5" rx="2" opacity=".6"/><rect x="22" y="54" width="56" height="5" rx="2" opacity=".6"/><rect x="22" y="64" width="40" height="5" rx="2" opacity=".6"/></g></svg>
</template>
</head>
<body>
<div id="root"></div>

<script src="https://unpkg.com/react@18.3.1/umd/react.development.js" integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L" crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js" integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm" crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js" integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y" crossorigin="anonymous"></script>

<script src="news-data.js"></script>
<script type="text/babel" data-presets="react" src="design-canvas.jsx"></script>
<script type="text/babel" data-presets="react" src="shared.jsx"></script>
<script type="text/babel" data-presets="react" src="variant-a.jsx"></script>
<script type="text/babel" data-presets="react" src="variant-b.jsx"></script>
<script type="text/babel" data-presets="react" src="variant-c.jsx"></script>
<script type="text/babel" data-presets="react" src="variant-d.jsx"></script>
<script type="text/babel" data-presets="react" src="variant-e.jsx"></script>

<script type="text/babel" data-presets="react">
const NW = 1180;

function App(){
  const { DesignCanvas: DCv, DCSection: DCSec, DCArtboard: DCArt } = window;
  return <DCv>
    <DCSec id="noticias" title="Noticias — variantes de layout" subtitle="Misma data y mismas interacciones (filtro por categoría · expandir · leído/guardar). Cada artboard es la tab completa.">
      <DCArt id="a" label="A · Feed cronológico" width={NW} height={2570}><window.VariantA/></DCArt>
      <DCArt id="b" label="B · Línea de tiempo" width={NW} height={2625}><window.VariantB/></DCArt>
      <DCArt id="c" label="C · Destacada + columna" width={NW} height={1865}><window.VariantC/></DCArt>
      <DCArt id="d" label="D · Terminal (tabla densa)" width={NW} height={1290}><window.VariantD/></DCArt>
      <DCArt id="e" label="E · Tablero por medio" width={NW} height={1510}><window.VariantE/></DCArt>
    </DCSec>
  </DCv>;
}
ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
</script>
</body>
</html>
```

### 1.2 `finanzasbo.css` — hoja de estilos completa (tokens + componentes)

```css
/* ════════════════════════════════════════════════════════════════
   FinanzasBo — design tokens & components (paper theme as :root default)
   Extraído verbatim del design system + clases nuevas para Noticias.
   Las variables --* viven en :root (paper). body.theme-dark las overridea.
   ════════════════════════════════════════════════════════════════ */
:root{
  --bg-primary:#f5f7fa;--bg-secondary:#ffffff;--bg-tertiary:#dde8ef;
  --border-color:rgba(44,74,107,0.10);
  --text-primary:#2c4a6b;--text-secondary:#2c4a6b;--text-muted:#6b7d92;--text-soft:#8c9aab;
  --green:#1e4d7a;--green-muted:rgba(30,77,122,.10);--orange:#6b7d92;--orange-muted:rgba(107,125,146,.10);
  --blue-accent:#2c4a6b;
  --color-buy:#1e4d7a;--color-sell:#6b7d92;
  /* fuentes = portales de prensa */
  --src-eldeber:#1e6b8c;--src-correosur:#7a5ea8;--src-unitel:#c0564a;--src-larazon:#2c4a6b;--src-bloomberg:#c47e2a;
  /* categorías */
  --cat-economia:#2c4a6b;--cat-hidrocarburos:#b3473b;--cat-agro:#2c6e49;--cat-mineria:#8a6d3b;--cat-mundo:#5b6ba8;--cat-politica:#6b7d92;
  --font-display:'Outfit',system-ui,sans-serif;
  --font-body:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  --font-mono:'IBM Plex Mono',monospace;
  --text-2xs:9.5px;--text-xs:10.5px;--text-sm:11px;--text-base:12px;--text-md:13px;
  --text-lg:14px;--text-xl:16px;--text-2xl:18px;--text-3xl:22px;--text-4xl:26px;--text-5xl:28px;
  --radius-xs:3px;--radius-sm:4px;--radius-md:6px;--radius-lg:8px;--radius-xl:10px;--radius-pill:9999px;
  --shadow-sm:0 2px 8px rgba(0,0,0,.06);--shadow-md:0 6px 20px rgba(0,0,0,.18);
  --shadow-lg:0 8px 24px rgba(0,0,0,.18);--shadow-xl:0 10px 32px rgba(0,0,0,.24);
  --nav-h:50px;--sub-h:76px;
}
body.theme-dark{
  --bg-primary:#0a1424;--bg-secondary:#122237;--bg-tertiary:rgba(110,163,217,0.15);
  --border-color:rgba(255,255,255,0.10);
  --text-primary:#e6ebf2;--text-secondary:#e6ebf2;--text-muted:#8a96aa;--text-soft:#8a96aa;
  --green:#5a8cc4;--orange:#8a9caf;--blue-accent:#6ea3d9;
  --color-buy:#5a8cc4;--color-sell:#8a9caf;
  --src-eldeber:#5aa9c7;--src-correosur:#a98ed6;--src-unitel:#e07a6e;--src-larazon:#6ea3d9;--src-bloomberg:#e0a44e;
  --cat-economia:#6ea3d9;--cat-hidrocarburos:#e07a6e;--cat-agro:#4fb07a;--cat-mineria:#c79a5a;--cat-mundo:#8b9bd6;--cat-politica:#8a96aa;
  --shadow-sm:0 2px 8px rgba(0,0,0,.35);--shadow-md:0 6px 20px rgba(0,0,0,.45);
  --shadow-lg:0 8px 24px rgba(0,0,0,.50);--shadow-xl:0 10px 32px rgba(0,0,0,.55);
}
*,*::before,*::after{box-sizing:border-box}
.fb-app{font-family:var(--font-body);color:var(--text-primary);background:var(--bg-primary)}

/* ── Navbar ── */
.fb-navbar{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;background:var(--bg-secondary);border-bottom:1px solid var(--border-color)}
.fb-navbar-left{display:flex;align-items:center;gap:16px}
.fb-navbar-right{display:flex;align-items:center;gap:8px}
.fb-logo{font-family:var(--font-display);font-size:var(--text-3xl);font-weight:700;color:var(--blue-accent);letter-spacing:-.01em}
.fb-tabs{display:flex;gap:4px}
.fb-tab{font-family:var(--font-body);font-size:var(--text-lg);font-weight:500;padding:5px 12px;border:none;border-radius:var(--radius-md);cursor:pointer;background:transparent;color:var(--text-muted);transition:all .15s}
.fb-tab.active{background:rgba(44,74,107,.08);color:var(--blue-accent);font-weight:600}
.fb-tab:hover:not(:disabled){background:var(--bg-tertiary);color:var(--text-primary)}
body.theme-dark .fb-tab.active{background:rgba(110,163,217,.12);color:var(--blue-accent)}
.fb-soon{font-size:var(--text-xs);opacity:.7}
.fb-icon-btn{width:30px;height:30px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--border-color);border-radius:var(--radius-md);background:transparent;color:var(--text-muted);cursor:pointer;font-size:var(--text-sm);font-weight:500;transition:all .15s;padding:0}
.fb-icon-btn:hover{background:var(--bg-tertiary);color:var(--text-primary)}
/* tab con sub-categorías (flyout) */
.fb-tab-wrap{position:relative;display:inline-flex}
.fb-tab .fb-caret{font-size:.7em;opacity:.55;margin-left:3px}
.fb-flyout{position:absolute;top:calc(100% + 7px);left:0;display:flex;align-items:center;gap:9px;padding:8px 13px;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:var(--radius-md);box-shadow:var(--shadow-md);opacity:0;visibility:hidden;transform:translateY(-4px);transition:opacity .14s,transform .14s,visibility .14s;z-index:60;white-space:nowrap}
.fb-tab-wrap:hover .fb-flyout,.fb-tab-wrap:focus-within .fb-flyout{opacity:1;visibility:visible;transform:none}
.fb-sublink{background:none;border:none;cursor:pointer;font-family:var(--font-display);font-size:var(--text-md);font-weight:500;color:var(--text-muted);padding:1px 2px;transition:color .15s;line-height:1.2}
.fb-sublink:hover{color:var(--blue-accent)}
.fb-sub-sep{color:var(--border-color);font-size:var(--text-lg);font-weight:300;user-select:none}
body.theme-dark .fb-sub-sep{color:rgba(255,255,255,.20)}

/* ── Sub-header ── */
.fb-subheader{display:flex;align-items:flex-end;justify-content:space-between;padding:14px 18px 14px;background:var(--bg-secondary);border-bottom:1px solid var(--border-color);gap:24px}
.fb-subheader h1{font-family:var(--font-display);font-size:var(--text-4xl);font-weight:700;color:var(--text-primary);letter-spacing:-.02em;line-height:1.05}
.fb-subtitle{font-size:var(--text-md);color:var(--text-muted);margin-top:4px}
.fb-subheader-stats{display:flex;gap:24px;align-items:flex-end}
.fb-stat{text-align:right}
.fb-stat-label{display:block;font-family:var(--font-display);font-size:var(--text-xs);font-weight:500;text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted)}
.fb-stat-value{display:block;font-family:var(--font-mono);font-size:var(--text-xl);font-weight:500;color:var(--text-primary);font-variant-numeric:tabular-nums}

/* ── KPI grid ── */
.fb-kpi-wrap{padding:14px 18px 0;background:var(--bg-primary)}
.fb-kpi-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;padding-bottom:14px}
.fb-kpi-card{padding:14px 16px;border:1px solid var(--border-color);border-radius:var(--radius-lg);background:var(--bg-secondary)}
.fb-kpi-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.fb-kpi-label{font-family:var(--font-display);font-size:var(--text-xs);font-weight:500;text-transform:uppercase;letter-spacing:.10em;color:var(--text-muted)}
.fb-kpi-icon{color:var(--text-muted);opacity:.6;display:inline-flex}
.fb-kpi-icon svg{display:block;width:18px;height:18px}
.fb-kpi-value{font-family:var(--font-mono);font-size:var(--text-3xl);font-weight:500;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1;color:var(--text-primary)}
.fb-kpi-value .unit{font-size:.5em;font-weight:500;color:var(--text-muted);letter-spacing:.04em;margin-left:3px}
.fb-kpi-sub{font-size:var(--text-sm);color:var(--text-muted);margin-top:5px}

/* ── Content ── */
.fb-content{padding:16px 18px 28px}

/* ── Sections / cards ── */
.section{background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:var(--radius-md);margin-bottom:16px;overflow:hidden}
.section-header{padding:16px 20px 12px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.section-header h2{font-family:var(--font-display);font-size:var(--text-lg);font-weight:600;letter-spacing:-.005em;color:var(--text-primary)}
.section-header p{font-size:var(--text-base);font-weight:400;color:var(--text-muted);margin-top:3px;line-height:1.4}
.section-body{padding:16px 20px 20px}

/* ── Filtros (fb-pill) ── */
.fb-flab{font-family:var(--font-display);font-size:var(--text-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.10em;font-weight:500}
.fb-pills{display:flex;gap:4px;flex-wrap:wrap}
.fb-pill{padding:6px 12px;border-radius:var(--radius-md);border:1px solid var(--border-color);background:transparent;font-size:var(--text-sm);color:var(--text-secondary);cursor:pointer;font-weight:500;font-family:var(--font-display);transition:all .15s;display:inline-flex;align-items:center;gap:7px;white-space:nowrap}
.fb-pill:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.fb-pill.active{background:#2c4a6b;color:#fff;border-color:#2c4a6b}
body.theme-dark .fb-pill.active{background:#6ea3d9;border-color:#6ea3d9;color:#0a1424}
.fb-pill .pdot{width:8px;height:8px;border-radius:var(--radius-pill);flex-shrink:0}
.fb-pill.active .pdot{box-shadow:0 0 0 1.5px rgba(255,255,255,.5)}
.fb-pill .pcount{font-family:var(--font-mono);font-size:var(--text-2xs);opacity:.7}

.ds-chip{padding:5px 11px;font-family:var(--font-mono);font-size:var(--text-sm);font-weight:500;border:1px solid var(--border-color);background:transparent;color:var(--text-secondary);cursor:pointer;margin-right:-1px;transition:all .15s;border-radius:var(--radius-sm)}
.ds-chip:first-child{border-radius:var(--radius-sm) 0 0 var(--radius-sm)}
.ds-chip:last-child{border-radius:0 var(--radius-sm) var(--radius-sm) 0;margin-right:0}
.ds-chip:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.ds-chip.active{background:var(--blue-accent);color:#fff;border-color:var(--blue-accent)}
body.theme-dark .ds-chip.active{color:#0a1424}

/* ── Pills / tags ── */
.pill{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:var(--radius-pill);font-size:var(--text-2xs);font-weight:600;letter-spacing:.04em;font-family:var(--font-display);font-variant-numeric:normal;line-height:1.5;white-space:nowrap}
.src-tag{display:inline-flex;align-items:center;gap:6px;font-family:var(--font-display);font-size:var(--text-xs);font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--src-color,var(--text-muted))}
.src-tag .sdot{width:7px;height:7px;border-radius:var(--radius-pill);background:var(--src-color,var(--text-muted));flex-shrink:0}
.topic-tag{display:inline-flex;align-items:center;padding:1px 8px;border-radius:var(--radius-xs);font-family:var(--font-mono);font-size:var(--text-2xs);font-weight:500;letter-spacing:.02em;color:var(--text-muted);background:var(--bg-tertiary);text-transform:uppercase}
.cat-tag{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:var(--radius-pill);font-family:var(--font-display);font-size:var(--text-2xs);font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--cat-color,var(--text-muted));background:color-mix(in srgb,var(--cat-color,#888) 13%,transparent);white-space:nowrap}
.cat-tag .cdot{width:6px;height:6px;border-radius:var(--radius-pill);background:var(--cat-color,var(--text-muted));flex-shrink:0}

.impact{display:inline-flex;align-items:center;gap:5px;font-family:var(--font-display);font-size:var(--text-2xs);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.impact .ibar{display:inline-flex;gap:2px}
.impact .ibar i{width:4px;height:11px;border-radius:1px;background:currentColor;opacity:.22}
.impact .ibar i.on{opacity:1}
.impact.alto{color:#2c4a6b}
.impact.medio{color:#5589c0}
.impact.bajo{color:#8c9aab}
body.theme-dark .impact.alto{color:#9cc3e8}
body.theme-dark .impact.medio{color:#6ea3d9}

/* ── Data table ── */
.fb-data-table{width:100%;border-collapse:collapse;font-size:var(--text-base)}
.fb-data-table th,.fb-data-table td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--border-color)}
.fb-data-table th{font-family:var(--font-display);font-size:var(--text-2xs);color:var(--text-muted);text-transform:uppercase;letter-spacing:.10em;font-weight:500}
.fb-data-table tr:hover{background:rgba(44,74,107,.04)}
body.theme-dark .fb-data-table tr:hover{background:rgba(255,255,255,.04)}
.fb-data-table td.mono{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.fb-data-table th.num,.fb-data-table td.num{text-align:right;font-family:var(--font-mono)}

/* ── Terminal (variante D): tira de días + scroll interno ── */
.fd-daystrip{display:flex;align-items:center;gap:18px;padding:12px 20px 10px}
.fd-daystrip .fb-flab{flex:none}
.fd-slider{position:relative;flex:1;padding:30px 0 18px}
.fd-track{position:absolute;left:0;right:0;top:35px;height:6px;border-radius:var(--radius-pill);background:var(--bg-tertiary);pointer-events:none}
.fd-mark{position:absolute;top:50%;transform:translate(-50%,-50%);width:5px;height:5px;border-radius:50%;background:var(--blue-accent)}
.fd-mark.today{width:7px;height:7px;background:var(--bg-secondary);border:2px solid var(--blue-accent)}
.fd-range{-webkit-appearance:none;appearance:none;position:relative;z-index:2;display:block;width:100%;height:16px;margin:0;background:transparent;outline:none;cursor:pointer}
.fd-range::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:var(--blue-accent);border:2.5px solid var(--bg-secondary);box-shadow:var(--shadow-sm);cursor:grab}
.fd-range:active::-webkit-slider-thumb{cursor:grabbing}
.fd-range::-moz-range-thumb{width:16px;height:16px;border-radius:50%;background:var(--blue-accent);border:2.5px solid var(--bg-secondary);box-shadow:var(--shadow-sm);cursor:grab}
.fd-range:focus-visible::-webkit-slider-thumb{box-shadow:0 0 0 3px var(--green-muted)}
.fd-bubble{position:absolute;top:0;transform:translateX(-50%);white-space:nowrap;font-family:var(--font-mono);font-size:var(--text-xs);font-weight:600;color:var(--bg-secondary);background:var(--blue-accent);padding:3px 9px;border-radius:var(--radius-sm);pointer-events:none}
.fd-bubble::after{content:'';position:absolute;left:50%;top:100%;transform:translateX(-50%);border:4px solid transparent;border-top-color:var(--blue-accent)}
.fd-bubble .bcount{font-weight:400;opacity:.75}
.fd-scale{display:flex;justify-content:space-between;margin-top:12px;font-family:var(--font-mono);font-size:var(--text-2xs);text-transform:uppercase;letter-spacing:.08em;color:var(--text-soft)}
.fd-scroll{max-height:520px;overflow-y:scroll;scrollbar-width:thin;scrollbar-color:var(--text-soft) var(--bg-primary)}
/* design-canvas oculta los scrollbars dentro de los artboards; re-habilitar para la tabla terminal */
.dc-card .fd-scroll{scrollbar-width:thin;scrollbar-color:var(--text-soft) var(--bg-primary)}
.dc-card .fd-scroll::-webkit-scrollbar{display:block;width:11px}
.fd-scroll::-webkit-scrollbar{width:11px}
.fd-scroll::-webkit-scrollbar-track{background:var(--bg-primary);border-left:1px solid var(--border-color)}
.fd-scroll::-webkit-scrollbar-thumb{background:var(--text-soft);border-radius:var(--radius-pill);border:2px solid var(--bg-primary)}
.fd-scroll::-webkit-scrollbar-thumb:hover{background:var(--text-muted)}
.fd-scroll .fb-data-table thead th{position:sticky;top:0;background:var(--bg-secondary);z-index:2;box-shadow:0 1px 0 var(--border-color)}

/* ── Help tip ── */
.help-tip{position:relative;display:inline-flex;cursor:help;vertical-align:middle;margin-left:5px}
.help-tip .help-icon{display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:var(--radius-pill);border:1px solid var(--text-muted);color:var(--text-muted);font-size:var(--text-xs);font-weight:600;line-height:1;opacity:.6;font-family:var(--font-display);font-style:italic;transition:all .15s}
.help-tip:hover .help-icon{opacity:1;color:var(--text-primary);border-color:var(--text-primary)}
.help-tip .help-pop{position:absolute;bottom:calc(100% + 8px);left:50%;transform:translateX(-50%);width:max-content;max-width:260px;background:var(--bg-tertiary);color:var(--text-primary);border:1px solid var(--border-color);border-radius:var(--radius-md);padding:9px 11px;font-size:var(--text-sm);font-weight:400;line-height:1.5;box-shadow:var(--shadow-md);z-index:30;opacity:0;visibility:hidden;transition:opacity .12s;text-align:left;font-family:var(--font-body)}
.help-tip:hover .help-pop{opacity:1;visibility:visible}

/* ── Footer ── */
.fb-footer{padding:16px 18px;font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--text-muted);text-align:center;border-top:1px solid var(--border-color)}
.fb-footer strong{color:var(--text-secondary);font-weight:600}

/* ════════════════════════════════════════════════════════════════
   NOTICIAS — componentes nuevos (siguen la gramática del sistema)
   ════════════════════════════════════════════════════════════════ */

/* action buttons (leído / guardar) */
.n-act{display:inline-flex;align-items:center;justify-content:center;gap:5px;height:26px;padding:0 9px;border:1px solid var(--border-color);border-radius:var(--radius-sm);background:transparent;color:var(--text-muted);cursor:pointer;font-family:var(--font-display);font-size:var(--text-xs);font-weight:500;transition:all .15s}
.n-act:hover{background:var(--bg-tertiary);color:var(--text-primary)}
.n-act svg{width:13px;height:13px}
.n-act.on{color:var(--blue-accent);border-color:var(--blue-accent);background:rgba(44,74,107,.06)}
body.theme-dark .n-act.on{background:rgba(110,163,217,.12)}
.n-act.icon{width:26px;padding:0}

/* read indicator */
.n-readdot{width:7px;height:7px;border-radius:var(--radius-pill);background:var(--blue-accent);flex-shrink:0}

/* ── Variant A — feed cronológico (rows) ── */
.feed-row{display:grid;grid-template-columns:96px 1fr auto;gap:18px;padding:16px 20px;border-bottom:1px solid var(--border-color);transition:background .15s;align-items:start}
.feed-row:last-child{border-bottom:none}
.feed-row:hover{background:rgba(44,74,107,.03)}
body.theme-dark .feed-row:hover{background:rgba(255,255,255,.03)}
.feed-row.is-read{opacity:.62}
.feed-time{font-family:var(--font-mono);font-size:var(--text-sm);color:var(--text-muted);line-height:1.4;font-variant-numeric:tabular-nums}
.feed-time .ft-day{display:block;color:var(--text-secondary);font-weight:500}
.feed-main{min-width:0}
.feed-head{display:flex;align-items:center;gap:10px;margin-bottom:5px;flex-wrap:wrap}
.feed-title{font-family:var(--font-display);font-size:var(--text-lg);font-weight:600;color:var(--text-primary);line-height:1.3;letter-spacing:-.005em;cursor:pointer}
.feed-title:hover{color:var(--blue-accent)}
.feed-sum{font-size:var(--text-md);color:var(--text-secondary);line-height:1.55;margin-top:4px;text-wrap:pretty}
.feed-tags{display:flex;align-items:center;gap:8px;margin-top:9px;flex-wrap:wrap}
.feed-detail{margin-top:12px;padding:12px 14px;background:var(--bg-primary);border:1px solid var(--border-color);border-radius:var(--radius-md);font-size:var(--text-md);color:var(--text-secondary);line-height:1.6}
.feed-detail .fd-meta{display:flex;gap:18px;margin-top:10px;flex-wrap:wrap;font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-muted)}
.feed-detail .fd-meta b{color:var(--text-secondary);font-weight:600}
.feed-actions{display:flex;gap:6px;flex-shrink:0}

/* ── Variant B — timeline ── */
.tl-daygroup{margin-bottom:8px}
.tl-daylabel{display:flex;align-items:center;gap:10px;padding:6px 20px;background:var(--bg-primary);border-top:1px solid var(--border-color);border-bottom:1px solid var(--border-color);font-family:var(--font-display);font-size:var(--text-xs);font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);position:relative}
.tl-daylabel .tl-count{font-family:var(--font-mono);color:var(--text-soft);font-weight:500}
.tl-item{display:grid;grid-template-columns:64px 28px 1fr;gap:0;padding:0 20px;position:relative}
.tl-time{font-family:var(--font-mono);font-size:var(--text-sm);color:var(--text-muted);padding:16px 0;text-align:right;padding-right:12px;font-variant-numeric:tabular-nums}
.tl-rail{position:relative;display:flex;justify-content:center}
.tl-rail::before{content:'';position:absolute;top:0;bottom:0;width:2px;background:var(--border-color)}
.tl-dot{position:relative;z-index:1;width:13px;height:13px;border-radius:var(--radius-pill);margin-top:18px;background:var(--bg-secondary);border:2.5px solid var(--src-color,var(--text-muted))}
.tl-dot.alto{background:var(--src-color,var(--text-muted))}
.tl-body{padding:14px 0 16px 8px;min-width:0}
.tl-item:hover .tl-body{}
.tl-title{font-family:var(--font-display);font-size:var(--text-md);font-weight:600;color:var(--text-primary);line-height:1.35;cursor:pointer}
.tl-title:hover{color:var(--blue-accent)}
.tl-item.is-read .tl-title{color:var(--text-muted);font-weight:500}
.tl-meta{display:flex;align-items:center;gap:9px;margin-top:6px;flex-wrap:wrap}
.tl-sum{font-size:var(--text-base);color:var(--text-secondary);line-height:1.5;margin-top:7px}
.tl-actions{display:flex;gap:6px;margin-top:9px}

/* ── Variant C — destacada + sidebar ── */
.c-grid{display:grid;grid-template-columns:1.55fr 1fr;gap:16px}
.lead-card{border:1px solid var(--border-color);border-radius:var(--radius-md);background:var(--bg-secondary);overflow:hidden;display:flex;flex-direction:column}
.lead-banner{padding:22px 22px 18px;border-bottom:1px solid var(--border-color);background:linear-gradient(180deg,rgba(44,74,107,.05),transparent)}
body.theme-dark .lead-banner{background:linear-gradient(180deg,rgba(110,163,217,.10),transparent)}
.lead-kicker{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.lead-title{font-family:var(--font-display);font-size:var(--text-3xl);font-weight:700;color:var(--text-primary);line-height:1.18;letter-spacing:-.02em;cursor:pointer}
.lead-title:hover{color:var(--blue-accent)}
.lead-body{padding:18px 22px 20px}
.lead-lede{font-size:var(--text-md);color:var(--text-secondary);line-height:1.65;text-wrap:pretty}
.lead-lede + .lead-lede{margin-top:10px}
.lead-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px;padding-top:14px;border-top:1px solid var(--border-color)}
.side-list{border:1px solid var(--border-color);border-radius:var(--radius-md);background:var(--bg-secondary);overflow:hidden}
.side-item{padding:13px 16px;border-bottom:1px solid var(--border-color);transition:background .15s;cursor:pointer}
.side-item:last-child{border-bottom:none}
.side-item:hover{background:rgba(44,74,107,.03)}
body.theme-dark .side-item:hover{background:rgba(255,255,255,.03)}
.side-item.is-read{opacity:.6}
.side-meta{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.side-title{font-family:var(--font-display);font-size:var(--text-md);font-weight:600;color:var(--text-primary);line-height:1.32}
.side-time{font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--text-soft);margin-left:auto}

/* ── Calendar strip ── */
.cal-strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.cal-card{border:1px solid var(--border-color);border-radius:var(--radius-md);padding:12px 13px;background:var(--bg-secondary)}
.cal-date{font-family:var(--font-mono);font-size:var(--text-sm);color:var(--blue-accent);font-weight:600;letter-spacing:.02em}
.cal-in{font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--text-soft);margin-left:6px}
.cal-title{font-family:var(--font-display);font-size:var(--text-base);font-weight:600;color:var(--text-primary);margin-top:6px;line-height:1.3}
.cal-src{margin-top:8px}

/* ── Variant E — board por fuente ── */
.board-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.board-col{border:1px solid var(--border-color);border-radius:var(--radius-md);background:var(--bg-secondary);overflow:hidden;display:flex;flex-direction:column}
.board-head{padding:12px 14px;border-bottom:1px solid var(--border-color);display:flex;align-items:center;justify-content:space-between;border-top:3px solid var(--src-color,var(--text-muted))}
.board-head .bh-name{font-family:var(--font-display);font-size:var(--text-md);font-weight:700;color:var(--text-primary);letter-spacing:.01em}
.board-head .bh-count{font-family:var(--font-mono);font-size:var(--text-xs);color:var(--text-muted);background:var(--bg-tertiary);padding:2px 7px;border-radius:var(--radius-pill)}
.board-item{padding:11px 14px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .15s}
.board-item:last-child{border-bottom:none}
.board-item:hover{background:rgba(44,74,107,.03)}
body.theme-dark .board-item:hover{background:rgba(255,255,255,.03)}
.board-item.is-read{opacity:.55}
.board-time{font-family:var(--font-mono);font-size:var(--text-2xs);color:var(--text-soft);display:flex;align-items:center;gap:7px;margin-bottom:5px}
.board-title{font-family:var(--font-display);font-size:var(--text-base);font-weight:600;color:var(--text-primary);line-height:1.34}
.board-sum{font-size:var(--text-sm);color:var(--text-muted);line-height:1.45;margin-top:5px}
.board-empty{padding:24px 14px;text-align:center;color:var(--text-soft);font-size:var(--text-sm);font-style:italic}

/* filter bar wrapper used across variants */
.n-filterbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:var(--bg-secondary);border:1px solid var(--border-color);border-radius:var(--radius-lg);padding:12px 16px;margin-bottom:16px}
.n-filtergroup{display:flex;flex-direction:column;gap:7px}
.n-filterbar-right{margin-left:auto;display:flex;align-items:center;gap:14px}
.n-savedtoggle{display:inline-flex;align-items:center;gap:7px;font-family:var(--font-display);font-size:var(--text-sm);font-weight:500;color:var(--text-secondary);cursor:pointer;user-select:none}
.n-empty{padding:48px 20px;text-align:center;color:var(--text-soft);font-size:var(--text-md);font-style:italic}
```

### 1.3 `news-data.js` — datos: portales, categorías, noticias curadas, agenda y generador de volumen

```js
/* ════════════════════════════════════════════════════════════════
   Noticias — dataset de ejemplo (contexto Bolivia, jun 2026)
   Contenido ILUSTRATIVO. Sólo prensa: El Deber · Correo del Sur ·
   Unitel · La Razón · Bloomberg. Clasificado por categoría.
   ════════════════════════════════════════════════════════════════ */

// ── Fuentes = portales de prensa ──
window.PORTALS = {
  eldeber:   { id:'eldeber',   name:'El Deber',       full:'El Deber · Santa Cruz',     color:'var(--src-eldeber)' },
  correosur: { id:'correosur', name:'Correo del Sur', full:'Correo del Sur · Sucre',    color:'var(--src-correosur)' },
  unitel:    { id:'unitel',    name:'Unitel',         full:'Unitel · red nacional',     color:'var(--src-unitel)' },
  larazon:   { id:'larazon',   name:'La Razón',       full:'La Razón · La Paz',         color:'var(--src-larazon)' },
  bloomberg: { id:'bloomberg', name:'Bloomberg',      full:'Bloomberg Línea',           color:'var(--src-bloomberg)' },
};
// srcMeta() y SrcTag siguen leyendo de SOURCES → ahora son los portales
window.SOURCES = window.PORTALS;
window.PORTAL_ORDER = ['eldeber','correosur','unitel','larazon','bloomberg'];

// ── Categorías = taxonomía principal (filtro) ──
window.CATEGORIES = {
  economia:      { id:'economia',      name:'Economía',      color:'var(--cat-economia)' },
  hidrocarburos: { id:'hidrocarburos', name:'Hidrocarburos', color:'var(--cat-hidrocarburos)' },
  agro:          { id:'agro',          name:'Agro',          color:'var(--cat-agro)' },
  mineria:       { id:'mineria',       name:'Minería',       color:'var(--cat-mineria)' },
  mundo:         { id:'mundo',         name:'Mundo',         color:'var(--cat-mundo)' },
  politica:      { id:'politica',      name:'Política',      color:'var(--cat-politica)' },
};
window.CAT_ORDER = ['economia','hidrocarburos','agro','mineria','mundo','politica'];

window.NEWS = [
  {
    id:'n01', source:'bloomberg', category:'economia', date:'2026-06-03', time:'08:40',
    title:'La prima del dólar paralelo en Bolivia supera el 40% pese a la intervención del BCB',
    summary:'El USDT/BOB en el mercado P2P cotiza con una prima cercana al 43% sobre el tipo de cambio oficial de 6,96.',
    detail:'Bloomberg Línea reporta que la brecha entre el dólar oficial y el paralelo se mantiene por encima del 40% ante la escasez de reservas líquidas. La autoridad monetaria amplió cupos de venta a importadores priorizados, pero la demanda sigue canalizándose al mercado informal de stablecoins.',
    topics:['Dólar','Reservas'], impact:'alto', sourceNote:'Bloomberg Línea · Mercados',
  },
  {
    id:'n02', source:'eldeber', category:'hidrocarburos', date:'2026-06-03', time:'07:15',
    title:'YPFB reporta caída de producción de gas y una factura récord por importación de diésel',
    summary:'La estatal admite que la subvención de combustibles vuelve a presionar las cuentas fiscales del segundo semestre.',
    detail:'Según El Deber, la producción de gas natural retrocedió frente al año pasado, mientras la importación de diésel y gasolina se encarece por la escasez de divisas. El gasto en subvención se mantiene como una de las mayores presiones sobre el Tesoro General de la Nación.',
    topics:['Gas','Subvención','Fiscal'], impact:'alto', sourceNote:'El Deber · Economía',
  },
  {
    id:'n03', source:'larazon', category:'economia', date:'2026-06-02', time:'17:05',
    title:'El INE confirma una inflación interanual de 20,5% a mayo, la más alta en dos décadas',
    summary:'Alimentos y transporte concentran el mayor aporte al índice de precios al consumidor.',
    detail:'La Razón informa que el Instituto Nacional de Estadística confirmó una inflación interanual de 20,5% a mayo, impulsada por los rubros de alimentos (+29%) y transporte (+23%). El dato presiona las tasas reales y el poder adquisitivo de los hogares.',
    topics:['Inflación','Precios'], impact:'alto', sourceNote:'La Razón · Economía',
  },
  {
    id:'n04', source:'unitel', category:'hidrocarburos', date:'2026-06-02', time:'16:20',
    title:'Escasez de combustible: los surtidores racionan diésel en cuatro departamentos',
    summary:'Largas filas de transportistas y productores se reportan en Santa Cruz, Cochabamba, Tarija y Beni.',
    detail:'Unitel constató filas de varias horas en surtidores que aplican racionamiento de diésel. Gremios del transporte pesado advierten afectaciones a la cadena de abastecimiento y a la cosecha agrícola si la provisión no se normaliza en los próximos días.',
    topics:['Diésel','Transporte'], impact:'alto', sourceNote:'Unitel · Nacional',
  },
  {
    id:'n05', source:'correosur', category:'agro', date:'2026-06-02', time:'12:30',
    title:'Productores de soya advierten pérdidas por falta de diésel en plena cosecha',
    summary:'El sector agroindustrial cruceño estima riesgos en la campaña de verano por la escasez de combustible.',
    detail:'Correo del Sur recoge la alerta de los productores de oleaginosas, que vinculan la falta de diésel con retrasos en la cosecha de soya. Los gremios piden priorizar la dotación al agro para no comprometer las exportaciones y el abastecimiento interno de aceite.',
    topics:['Soya','Exportación'], impact:'medio', sourceNote:'Correo del Sur · Capitales',
  },
  {
    id:'n06', source:'bloomberg', category:'mundo', date:'2026-06-01', time:'18:00',
    title:'La Fed mantiene tasas y los mercados emergentes sienten la presión cambiaria',
    summary:'El dólar fuerte complica el financiamiento externo de las economías de la región.',
    detail:'Bloomberg señala que la decisión de la Reserva Federal de mantener tasas altas prolonga la presión sobre las monedas emergentes. Para países con spreads soberanos elevados como Bolivia, el costo de acceder a mercados externos se mantiene en niveles prohibitivos.',
    topics:['Tasas','Global'], impact:'medio', sourceNote:'Bloomberg Línea · Mundo',
  },
  {
    id:'n07', source:'eldeber', category:'economia', date:'2026-06-01', time:'11:40',
    title:'Largas filas en bancos por el racionamiento de dólares para importadores',
    summary:'Empresas denuncian demoras de semanas para acceder a divisas al tipo de cambio oficial.',
    detail:'El Deber documenta la persistencia de filas en entidades financieras para la compra de dólares. Importadores de insumos y bienes de capital reportan que el cupo asignado no cubre la demanda, lo que empuja parte de las operaciones al mercado paralelo.',
    topics:['Dólar','Importación'], impact:'alto', sourceNote:'El Deber · Economía',
  },
  {
    id:'n08', source:'larazon', category:'politica', date:'2026-05-31', time:'19:20',
    title:'La Asamblea debate la ley de créditos externos por USD 1.800 millones',
    summary:'El oficialismo y la oposición tensionan la aprobación del financiamiento multilateral pendiente.',
    detail:'La Razón informa que el debate en la Asamblea Legislativa se concentra en la aprobación de créditos externos clave para sostener las reservas y proyectos de inversión. El bloqueo legislativo de los préstamos es señalado por analistas como un factor de presión adicional sobre las divisas.',
    topics:['Crédito','Asamblea'], impact:'medio', sourceNote:'La Razón · Política',
  },
  {
    id:'n09', source:'unitel', category:'agro', date:'2026-05-30', time:'09:50',
    title:'La sequía en el Chaco golpea la ganadería y eleva el precio de la carne',
    summary:'Productores reportan mortandad de ganado y menor oferta en mercados del oriente.',
    detail:'Unitel recorrió zonas del Chaco afectadas por la prolongada sequía, donde la falta de agua y forraje compromete el hato ganadero. El menor abastecimiento ya se refleja en alzas del precio de la carne en mercados de Santa Cruz y Tarija.',
    topics:['Ganadería','Sequía'], impact:'medio', sourceNote:'Unitel · Regional',
  },
  {
    id:'n10', source:'correosur', category:'mineria', date:'2026-05-29', time:'15:10',
    title:'Cooperativas mineras de Potosí bloquean por el precio del oro y las regalías',
    summary:'El conflicto interrumpe vías clave y reaviva el debate sobre la exportación de minerales.',
    detail:'Correo del Sur reporta bloqueos de cooperativas mineras que exigen cambios en el régimen de regalías en un contexto de precios internacionales del oro al alza. El sector reclama mayor participación de los ingresos por exportación de minerales.',
    topics:['Oro','Regalías'], impact:'medio', sourceNote:'Correo del Sur · Nacional',
  },
  {
    id:'n11', source:'bloomberg', category:'economia', date:'2026-05-28', time:'10:05',
    title:'El riesgo país de Bolivia cierra cerca de 1.900 pb, el más alto de la región',
    summary:'El spread soberano se mantiene muy por encima del promedio latinoamericano de unos 450 pb.',
    detail:'Bloomberg destaca que el EMBI de Bolivia se sostiene cerca de los 1.900 puntos básicos, reflejando la incertidumbre sobre el financiamiento externo y el calendario de vencimientos. El nivel encarece cualquier intento de retorno a los mercados internacionales de deuda.',
    topics:['Riesgo País','Deuda'], impact:'alto', sourceNote:'Bloomberg Línea · Mercados',
  },
  {
    id:'n12', source:'eldeber', category:'mundo', date:'2026-05-27', time:'08:20',
    title:'Brasil y Argentina buscan ampliar el comercio bilateral con Bolivia en moneda local',
    summary:'Las mesas técnicas exploran mecanismos de pago que reduzcan el uso de dólares.',
    detail:'El Deber informa sobre conversaciones para ampliar el comercio regional usando monedas locales, una alternativa frente a la escasez de divisas. La medida apunta a sostener el intercambio de gas, granos y manufacturas con los socios del Mercosur.',
    topics:['Comercio','Mercosur'], impact:'bajo', sourceNote:'El Deber · Mundo',
  },
  {
    id:'n13', source:'larazon', category:'hidrocarburos', date:'2026-05-26', time:'16:45',
    title:'Bolivia negocia nuevos contratos de exploración gasífera con empresas extranjeras',
    summary:'El Gobierno busca revertir la declinación de reservas probadas de gas natural.',
    detail:'La Razón reporta que YPFB avanza en rondas de negociación para atraer inversión en exploración de gas. El objetivo es frenar la caída de la producción que en la última década pasó de exportador neto a una balanza energética cada vez más ajustada.',
    topics:['Gas','Inversión'], impact:'medio', sourceNote:'La Razón · Economía',
  },
  {
    id:'n14', source:'correosur', category:'agro', date:'2026-05-24', time:'14:30',
    title:'Exportadores de quinua de Oruro reportan caída de pedidos por la brecha cambiaria',
    summary:'La incertidumbre del tipo de cambio complica los contratos en dólares del sector.',
    detail:'Correo del Sur recoge la preocupación de los exportadores de quinua del altiplano, que vinculan la caída de pedidos con la dificultad para cerrar pagos en dólares. El sector pide reglas claras de acceso a divisas para sostener su competitividad externa.',
    topics:['Quinua','Exportación'], impact:'bajo', sourceNote:'Correo del Sur · Capitales',
  },
  {
    id:'n15', source:'unitel', category:'politica', date:'2026-05-23', time:'11:10',
    title:'Gobierno y oposición tensionan el debate por el Presupuesto General 2026',
    summary:'El tratamiento del PGE concentra la discusión sobre el déficit fiscal y la subvención.',
    detail:'Unitel sigue el pulso político en torno al Presupuesto General del Estado, donde el déficit fiscal y el gasto en subvención de combustibles son los puntos más controvertidos. El desenlace condicionará la sostenibilidad de las cuentas públicas del año.',
    topics:['Presupuesto','Fiscal'], impact:'medio', sourceNote:'Unitel · Política',
  },
];

// ── Agenda: próximos hechos que la prensa cubrirá (por categoría) ──
window.EVENTS = [
  { id:'e1', category:'economia',      date:'2026-06-08', inDays:5,  title:'INE publica el IPC de mayo (dato definitivo)' },
  { id:'e2', category:'hidrocarburos', date:'2026-06-10', inDays:7,  title:'YPFB presenta su informe de producción y subvención' },
  { id:'e3', category:'agro',          date:'2026-06-12', inDays:9,  title:'Cierre de la campaña de verano de soya en Santa Cruz' },
  { id:'e4', category:'politica',      date:'2026-06-15', inDays:12, title:'La Asamblea trata el crédito externo por USD 1.800 M' },
  { id:'e5', category:'mundo',         date:'2026-06-18', inDays:15, title:'Reunión del Mercosur: comercio en monedas locales' },
];

window.TOPIC_LIST = ['Dólar','Inflación','Gas','Diésel','Subvención','Reservas','Riesgo País','Comercio','Exportación','Fiscal'];

/* ════════════════════════════════════════════════════════════════
   Generador determinista de volumen: completa cada uno de los
   últimos 30 días hasta ~10±2 notas. Contenido ILUSTRATIVO que
   complementa las 15 notas curadas de arriba.
   ════════════════════════════════════════════════════════════════ */
(function(){
  const TODAY = '2026-06-03';
  function mulberry32(a){ return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
  const rnd = mulberry32(20260603);
  const int  = (a,b)=>a+Math.floor(rnd()*(b-a+1));
  const pick = arr=>arr[Math.floor(rnd()*arr.length)];
  const bs   = v=>v.toFixed(2).replace('.',',');
  const addDays = (iso,d)=>{ const [y,m,dd]=iso.split('-').map(Number); const dt=new Date(y,m-1,dd+d);
    return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`; };

  const CIUDADES = ['Santa Cruz','La Paz','Cochabamba','El Alto','Tarija','Sucre','Oruro','Potosí','Trinidad'];
  const FRONTERAS = ['Argentina','Perú','Chile','Brasil'];
  const ZONAS_GAS = ['el Chaco tarijeño','el subandino sur','el norte de La Paz'];
  const SECCION = { economia:'Economía', hidrocarburos:'Energía', agro:'Agro', mineria:'Minería', mundo:'Mundo', politica:'Política' };

  // Series diarias: evolucionan con el índice del día (0 = hace 29 días … 29 = hoy)
  const SERIES = [
    { cat:'economia', srcs:['bloomberg','eldeber'], impact:'alto', topics:['Dólar','Reservas'],
      mk:(di)=>{ const r=9.52+di*0.014+(rnd()-0.5)*0.06, p=(r/6.96-1)*100; return {
        title:`El dólar paralelo opera en Bs ${bs(r)} y la prima llega al ${p.toFixed(0)}%`,
        summary:`El USDT/BOB cotiza en torno a Bs ${bs(r)} en el mercado P2P, frente al oficial de 6,96.`,
        detail:`Operadores del mercado paralelo reportan un tipo de cambio de referencia de Bs ${bs(r)} por dólar, una prima de ${p.toFixed(1)}% sobre el oficial. La oferta de divisas sigue limitada y parte de la demanda se canaliza vía stablecoins.` }; } },
    { every:3, cat:'economia', srcs:['bloomberg'], impact:'medio', topics:['Riesgo País','Deuda'],
      mk:(di)=>{ const pb=1845+di*2+int(-12,12); return {
        title:`El riesgo país se mantiene en torno a ${pb.toLocaleString('es-BO')} puntos básicos`,
        summary:`El spread soberano sigue entre los más altos de la región, lejos del promedio latinoamericano.`,
        detail:`El EMBI de Bolivia cerró la jornada cerca de los ${pb.toLocaleString('es-BO')} puntos básicos. El nivel refleja la incertidumbre sobre el financiamiento externo y mantiene cerrado el acceso a los mercados internacionales de deuda.` }; } },
    { cat:'hidrocarburos', srcs:['unitel','eldeber'], impact:'medio', topics:['Diésel','Transporte'],
      mk:()=>{ const c=pick(CIUDADES), h=int(3,9); return {
        title:`Filas de hasta ${h} horas por diésel en surtidores de ${c}`,
        summary:`Transportistas y particulares reportan espera prolongada para cargar combustible.`,
        detail:`En surtidores de ${c} se registraron filas de hasta ${h} horas para cargar diésel. Los administradores señalan que la provisión llega de forma irregular y se agota en pocas horas.` }; } },
  ];

  // Pool de plantillas: se reutilizan entre días con parámetros distintos
  const POOL = [
    { cat:'economia', srcs:['eldeber','larazon'], impact:'medio', topics:['Dólar','Banca'],
      mk:()=>{ const m=int(4,10)*50; return {
        title:`Bancos ajustan a USD ${m} semanales el cupo de retiro en dólares`,
        summary:`Las entidades financieras vuelven a recalibrar los límites de retiro de moneda extranjera.`,
        detail:`Clientes de varias entidades reportan que el cupo de retiro en ventanilla se fijó en torno a USD ${m} por semana. Los bancos atribuyen la medida a la menor disponibilidad de billetes físicos.` }; } },
    { cat:'economia', srcs:['bloomberg','larazon'], impact:'medio', topics:['Banca'],
      mk:()=>{ const p=int(3,8); return {
        title:`Los depósitos en dólares caen ${p}% en el sistema financiero`,
        summary:`La dolarización de ahorros fuera del sistema continúa, según cifras del regulador.`,
        detail:`Los depósitos en moneda extranjera acumulan una caída de ${p}% en el año. Analistas vinculan el retroceso con la preferencia por mantener divisas fuera del sistema ante la brecha cambiaria.` }; } },
    { cat:'economia', srcs:['larazon','bloomberg'], impact:'alto', topics:['Reservas'],
      mk:()=>{ const m=int(3,8)*10; return {
        title:`El BCB monetiza oro por USD ${m} millones para sostener las reservas`,
        summary:`La autoridad monetaria recurre otra vez a las reservas en oro para obtener liquidez.`,
        detail:`El Banco Central concretó una nueva operación con sus reservas en oro por unos USD ${m} millones. La entidad defiende la medida como un mecanismo para honrar deuda externa y sostener la provisión de divisas.` }; } },
    { cat:'economia', srcs:['unitel','eldeber'], impact:'medio', topics:['Precios','Inflación'],
      mk:()=>{ const c=pick(CIUDADES), m=int(4,9)*10; return {
        title:`La canasta básica se encarece Bs ${m} en un mes en ${c}`,
        summary:`Amas de casa y comerciantes confirman alzas sostenidas en alimentos esenciales.`,
        detail:`Un sondeo en mercados de ${c} muestra que la canasta básica subió alrededor de Bs ${m} en las últimas cuatro semanas, con los mayores incrementos en aceite, arroz y carne.` }; } },
    { cat:'economia', srcs:['eldeber','correosur'], impact:'bajo', topics:['Remesas','Dólar'],
      mk:()=>{ const p=int(5,12); return {
        title:`Las remesas crecen ${p}% interanual y alivian la escasez de divisas`,
        summary:`Los envíos desde el exterior se consolidan como una fuente clave de dólares.`,
        detail:`Las remesas familiares registraron un crecimiento interanual de ${p}%, con España, Estados Unidos y Chile como principales orígenes. El flujo ayuda a oxigenar el mercado cambiario.` }; } },
    { cat:'economia', srcs:['larazon'], impact:'bajo', topics:['Banca','Tasas'],
      mk:()=>{ const t=int(14,19); return {
        title:`El crédito al consumo se encarece: tasas ya superan el ${t}% anual`,
        summary:`El encarecimiento del fondeo se traslada a los préstamos de los hogares.`,
        detail:`Entidades financieras ajustaron al alza las tasas de los créditos de consumo, que en algunos productos superan el ${t}% anual. El microcrédito muestra una tendencia similar.` }; } },
    { cat:'hidrocarburos', srcs:['unitel','eldeber'], impact:'medio', topics:['Diésel'],
      mk:()=>{ const c=pick(CIUDADES), n=int(15,40); return {
        title:`YPFB despacha ${n} cisternas de diésel a ${c} para normalizar la provisión`,
        summary:`La estatal asegura que el abastecimiento se regularizará en las próximas horas.`,
        detail:`YPFB informó el despacho de ${n} cisternas de diésel hacia ${c} y pidió a la población no sobreabastecerse. Gremios del transporte se mantienen en emergencia hasta que la provisión sea regular.` }; } },
    { cat:'hidrocarburos', srcs:['unitel','correosur'], impact:'medio', topics:['Combustible','Frontera'],
      mk:()=>{ const m=int(8,25), f=pick(FRONTERAS); return {
        title:`Incautan ${m} mil litros de combustible de contrabando en la frontera con ${f}`,
        summary:`Operativos militares interceptan cargamentos que salían del país.`,
        detail:`Un operativo en la frontera con ${f} permitió incautar cerca de ${m}.000 litros de combustible subvencionado que era sacado de contrabando. Las autoridades anuncian más controles en rutas alternas.` }; } },
    { cat:'hidrocarburos', srcs:['larazon','eldeber'], impact:'bajo', topics:['GLP'],
      mk:()=>{ const p=int(8,18); return {
        title:`La demanda de GLP sube ${p}% por el invierno y YPFB refuerza la distribución`,
        summary:`La estatal garantiza el abastecimiento de garrafas pese al pico estacional.`,
        detail:`Con la llegada del invierno, la demanda de GLP creció alrededor de ${p}%. YPFB amplió los puntos de venta directa y descartó un desabastecimiento del energético.` }; } },
    { cat:'hidrocarburos', srcs:['eldeber','larazon'], impact:'alto', topics:['Subvención','Fiscal'],
      mk:()=>{ const m=int(6,9)*100; return {
        title:`La subvención a combustibles ya supera los USD ${m} millones en el año`,
        summary:`El costo fiscal de mantener los precios congelados sigue creciendo.`,
        detail:`Según datos oficiales, el gasto en subvención de combustibles acumula más de USD ${m} millones en lo que va del año, una de las mayores presiones sobre el Tesoro y las divisas.` }; } },
    { cat:'hidrocarburos', srcs:['larazon','bloomberg'], impact:'medio', topics:['Gas','Inversión'],
      mk:()=>{ const z=pick(ZONAS_GAS); return {
        title:`Avanza la negociación de un nuevo contrato de exploración gasífera en ${z}`,
        summary:`YPFB busca socios para revertir la declinación de las reservas de gas.`,
        detail:`La estatal petrolera informó avances en la negociación de un contrato de exploración en ${z}. El objetivo es incorporar reservas frente a la caída sostenida de la producción.` }; } },
    { cat:'agro', srcs:['eldeber','bloomberg'], impact:'medio', topics:['Soya','Exportación'],
      mk:()=>{ const p=int(5,15); return {
        title:`Las exportaciones de soya caen ${p}% por la falta de diésel y los bloqueos`,
        summary:`La agroindustria advierte que la logística encarece la campaña.`,
        detail:`Los despachos de soya y derivados retrocedieron ${p}% frente al año pasado. El sector atribuye la caída a la escasez de diésel, los bloqueos intermitentes y la menor molienda.` }; } },
    { cat:'agro', srcs:['unitel','correosur'], impact:'medio', topics:['Precios'],
      mk:()=>{ const c=pick(CIUDADES), v=int(18,24); return {
        title:`El kilo de pollo sube a Bs ${v} en mercados de ${c}`,
        summary:`Comerciantes atribuyen el alza al costo del alimento balanceado y la logística.`,
        detail:`En mercados de ${c} el kilo de pollo se vende hasta en Bs ${v}. Avicultores señalan que el encarecimiento del maíz, la soya y el transporte presiona los precios al consumidor.` }; } },
    { cat:'agro', srcs:['correosur','unitel'], impact:'medio', topics:['Clima'],
      mk:()=>{ const h=int(10,40)/10; return {
        title:`Heladas afectan ${bs(h)} mil hectáreas de cultivos en el altiplano`,
        summary:`Productores de papa y quinua piden apoyo ante las pérdidas por el frío.`,
        detail:`Las heladas de los últimos días dañaron alrededor de ${bs(h)} mil hectáreas de cultivos en municipios del altiplano. Los gobiernos locales evalúan declaratorias de emergencia agrícola.` }; } },
    { cat:'agro', srcs:['eldeber'], impact:'bajo', topics:['Arroz','Exportación'],
      mk:()=>({
        title:'Arroceros piden liberar la exportación de excedentes tras una buena cosecha',
        summary:'El sector estima un superávit que podría venderse a mercados vecinos.',
        detail:'Productores de arroz solicitan certificados de exportación para colocar excedentes en países vecinos. Aseguran que el mercado interno está abastecido y que la venta externa daría liquidez al sector.' }) },
    { cat:'mineria', srcs:['bloomberg','correosur'], impact:'medio', topics:['Oro'],
      mk:()=>({
        title:'El oro marca un nuevo máximo y dinamiza la actividad de las cooperativas',
        summary:'El precio internacional vuelve a batir récords e impulsa la producción aurífera.',
        detail:'La cotización internacional del oro alcanzó un nuevo máximo histórico. En Bolivia, las cooperativas auríferas amplían frentes de trabajo, mientras persiste el debate sobre regalías y control de la comercialización.' }) },
    { cat:'mineria', srcs:['bloomberg','larazon'], impact:'bajo', topics:['Zinc','Exportación'],
      mk:()=>{ const p=int(3,12); return {
        title:`Las exportaciones de zinc suben ${p}% por mejores precios internacionales`,
        summary:`La minería mediana aprovecha la recuperación de los metales industriales.`,
        detail:`El valor exportado de zinc creció ${p}% interanual, impulsado por los precios internacionales. El mineral se mantiene entre los principales generadores de divisas del país.` }; } },
    { cat:'mineria', srcs:['correosur'], impact:'bajo', topics:['Regalías'],
      mk:()=>{ const p=int(10,25); return {
        title:`Las regalías mineras de Potosí crecen ${p}% interanual`,
        summary:`Los buenos precios de los minerales mejoran los ingresos departamentales.`,
        detail:`La gobernación de Potosí reporta un incremento de ${p}% en las regalías mineras respecto al año pasado, explicado por las cotizaciones del zinc, la plata y el oro.` }; } },
    { cat:'mineria', srcs:['larazon','bloomberg'], impact:'medio', topics:['Litio'],
      mk:()=>({
        title:'El programa de litio en Uyuni suma avances pero la producción sigue lejos de la meta',
        summary:'Los convenios con socios extranjeros avanzan a ritmo más lento de lo previsto.',
        detail:'Autoridades informaron avances en los convenios de extracción directa de litio en el salar de Uyuni. Analistas advierten que la producción comercial todavía está lejos de los volúmenes comprometidos.' }) },
    { cat:'mundo', srcs:['bloomberg'], impact:'bajo', topics:['Petróleo'],
      mk:()=>{ const v=int(78,88); return {
        title:`El Brent opera en torno a USD ${v} por barril`,
        summary:`El precio del crudo marca el costo de la factura boliviana de importación.`,
        detail:`El petróleo Brent cotizó cerca de USD ${v} por barril. Para Bolivia, importador neto de diésel y gasolina, el nivel del crudo define buena parte del costo de la subvención.` }; } },
    { cat:'mundo', srcs:['bloomberg','eldeber'], impact:'bajo', topics:['Comercio'],
      mk:()=>({
        title:'El real brasileño se fortalece y encarece las importaciones desde Brasil',
        summary:'El tipo de cambio regional mueve el comercio de frontera.',
        detail:'La apreciación del real frente al dólar encarece los productos brasileños que ingresan al país. Comerciantes de frontera reportan menor movimiento en las compras al por mayor.' }) },
    { cat:'mundo', srcs:['bloomberg'], impact:'medio', topics:['Tasas','Global'],
      mk:()=>({
        title:'Mercados emergentes atentos a las señales de la Fed sobre recortes de tasas',
        summary:'El costo del financiamiento externo sigue atado a la política monetaria de EE.UU.',
        detail:'Los inversores reposicionan sus carteras a la espera de definiciones de la Reserva Federal. Para economías con spreads altos como Bolivia, cualquier alivio en las tasas globales llega amortiguado.' }) },
    { cat:'mundo', srcs:['eldeber','larazon'], impact:'bajo', topics:['Comercio','Frontera'],
      mk:()=>({
        title:'El comercio fronterizo con Argentina se reactiva por el diferencial cambiario',
        summary:'Compradores cruzan la frontera en busca de precios más convenientes.',
        detail:'El movimiento comercial en pasos fronterizos con Argentina volvió a crecer, impulsado por el diferencial de precios y tipo de cambio. Los gremios locales piden controles para proteger al comercio formal.' }) },
    { cat:'politica', srcs:['larazon','unitel'], impact:'medio', topics:['Crédito','Asamblea'],
      mk:()=>{ const m=int(3,9)*100; return {
        title:`La Asamblea posterga el tratamiento de créditos externos por USD ${m} millones`,
        summary:`El financiamiento multilateral sigue trabado en el Legislativo.`,
        detail:`La sesión prevista para tratar créditos externos por unos USD ${m} millones volvió a postergarse por falta de acuerdos. Analistas advierten que la demora agrava la escasez de divisas.` }; } },
    { cat:'politica', srcs:['unitel'], impact:'medio', topics:['Transporte','Diésel'],
      mk:()=>({
        title:'Gobierno y transportistas instalan una mesa de diálogo por el abastecimiento de diésel',
        summary:'El sector condiciona la suspensión de medidas de presión a resultados concretos.',
        detail:'Representantes del transporte pesado y del Ejecutivo instalaron una mesa técnica para garantizar la provisión de diésel. Los gremios advierten que retomarán las movilizaciones si no hay resultados.' }) },
    { cat:'politica', srcs:['larazon','eldeber'], impact:'alto', topics:['Dólar','Política'],
      mk:()=>({
        title:'El Ejecutivo descarta modificar el tipo de cambio oficial de Bs 6,96',
        summary:'El Gobierno ratifica la política cambiaria pese a la brecha con el paralelo.',
        detail:'Voceros oficiales reiteraron que no está en evaluación un ajuste del tipo de cambio oficial. Economistas insisten en que la brecha con el paralelo seguirá presionando precios e importaciones.' }) },
    { cat:'politica', srcs:['unitel','larazon'], impact:'medio', topics:['Reservas','Asamblea'],
      mk:()=>({
        title:'Comisión legislativa pide un informe al BCB sobre el nivel de las reservas',
        summary:'Legisladores buscan precisiones sobre la posición de divisas y oro del país.',
        detail:'La Comisión de Planificación solicitó al Banco Central un informe detallado sobre las reservas internacionales. El requerimiento se suma al debate por el uso del oro monetario.' }) },
  ];

  // Notas curadas ya existentes por día
  const curated = {}; window.NEWS.forEach(n=>{ curated[n.date]=(curated[n.date]||0)+1; });

  const gen = [];
  for (let di=0; di<30; di++){
    const date = addDays(TODAY, di-29);
    const target = int(8,12);
    let need = target - (curated[date]||0);
    const dayItems = [];
    const usedPool = new Set();
    SERIES.forEach((s,si)=>{
      if (need<=0) return;
      if (s.every && di % s.every !== 0) return;
      dayItems.push({ tpl:s, body:s.mk(di) }); need--;
    });
    let guard = 0;
    while (need>0 && guard++<200){
      const ti = int(0, POOL.length-1);
      if (usedPool.has(ti)) continue;
      usedPool.add(ti);
      const t = POOL[ti];
      dayItems.push({ tpl:t, body:t.mk(di) }); need--;
    }
    dayItems.forEach((it,i)=>{
      const src = pick(it.tpl.srcs);
      const hh = int(6,21), mm = int(0,11)*5;
      gen.push({
        id:`g${date.replace(/-/g,'')}x${i}`,
        source:src, category:it.tpl.cat, date,
        time:`${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}`,
        title:it.body.title, summary:it.body.summary, detail:it.body.detail,
        topics:it.tpl.topics, impact:it.tpl.impact,
        sourceNote:`${window.PORTALS[src].name} · ${SECCION[it.tpl.cat]}`,
      });
    });
  }
  window.NEWS = window.NEWS.concat(gen);
})();
```

### 1.4 `shared.jsx` — helpers, hook de estado del feed y componentes comunes (navbar, KPIs, filtros, tags)

```jsx
/* shared.jsx — helpers, hooks y componentes comunes para las variantes de Noticias.
   Exporta a window para que los demás scripts babel los usen. */
const { useState, useMemo, useCallback } = React;

const MESES = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
function parseD(d){ const [y,m,day]=d.split('-').map(Number); return new Date(y,m-1,day); }
function fmtDay(d){ const dt=parseD(d); return `${String(dt.getDate()).padStart(2,'0')} ${MESES[dt.getMonth()]}`; }
function fmtDayLong(d){ const dt=parseD(d); const dias=['domingo','lunes','martes','miércoles','jueves','viernes','sábado']; return `${dias[dt.getDay()]} ${dt.getDate()} ${MESES[dt.getMonth()]}`; }
const TODAY = '2026-06-03';
function relDay(d){ if(d===TODAY) return 'Hoy'; const diff=Math.round((parseD(TODAY)-parseD(d))/86400000); if(diff===1) return 'Ayer'; return `hace ${diff} días`; }

function srcMeta(id){ return window.SOURCES[id]; }
function catMeta(id){ return window.CATEGORIES[id]; }

// ── átomos visuales ──
function SrcTag({ id }){
  const s = srcMeta(id);
  return <span className="src-tag" style={{ '--src-color': s.color }}>
    <span className="sdot"></span>{s.name}
  </span>;
}
function CatTag({ id }){
  const c = catMeta(id); if(!c) return null;
  return <span className="cat-tag" style={{ '--cat-color': c.color }}>
    <span className="cdot"></span>{c.name}
  </span>;
}
function Topic({ t }){ return <span className="topic-tag">{t}</span>; }
function Impact({ level }){
  const n = level==='alto'?3:level==='medio'?2:1;
  return <span className={`impact ${level}`}>
    <span className="ibar">{[0,1,2].map(i=><i key={i} className={i<n?'on':''}></i>)}</span>
    {level}
  </span>;
}
const IconCheck = () => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>;
const IconBookmark = ({filled}) => <svg viewBox="0 0 24 24" fill={filled?'currentColor':'none'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>;
const IconChevron = ({open}) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{transition:'transform .15s',transform:open?'rotate(180deg)':'none'}}><polyline points="6 9 12 15 18 9"/></svg>;

function ReadBtn({ on, onClick, iconOnly }){
  return <button className={`n-act ${iconOnly?'icon':''} ${on?'on':''}`} onClick={onClick} title={on?'Marcar como no leído':'Marcar como leído'}>
    <IconCheck/>{!iconOnly && (on?'Leído':'Leer')}
  </button>;
}
function SaveBtn({ on, onClick, iconOnly }){
  return <button className={`n-act ${iconOnly?'icon':''} ${on?'on':''}`} onClick={onClick} title={on?'Quitar de guardados':'Guardar'}>
    <IconBookmark filled={on}/>{!iconOnly && (on?'Guardada':'Guardar')}
  </button>;
}

// ── hook de estado del feed (filtro por CATEGORÍA) ──
function useFeed(key){
  const ALL = window.CAT_ORDER;
  const [cats, setCats] = useState(()=>new Set(ALL));
  const [onlySaved, setOnlySaved] = useState(false);
  const [read, setRead] = useState(()=>new Set());
  const [saved, setSaved] = useState(()=>new Set());
  const [expanded, setExpanded] = useState(null);

  const toggleCat = useCallback((id)=>setCats(prev=>{
    const n=new Set(prev);
    if(id==='all'){ return n.size===ALL.length ? new Set() : new Set(ALL); }
    n.has(id)?n.delete(id):n.add(id); return n;
  }),[]);
  const mk = (setter)=>(id)=>setter(prev=>{ const n=new Set(prev); n.has(id)?n.delete(id):n.add(id); return n; });
  const toggleRead = useCallback(mk(setRead),[]);
  const toggleSave = useCallback(mk(setSaved),[]);
  const toggleExpand = useCallback((id)=>setExpanded(p=>p===id?null:id),[]);

  const all = window.NEWS;
  const counts = useMemo(()=>{
    const c={}; ALL.forEach(k=>c[k]=0); all.forEach(n=>c[n.category]++); return c;
  },[all]);

  const items = useMemo(()=> all
    .filter(n=> cats.has(n.category))
    .filter(n=> !onlySaved || saved.has(n.id))
    .slice()
    .sort((a,b)=> (b.date+b.time).localeCompare(a.date+a.time))
  ,[all,cats,onlySaved,saved]);

  return { cats, toggleCat, onlySaved, setOnlySaved, read, toggleRead, saved, toggleSave,
           expanded, toggleExpand, items, counts, allCount: all.length };
}

// ── KPI strip ──
const KICON = {
  hoy:'<path d="M3 9h18M3 15h18M9 3v18M15 3v18"/>',
  medios:'<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8z"/>',
  evento:'<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  impacto:'<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  guardadas:'<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
};
function Kpi({ label, value, unit, sub, icon }){
  return <div className="fb-kpi-card">
    <div className="fb-kpi-head">
      <span className="fb-kpi-label">{label}</span>
      <span className="fb-kpi-icon" dangerouslySetInnerHTML={{__html:`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${KICON[icon]}</svg>`}}></span>
    </div>
    <div className="fb-kpi-value">{value}{unit && <span className="unit">{unit}</span>}</div>
    <div className="fb-kpi-sub">{sub}</div>
  </div>;
}
function KpiStrip({ feed }){
  const all = window.NEWS;
  const hoy = all.filter(n=>n.date===TODAY).length;
  const portales = window.PORTAL_ORDER.length;
  const alto = all.filter(n=>n.impact==='alto').length;
  const ev = window.EVENTS[0];
  return <div className="fb-kpi-wrap"><div className="fb-kpi-grid">
    <Kpi icon="hoy" label="Noticias hoy" value={hoy} sub="actualizado 09:09 a. m." />
    <Kpi icon="medios" label="Portales" value={portales} sub="medios monitoreados" />
    <Kpi icon="impacto" label="Impacto alto" value={alto} sub="marcadas como relevantes" />
    <Kpi icon="evento" label="Próximo hecho" value={`+${ev.inDays}`} unit="d" sub={catMeta(ev.category).name+' · '+fmtDay(ev.date)} />
    <Kpi icon="guardadas" label="Guardadas" value={feed.saved.size} sub="en esta sesión" />
  </div></div>;
}

// ── Category filter bar ──
function SourceFilter({ feed, extra }){
  const order = window.CAT_ORDER;
  const allOn = feed.cats.size===order.length;
  return <div className="n-filterbar">
    <div className="n-filtergroup">
      <span className="fb-flab">Categoría</span>
      <div className="fb-pills">
        <button className={`fb-pill ${allOn?'active':''}`} onClick={()=>feed.toggleCat('all')}>Todas</button>
        {order.map(id=>{ const c=catMeta(id); const on=feed.cats.has(id);
          return <button key={id} className={`fb-pill ${on?'active':''}`} onClick={()=>feed.toggleCat(id)}>
            <span className="pdot" style={{background:c.color}}></span>{c.name}
            <span className="pcount">{feed.counts[id]}</span>
          </button>; })}
      </div>
    </div>
    {extra}
    <div className="n-filterbar-right">
      <label className="n-savedtoggle" onClick={()=>feed.setOnlySaved(!feed.onlySaved)}>
        <span className={`n-act ${feed.onlySaved?'on':''}`} style={{pointerEvents:'none'}}><IconBookmark filled={feed.onlySaved}/>Solo guardadas</span>
      </label>
    </div>
  </div>;
}

// ── Shell: navbar + subheader + kpis + filtros + footer ──
function NavShell({ children }){
  const flip = ()=>document.body.classList.toggle('theme-dark');
  const goMacro = ()=>{ try{ location.href='Macroeconomia.html'; }catch(e){} };
  return <div className="fb-app">
    <nav className="fb-navbar">
      <div className="fb-navbar-left">
        <span className="fb-logo">FinanzasBo</span>
        <div className="fb-tabs">
          <button className="fb-tab">Dólar</button>
          <div className="fb-tab-wrap">
            <button className="fb-tab" onClick={goMacro}>Macro <span className="fb-caret">▾</span></button>
            <div className="fb-flyout">
              <button className="fb-sublink" onClick={goMacro}>Riesgo País</button>
              <span className="fb-sub-sep">|</span>
              <button className="fb-sublink" onClick={goMacro}>Inflación</button>
            </div>
          </div>
          <button className="fb-tab">Rendimientos DPF</button>
          <button className="fb-tab">BBV</button>
          <button className="fb-tab">Guía</button>
          <button className="fb-tab active">Noticias</button>
        </div>
      </div>
      <div className="fb-navbar-right">
        <button className="fb-icon-btn">ES</button>
        <button className="fb-icon-btn" onClick={flip} title="Cambiar tema">☾</button>
      </div>
    </nav>
    {children}
    <div className="fb-footer">FinanzasBo · agregador de prensa boliviana e internacional · El Deber · Correo del Sur · Unitel · La Razón · Bloomberg · <strong>contenido de ejemplo</strong></div>
  </div>;
}
function SubHeader(){
  return <div className="fb-subheader">
    <div>
      <h1>Noticias</h1>
      <div className="fb-subtitle">Hechos relevantes de la prensa boliviana e internacional, por categoría · Actualizado 03-jun, 09:09 a. m.</div>
    </div>
    <div className="fb-subheader-stats">
      <div className="fb-stat"><span className="fb-stat-label">Visitas hoy</span><span className="fb-stat-value">3</span></div>
      <div className="fb-stat"><span className="fb-stat-label">Visitas mes</span><span className="fb-stat-value">11</span></div>
    </div>
  </div>;
}

Object.assign(window, {
  useFeed, NavShell, SubHeader, KpiStrip, SourceFilter,
  SrcTag, CatTag, Topic, Impact, ReadBtn, SaveBtn, IconCheck, IconBookmark, IconChevron,
  fmtDay, fmtDayLong, relDay, srcMeta, catMeta, TODAY,
});
```

### 1.5 `variant-d.jsx` — ★ LA VISTA ELEGIDA: terminal con slider de 30 días y tabla con scroll interno

```jsx
/* variant-d.jsx — Terminal / tabla densa (estilo BBV) con fila expandible,
   scroll interno en la tabla y tira horizontal de los últimos 30 días. */

function fdAddDays(iso, delta){
  const [y,m,d]=iso.split('-').map(Number);
  const dt=new Date(y,m-1,d+delta);
  return `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
}
/* Slider de los últimos 30 días: la bolita se mueve día a día y filtra la tabla.
   Flechas a los costados para avanzar/retroceder de uno en uno. */
function DayStrip({ day, setDay, countByDay }){
  const days = React.useMemo(()=>Array.from({length:30},(_,i)=>fdAddDays(window.TODAY,i-29)),[]); // [0]=hace 29 días … [29]=hoy
  const idx = day? days.indexOf(day) : 29;
  const p = idx/29;
  const sel = day || window.TODAY;
  const c = countByDay[sel]||0;
  const step = (d)=>{
    const from = day? days.indexOf(day) : 29;
    const next = Math.min(29, Math.max(0, from+d));
    setDay(days[next]);
  };
  const halfW = day? 64 : 92;
  const posStyle = { left:`clamp(${halfW}px, calc((100% - 16px) * ${p} + 8px), calc(100% - ${halfW}px))` };
  return <div className="section" style={{marginBottom:14}}>
    <div className="fd-daystrip">
      <span className="fb-flab">Últimos 30 días</span>
      <button className="n-act icon" title="Día anterior" onClick={()=>step(-1)} disabled={idx===0} style={{opacity:idx===0?.35:1}}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
      </button>
      <div className="fd-slider">
        <div className="fd-bubble" style={posStyle}>
          {day? <>{window.fmtDayLong(day)} <span className="bcount">· {c} {c===1?'nota':'notas'}</span></>
               : <>últimos 30 días <span className="bcount">· {window.NEWS.length} notas</span></>}
        </div>
        <div className="fd-track">
          {days.map((d,i)=> (countByDay[d]||0)>0 || d===window.TODAY
            ? <span key={d} className={`fd-mark ${d===window.TODAY?'today':''}`} style={{left:`calc((100% - 16px) * ${i/29} + 8px)`}} title={window.fmtDayLong(d)}></span>
            : null)}
        </div>
        <input className="fd-range" type="range" min="0" max="29" step="1" value={idx}
               onChange={e=>setDay(days[Number(e.target.value)])} aria-label="Navegar por día"/>
        <div className="fd-scale"><span>{window.fmtDay(days[0])}</span><span>hoy · {window.fmtDay(window.TODAY)}</span></div>
      </div>
      <button className="n-act icon" title="Día siguiente" onClick={()=>step(1)} disabled={idx===29} style={{opacity:idx===29?.35:1}}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="9 18 15 12 9 6"/></svg>
      </button>
      <button className={`fb-pill ${day===null?'active':''}`} onClick={()=>setDay(null)} style={{flex:'none'}}>Todos los días</button>
    </div>
  </div>;
}

function VariantD(){
  const feed = window.useFeed('d');
  const { items, read, saved, expanded } = feed;
  const [day, setDay] = React.useState(null);
  const countByDay = React.useMemo(()=>{
    const c={}; window.NEWS.forEach(n=>{ c[n.date]=(c[n.date]||0)+1; }); return c;
  },[]);
  const visible = React.useMemo(()=> day? items.filter(n=>n.date===day) : items, [items, day]);
  return <window.NavShell>
    <window.SubHeader/>
    <window.KpiStrip feed={feed}/>
    <div className="fb-content">
      <window.SourceFilter feed={feed}/>
      <DayStrip day={day} setDay={setDay} countByDay={countByDay}/>
      <div className="section">
        <div className="section-header"><div>
          <h2>Tablero de hechos · vista terminal</h2>
          <p>Densa, ordenable por hora · clic en una fila para ver el detalle · {day? window.fmtDayLong(day) : 'últimos 30 días'} · {visible.length} {visible.length===1?'nota':'notas'}</p>
        </div></div>
        <div className="section-body" style={{paddingTop:0,paddingLeft:0,paddingRight:0,paddingBottom:0}}>
          <div className="fd-scroll">
          <table className="fb-data-table">
            <thead><tr>
              <th style={{width:96}}>Fecha</th>
              <th style={{width:64}}>Hora</th>
              <th style={{width:90}}>Fuente</th>
              <th>Titular</th>
              <th style={{width:170}}>Categoría</th>
              <th style={{width:96}}>Impacto</th>
              <th style={{width:120,textAlign:'right'}}>Acción</th>
            </tr></thead>
            <tbody>
              {visible.length===0 && <tr><td colSpan="7"><div className="n-empty">No hay notas {day?`para el ${window.fmtDayLong(day)}`:'para los filtros seleccionados'}.</div></td></tr>}
              {visible.map(n=>{
                const isRead=read.has(n.id), isOpen=expanded===n.id;
                return <React.Fragment key={n.id}>
                  <tr style={{cursor:'pointer',opacity:isRead?.6:1}} onClick={()=>feed.toggleExpand(n.id)}>
                    <td className="mono" style={{color:'var(--text-secondary)'}}>{window.fmtDay(n.date)}</td>
                    <td className="mono" style={{color:'var(--text-muted)'}}>{n.time}</td>
                    <td><window.SrcTag id={n.source}/></td>
                    <td style={{fontFamily:'var(--font-display)',fontWeight:600,color:'var(--text-primary)'}}>{n.title}</td>
                    <td><div style={{display:'flex',gap:5,flexWrap:'wrap',alignItems:'center'}}><window.CatTag id={n.category}/>{n.topics.slice(0,1).map(t=><window.Topic key={t} t={t}/>)}</div></td>
                    <td><window.Impact level={n.impact}/></td>
                    <td onClick={e=>e.stopPropagation()} style={{textAlign:'right'}}>
                      <div style={{display:'inline-flex',gap:5}}>
                        <window.ReadBtn on={isRead} onClick={()=>feed.toggleRead(n.id)} iconOnly/>
                        <window.SaveBtn on={saved.has(n.id)} iconOnly onClick={()=>feed.toggleSave(n.id)}/>
                        <button className="n-act icon" onClick={()=>feed.toggleExpand(n.id)}><window.IconChevron open={isOpen}/></button>
                      </div>
                    </td>
                  </tr>
                  {isOpen && <tr><td colSpan="7" style={{background:'var(--bg-primary)'}}>
                    <div style={{padding:'4px 2px',fontSize:'var(--text-md)',color:'var(--text-secondary)',lineHeight:1.6,maxWidth:880}}>
                      {n.detail}
                      <div className="fd-meta" style={{display:'flex',gap:18,marginTop:10,fontFamily:'var(--font-mono)',fontSize:'var(--text-xs)',color:'var(--text-muted)',flexWrap:'wrap'}}>
                        <span>Fuente: <b style={{color:'var(--text-secondary)'}}>{window.srcMeta(n.source).full}</b></span>
                        <span>Ref: <b style={{color:'var(--text-secondary)'}}>{n.sourceNote}</b></span>
                      </div>
                    </div>
                  </td></tr>}
                </React.Fragment>;
              })}
            </tbody>
          </table>
          </div>
        </div>
        <div className="fb-footer" style={{borderTop:'1px solid var(--border-color)'}}>Fuentes: El Deber · Correo del Sur · Unitel · La Razón · Bloomberg — contenido de ejemplo</div>
      </div>
    </div>
  </window.NavShell>;
}
window.VariantD = VariantD;
```

### 1.6 `variant-a.jsx` — Feed cronológico (no elegida)

```jsx
/* variant-a.jsx — Feed cronológico (filas) */
function VariantA(){
  const feed = window.useFeed('a');
  const { items, read, saved, expanded } = feed;
  const shown = items.slice(0,15);
  return <window.NavShell>
    <window.SubHeader/>
    <window.KpiStrip feed={feed}/>
    <div className="fb-content">
      <window.SourceFilter feed={feed}/>
      <div className="section">
        <div className="section-header">
          <div>
            <h2>Feed de hechos relevantes</h2>
            <p>Orden cronológico inverso · mostrando {shown.length} de {items.length} notas</p>
          </div>
        </div>
        <div>
          {items.length===0 && <div className="n-empty">No hay notas para los filtros seleccionados.</div>}
          {shown.map(n=>{
            const isRead=read.has(n.id), isOpen=expanded===n.id;
            return <div key={n.id} className={`feed-row ${isRead?'is-read':''}`}>
              <div className="feed-time">
                <span className="ft-day">{window.fmtDay(n.date)}</span>
                {n.time}
              </div>
              <div className="feed-main">
                <div className="feed-head">
                  <window.SrcTag id={n.source}/>
                  <window.CatTag id={n.category}/>
                  <window.Impact level={n.impact}/>
                  {isRead && <span className="topic-tag">leído</span>}
                </div>
                <div className="feed-title" onClick={()=>feed.toggleExpand(n.id)}>{n.title}</div>
                <div className="feed-sum">{n.summary}</div>
                <div className="feed-tags">
                  {n.topics.map(t=><window.Topic key={t} t={t}/>)}
                  <button className="n-act" style={{marginLeft:'auto'}} onClick={()=>feed.toggleExpand(n.id)}>
                    {isOpen?'Cerrar':'Ver detalle'} <window.IconChevron open={isOpen}/>
                  </button>
                </div>
                {isOpen && <div className="feed-detail">
                  {n.detail}
                  <div className="fd-meta">
                    <span>Fuente: <b>{window.srcMeta(n.source).full}</b></span>
                    <span>Ref: <b>{n.sourceNote}</b></span>
                    <span><b>{window.fmtDayLong(n.date)}</b> · {n.time}</span>
                  </div>
                </div>}
              </div>
              <div className="feed-actions">
                <window.ReadBtn on={isRead} onClick={()=>feed.toggleRead(n.id)}/>
                <window.SaveBtn on={saved.has(n.id)} iconOnly onClick={()=>feed.toggleSave(n.id)}/>
              </div>
            </div>;
          })}
        </div>
      </div>
    </div>
  </window.NavShell>;
}
window.VariantA = VariantA;
```

### 1.7 `variant-b.jsx` — Línea de tiempo (no elegida)

```jsx
/* variant-b.jsx — Timeline vertical con dots por fuente, agrupado por día */
function VariantB(){
  const feed = window.useFeed('b');
  const { items, read, saved, expanded } = feed;
  // agrupar por día (sólo lo más reciente; el dataset completo vive en la vista terminal)
  const shown = items.slice(0,15);
  const groups = [];
  shown.forEach(n=>{ let g=groups.find(x=>x.date===n.date); if(!g){g={date:n.date,items:[]};groups.push(g);} g.items.push(n); });
  return <window.NavShell>
    <window.SubHeader/>
    <window.KpiStrip feed={feed}/>
    <div className="fb-content">
      <window.SourceFilter feed={feed}/>
      <div className="section">
        <div className="section-header">
          <div>
            <h2>Línea de tiempo
              <span className="help-tip" tabIndex="0"><span className="help-icon">i</span><span className="help-pop">El color del punto indica la fuente; relleno sólido marca impacto alto.</span></span>
            </h2>
            <p>Secuencia de hechos por día · color = fuente · mostrando {shown.length} de {items.length} notas</p>
          </div>
        </div>
        <div style={{padding:'2px 0 8px'}}>
          {items.length===0 && <div className="n-empty">No hay notas para los filtros seleccionados.</div>}
          {groups.map(g=>(
            <div key={g.date} className="tl-daygroup">
              <div className="tl-daylabel">{window.relDay(g.date)} · {window.fmtDayLong(g.date)} <span className="tl-count">{g.items.length} notas</span></div>
              {g.items.map(n=>{
                const isRead=read.has(n.id), isOpen=expanded===n.id, s=window.srcMeta(n.source);
                return <div key={n.id} className={`tl-item ${isRead?'is-read':''}`}>
                  <div className="tl-time">{n.time}</div>
                  <div className="tl-rail"><span className={`tl-dot ${n.impact}`} style={{'--src-color':s.color}}></span></div>
                  <div className="tl-body">
                    <div className="tl-meta"><window.SrcTag id={n.source}/><window.CatTag id={n.category}/><window.Impact level={n.impact}/></div>
                    <div className="tl-title" onClick={()=>feed.toggleExpand(n.id)}>{n.title}</div>
                    <div className="tl-sum">{n.summary}</div>
                    {isOpen && <div className="feed-detail" style={{marginTop:10}}>
                      {n.detail}
                      <div className="fd-meta">
                        <span>Fuente: <b>{s.full}</b></span>
                        <span>Ref: <b>{n.sourceNote}</b></span>
                      </div>
                    </div>}
                    <div className="tl-actions">
                      {n.topics.slice(0,2).map(t=><window.Topic key={t} t={t}/>)}
                      <button className="n-act" onClick={()=>feed.toggleExpand(n.id)}>{isOpen?'Cerrar':'Detalle'} <window.IconChevron open={isOpen}/></button>
                      <window.ReadBtn on={isRead} onClick={()=>feed.toggleRead(n.id)}/>
                      <window.SaveBtn on={saved.has(n.id)} iconOnly onClick={()=>feed.toggleSave(n.id)}/>
                    </div>
                  </div>
                </div>;
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  </window.NavShell>;
}
window.VariantB = VariantB;
```

### 1.8 `variant-c.jsx` — Destacada + columna (no elegida)

```jsx
/* variant-c.jsx — Destacada + columna de titulares + tira de calendario */
function VariantC(){
  const feed = window.useFeed('c');
  const { items, read, saved, expanded } = feed;
  // destacada: primera de impacto alto, si no la primera
  const lead = items.find(n=>n.impact==='alto') || items[0];
  const rest = items.filter(n=>n!==lead).slice(0,14);
  const isOpen = lead && expanded===lead.id;
  return <window.NavShell>
    <window.SubHeader/>
    <window.KpiStrip feed={feed}/>
    <div className="fb-content">
      <window.SourceFilter feed={feed}/>
      {items.length===0 && <div className="section"><div className="n-empty">No hay notas para los filtros seleccionados.</div></div>}
      {lead && <div className="c-grid" style={{marginBottom:16}}>
        <div className="lead-card">
          <div className="lead-banner">
            <div className="lead-kicker"><window.SrcTag id={lead.source}/><window.CatTag id={lead.category}/><window.Impact level={lead.impact}/><span className="topic-tag" style={{marginLeft:'auto'}}>destacada</span></div>
            <div className="lead-title" onClick={()=>feed.toggleExpand(lead.id)}>{lead.title}</div>
          </div>
          <div className="lead-body">
            <div className="lead-lede">{lead.summary}</div>
            {isOpen && <div className="lead-lede">{lead.detail}</div>}
            <div className="feed-tags" style={{marginTop:12}}>{lead.topics.map(t=><window.Topic key={t} t={t}/>)}</div>
            <div className="lead-foot">
              <span style={{fontFamily:'var(--font-mono)',fontSize:'var(--text-xs)',color:'var(--text-muted)'}}>{window.fmtDayLong(lead.date)} · {lead.time} · {lead.sourceNote}</span>
              <div style={{display:'flex',gap:6}}>
                <button className="n-act" onClick={()=>feed.toggleExpand(lead.id)}>{isOpen?'Cerrar':'Ver detalle'} <window.IconChevron open={isOpen}/></button>
                <window.ReadBtn on={read.has(lead.id)} onClick={()=>feed.toggleRead(lead.id)}/>
                <window.SaveBtn on={saved.has(lead.id)} iconOnly onClick={()=>feed.toggleSave(lead.id)}/>
              </div>
            </div>
          </div>
        </div>
        <div className="side-list">
          {rest.map(n=>{ const isRead=read.has(n.id);
            return <div key={n.id} className={`side-item ${isRead?'is-read':''}`} onClick={()=>feed.toggleRead(n.id)}>
              <div className="side-meta">
                <window.SrcTag id={n.source}/>
                <window.CatTag id={n.category}/>
                {n.impact==='alto' && <span className="n-readdot" title="impacto alto"></span>}
                <span className="side-time">{window.relDay(n.date)} · {n.time}</span>
              </div>
              <div className="side-title">{n.title}</div>
            </div>;
          })}
        </div>
      </div>}

      <div className="section">
        <div className="section-header"><div>
          <h2>Agenda · próximos hechos</h2>
          <p>Lo que la prensa cubrirá en los próximos días</p>
        </div></div>
        <div className="section-body">
          <div className="cal-strip">
            {window.EVENTS.map(e=>(
              <div key={e.id} className="cal-card">
                <div><span className="cal-date">{window.fmtDay(e.date)}</span><span className="cal-in">en {e.inDays}d</span></div>
                <div className="cal-title">{e.title}</div>
                <div className="cal-src"><window.CatTag id={e.category}/></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  </window.NavShell>;
}
window.VariantC = VariantC;
```

### 1.9 `variant-e.jsx` — Tablero por medio (no elegida)

```jsx
/* variant-e.jsx — Tablero por medio (una columna por portal) + agenda */
function VariantE(){
  const feed = window.useFeed('e');
  const { read, saved } = feed;
  const order = window.PORTAL_ORDER;
  const all = window.NEWS.slice().sort((a,b)=>(b.date+b.time).localeCompare(a.date+a.time));
  const byPortal = id => all
    .filter(n=>n.source===id)
    .filter(n=>feed.cats.has(n.category))
    .filter(n=>!feed.onlySaved||saved.has(n.id));
  return <window.NavShell>
    <window.SubHeader/>
    <window.KpiStrip feed={feed}/>
    <div className="fb-content">
      <window.SourceFilter feed={feed}/>
      <div className="section" style={{background:'transparent',border:'none',overflow:'visible'}}>
        <div className="section-header" style={{border:'none',padding:'0 2px 12px'}}><div>
          <h2>Tablero por medio</h2>
          <p>Una columna por portal · lo más reciente arriba · el filtro de categoría aplica a todas las columnas · clic en una nota para marcarla leída</p>
        </div></div>
        <div className="board-grid" style={{gridTemplateColumns:`repeat(${order.length},1fr)`}}>
          {order.map(id=>{ const s=window.srcMeta(id); const list=byPortal(id); const shown=list.slice(0,3);
            return <div key={id} className="board-col">
              <div className="board-head" style={{'--src-color':s.color}}>
                <span className="bh-name">{s.name}</span>
                <span className="bh-count">{list.length}</span>
              </div>
              {list.length===0 && <div className="board-empty">sin notas</div>}
              {shown.map(n=>{ const isRead=read.has(n.id);
                return <div key={n.id} className={`board-item ${isRead?'is-read':''}`} onClick={()=>feed.toggleRead(n.id)}>
                  <div className="board-time">
                    {window.relDay(n.date)} · {n.time}
                    {n.impact==='alto' && <span className="n-readdot" style={{marginLeft:'auto'}} title="impacto alto"></span>}
                  </div>
                  <div className="board-title">{n.title}</div>
                  <div className="board-sum">{n.summary}</div>
                  <div style={{display:'flex',gap:5,marginTop:8,alignItems:'center'}} onClick={e=>e.stopPropagation()}>
                    <window.CatTag id={n.category}/>
                    <window.SaveBtn on={saved.has(n.id)} iconOnly onClick={()=>feed.toggleSave(n.id)}/>
                  </div>
                </div>;
              })}
              {list.length>shown.length && <div className="board-empty">+{list.length-shown.length} notas más</div>}
            </div>;
          })}
        </div>
        <div className="section" style={{marginTop:16}}>
          <div className="section-header"><div>
            <h2>Agenda · próximos hechos</h2>
            <p>Lo que la prensa cubrirá en los próximos días</p>
          </div></div>
          <div className="section-body">
            <div className="cal-strip">
              {window.EVENTS.map(e=>(
                <div key={e.id} className="cal-card">
                  <div><span className="cal-date">{window.fmtDay(e.date)}</span><span className="cal-in">en {e.inDays}d</span></div>
                  <div className="cal-title">{e.title}</div>
                  <div className="cal-src"><window.CatTag id={e.category}/></div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  </window.NavShell>;
}
window.VariantE = VariantE;
```

---

## 2 · Spec de interacciones (variante D)

### 2.1 Chips de categoría
- **Selección MÚLTIPLE** (estado: `Set` de ids de categoría). Cada chip togglea su categoría on/off de forma independiente.
- **"Todas"**: si todas están activas → las desactiva todas (set vacío, tabla vacía); si no → activa todas. Está "active" sólo cuando el set está completo.
- Filtran las **filas de la tabla** (campo `category` de cada nota). El filtro se **intersecta** con "Solo guardadas" y con el día del slider.
- El **badge numérico** de cada chip es el conteo de notas de esa categoría en el **dataset completo** (no cambia con los demás filtros).
- Estado inicial: todas activas.

### 2.2 Toggle "Solo guardadas"
- Toggle booleano. ON → la tabla muestra sólo notas marcadas con bookmark en la sesión. Se intersecta con categoría + día.
- Estado inicial: OFF. No persiste (estado en memoria; se pierde al recargar).

### 2.3 Timeline de 30 días (slider)
- `<input type="range" min=0 max=29 step=1>`: posición 0 = hace 29 días, posición 29 = HOY. **Cada paso de la bolita = 1 día.**
- Mover la bolita selecciona **un día exacto** y filtra la tabla a las notas de ese día (campo `date`).
- **Burbuja** sobre la bolita (sigue su posición, clampeada en los extremos para no desbordar): con día seleccionado muestra `"{día de semana} {dd} {mes} · {n} notas"`; sin selección muestra `"últimos 30 días · {total} notas"`. El conteo de la burbuja es del **dataset completo** de ese día (no filtrado).
- **Marcas en la pista**: un punto por cada día con ≥1 nota, posicionado en su fecha; HOY lleva un punto outline (borde, fondo claro). Las marcas no son clickeables (decorativas).
- **Flechas prev/next** (a los costados): mueven la selección ±1 día, con clamp en los extremos (se deshabilitan en día 0 / día 29). Si no hay día seleccionado, prev arranca desde ayer.
- **Botón "Todos los días"**: limpia el filtro de día (estado `null`); la bolita queda en el extremo derecho (hoy) pero sin filtrar. Es el estado inicial y se marca "active" cuando está vigente.
- **Teclado**: el slider nativo responde a ←/→ cuando tiene foco.
- Etiquetas fijas bajo la pista: fecha más antigua (izq.) y `"hoy · {dd} {mes}"` (der.).

### 2.4 Tabla densa (tablero de hechos)
- **Columnas**: Fecha (dd mes, mono) · Hora (HH:MM, mono) · Fuente (tag con dot de color) · Titular (display font, semibold) · Categoría (tag con dot + primer topic como chip) · Impacto (3 barras + texto) · Acción (3 botones icon).
- **Orden**: fijo, descendente por `date+time` (lo más reciente arriba). **Los headers NO son clickeables** — el copy "ordenable por hora" del subtítulo es aspiracional; en el mockup no hay sort interactivo. Si lo implementan, el orden por defecto es ese.
- **Click en fila** → togglea la **fila de detalle expandida** (acordeón de UNA sola: abrir una cierra la anterior; re-click cierra). La fila expandida (colspan 7, fondo `--bg-primary`) muestra: el párrafo `detail` completo + meta en mono: `Fuente: {nombre completo del portal}` y `Ref: {sourceNote}`.
- **Acciones por fila** (con `stopPropagation`, no expanden):
  - **Check** = toggle LEÍDO. Fila leída → opacity 0.6. Tooltip "Marcar como leído/no leído". No filtra nada.
  - **Bookmark** = toggle GUARDADA. Alimenta el filtro "Solo guardadas" y el KPI "Guardadas". Icono relleno cuando está activa.
  - **Chevron** = idéntico al click en fila (expande/colapsa; rota 180° abierto).
- **Scroll interno**: el cuerpo de la tabla vive en un contenedor `max-height: 520px; overflow-y: scroll` con **scrollbar vertical siempre visible** (11px) y `<thead>` **sticky** (top 0, fondo opaco, sombra de 1px como borde).
- **Estado vacío**: una fila colspan 7 con texto "No hay notas para el {fecha larga}." (con día seleccionado) o "No hay notas para los filtros seleccionados." (sin día).

### 2.5 KPI cards
**Ninguna es interactiva** (sólo display). Significados:
- **Noticias hoy**: conteo de notas con `date === HOY` (dataset completo). Sub: hora de última actualización (estática en el mock).
- **Portales**: número de medios monitoreados (5, largo de `PORTAL_ORDER`).
- **Impacto alto**: conteo de notas con `impact === 'alto'` en el dataset completo.
- **Próximo hecho +5d**: días que faltan para el **próximo evento de agenda** (`EVENTS[0]`, lista ordenada de hechos futuros que la prensa cubrirá; ej. "INE publica el IPC de mayo" el 08-jun = hoy+5). Sub: categoría del evento + fecha. Es un dato de agenda editorial, no derivado de las noticias.
- **Guardadas**: `saved.size` de la sesión actual (arranca en 0; no persiste).

### 2.6 Estados no visibles en screenshot / otros
- **Persistencia**: NINGUNA. Leído/guardado/filtros/día son estado React en memoria; recargar resetea todo. (En producción querrán persistir leído/guardado por usuario.)
- **Tema oscuro**: toggle ☾ en el navbar alterna `body.theme-dark`; todos los tokens (incl. colores semánticos, §4) tienen variante dark.
- **Responsive**: NO implementado — el mockup es desktop fijo a 1180px de ancho. No hay breakpoints.
- **Hover de fila**: `rgba(44,74,107,.04)` (dark: `rgba(255,255,255,.04)`); cursor pointer.
- **Navbar/flyout "Macro"**: hover muestra sublinks (Riesgo País | Inflación) que navegan a la página Macroeconomía del mockup; el resto de tabs del navbar son decorativas.
- **Footer de sección y de página**: estáticos, con disclaimer de contenido de ejemplo.

---

## 3 · Modelo de datos

### 3.1 Objeto noticia

| Campo | Tipo | Notas |
|---|---|---|
| `id` | `string` | único (`n01…n15` curadas; `g{yyyymmdd}x{i}` generadas) |
| `source` | `'eldeber' \| 'correosur' \| 'unitel' \| 'larazon' \| 'bloomberg'` | id de portal |
| `category` | `'economia' \| 'hidrocarburos' \| 'agro' \| 'mineria' \| 'mundo' \| 'politica'` | taxonomía principal (filtro) |
| `date` | `string` `'YYYY-MM-DD'` | día de publicación |
| `time` | `string` `'HH:MM'` | hora (24h); orden = `date+time` desc |
| `title` | `string` | titular (columna Titular) |
| `summary` | `string` | 1 frase; usada en las vistas de cards/columnas, NO en la fila de la tabla D |
| `detail` | `string` | párrafo del detalle expandido |
| `topics` | `string[]` | tags libres; la tabla muestra sólo el primero como chip |
| `impact` | `'alto' \| 'medio' \| 'bajo'` | nivel de impacto |
| `sourceNote` | `string` | referencia "Portal · Sección", mostrada en el detalle como "Ref:" |

**Ejemplo 1 (curada):**
```js
{
  id:'n01', source:'bloomberg', category:'economia', date:'2026-06-03', time:'08:40',
  title:'La prima del dólar paralelo en Bolivia supera el 40% pese a la intervención del BCB',
  summary:'El USDT/BOB en el mercado P2P cotiza con una prima cercana al 43% sobre el tipo de cambio oficial de 6,96.',
  detail:'Bloomberg Línea reporta que la brecha entre el dólar oficial y el paralelo se mantiene por encima del 40% ante la escasez de reservas líquidas. La autoridad monetaria amplió cupos de venta a importadores priorizados, pero la demanda sigue canalizándose al mercado informal de stablecoins.',
  topics:['Dólar','Reservas'], impact:'alto', sourceNote:'Bloomberg Línea · Mercados',
}
```

**Ejemplo 2 (generada):**
```js
{
  id:'g20260505x2', source:'unitel', category:'hidrocarburos', date:'2026-05-05', time:'08:20',
  title:'Filas de hasta 3 horas por diésel en surtidores de La Paz',
  summary:'Transportistas y particulares reportan espera prolongada para cargar combustible.',
  detail:'En surtidores de La Paz se registraron filas de hasta 3 horas para cargar diésel. Los administradores señalan que la provisión llega de forma irregular y se agota en pocas horas.',
  topics:['Diésel','Transporte'], impact:'medio', sourceNote:'Unitel · Energía',
}
```

### 3.2 Catálogos

- **Categorías** (orden de los chips): `economia` Economía · `hidrocarburos` Hidrocarburos · `agro` Agro · `mineria` Minería · `mundo` Mundo · `politica` Política.
- **Impacto**: `alto` (3 barras) · `medio` (2 barras) · `bajo` (1 barra).
- **Fuentes/portales** (orden): `eldeber` "El Deber" (full: "El Deber · Santa Cruz") · `correosur` "Correo del Sur" (· Sucre) · `unitel` "Unitel" (· red nacional) · `larazon` "La Razón" (· La Paz) · `bloomberg` "Bloomberg" (full: "Bloomberg Línea").
- **Evento de agenda** (KPI "Próximo hecho"): `{ id, category, date:'YYYY-MM-DD', inDays:number, title }`.

---

## 4 · Colores semánticos (hex exactos)

### Categorías (dot del cat-tag, marcas, pills)

| Categoría | Light | Dark |
|---|---|---|
| Economía | `#2c4a6b` | `#6ea3d9` |
| Hidrocarburos | `#b3473b` | `#e07a6e` |
| Agro | `#2c6e49` | `#4fb07a` |
| Minería | `#8a6d3b` | `#c79a5a` |
| Mundo | `#5b6ba8` | `#8b9bd6` |
| Política | `#6b7d92` | `#8a96aa` |

### Fuentes / portales (dot del src-tag)

| Portal | Light | Dark |
|---|---|---|
| El Deber | `#1e6b8c` | `#5aa9c7` |
| Correo del Sur | `#7a5ea8` | `#a98ed6` |
| Unitel | `#c0564a` | `#e07a6e` |
| La Razón | `#2c4a6b` | `#6ea3d9` |
| Bloomberg | `#c47e2a` | `#e0a44e` |

### Impacto (color del texto + barras; barras apagadas = mismo color a opacity .22)

| Nivel | Light | Dark |
|---|---|---|
| Alto | `#2c4a6b` | `#9cc3e8` |
| Medio | `#5589c0` | `#6ea3d9` |
| Bajo | `#8c9aab` | `#8c9aab` (sin override) |
