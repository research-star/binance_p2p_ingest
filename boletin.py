#!/usr/bin/env python3
"""
boletin.py — Tarjeta diaria "Cotización del dólar" (imagen social) para
`/boletin-4k9x/index.html`.

Genera una página standalone, pública y NO linkeada, con:
  - una TARJETA 850×850 (SVG self-contained, foto embebida en base64) que
    replica el diseño aprobado por Diego: masthead FinanzasBo + foto del billete
    + dos columnas OFICIAL / BINANCE con deltas "vs. día anterior" / "vs. semana
    anterior" en BOB, y footer con la fuente + finanzasbo.com.
  - botones "Copiar imagen" (SVG→canvas→PNG al portapapeles) y "Descargar PNG".
  - dos captions para copy-paste: WhatsApp (negrita con `*`) y Facebook (plano).

Los VALORES salen del MISMO dict que la tab Dólar (`dashboard.process_data`), para
que la imagen y el dashboard nunca discrepen:
  - OFICIAL = TCO (`meta.bcb_tco_last` / vigente-hoy de `bcb_tco_history`), la pata
    compra del oficial (RD 88/2026). Es el número grande del card del BCB.
  - BINANCE = USDT compra = último `ts_metrics.vb10` (VWAP 10% profundidad, lado
    BUY = lo que pagás). Mismo número que el KPI "USDT compra" del dashboard.
  - Deltas día/semana = valor ACTUAL − CIERRE del día calendario anterior /
    del día calendario de hace 7 días (zona BOT, UTC-4). NO es una ventana móvil
    de 24h/168h: es el cierre de ayer y el cierre de hace una semana (con
    fallback al cierre disponible más reciente si ese día tiene hueco).

Reglas de emisión (heredadas del boletín anterior):
  - Si falta un VALOR BASE (TCO actual o USDT compra actual) → `BoletinDataError`;
    el caller (`dashboard.py`) NO sobrescribe el archivo anterior (un boletín con
    hueco es peor que uno viejo).
  - Delta sin cierre de referencia (serie corta / hueco) → se muestra "—" (hueco
    visible, no se rellena).
  - Fecha SIEMPRE derivada de runtime, zona BOT.
  - Números con punto decimal (formato del card aprobado), 2 decimales.

NO llama a la API de Anthropic. NO escribe al VPS. Repo-only.
"""
from __future__ import annotations

import base64
import html as _html
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# ── Constantes ──────────────────────────────────────────────────────────────

BOLETIN_DIRNAME = "boletin-4k9x"           # ruta standalone, fuera del SPA
BOT_TZ = timezone(timedelta(hours=-4))     # hora de Bolivia (UTC-4, sin DST)
DELTA_EPS = 0.005                          # |Δ| < eps → se muestra como "=0.00"

# Assets embebidos (base64 en el SVG en tiempo de generación → la página queda
# self-contained, nada extra que servir): foto del billete + las 2 webfonts que
# el render canónico usa de verdad (spec_fonts.json: Newsreader 600 en el
# masthead; Inter 800 en la fecha — Aptos nunca renderiza en Chromium).
_ASSETS_DIR = Path(__file__).resolve().parent / "boletin_assets"
PHOTO_PATH = _ASSETS_DIR / "dolar_card_bg.png"
FONT_NEWSREADER_PATH = _ASSETS_DIR / "newsreader_400-700_latin.woff2"
FONT_INTER800_PATH = _ASSETS_DIR / "inter_800_latin.woff2"
_PHOTO_W, _PHOTO_H = 612, 408              # dimensiones nativas del PNG

MESES_MAY = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
             "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]

# Paleta del diseño (extraída del render aprobado)
C_BG = "#F5EADF"        # crema de las bandas          rgb(245,234,223)
C_INK = "#211E1B"       # texto principal              rgb(33,30,27)
C_TAN = "#A08970"       # acento tan                   rgb(160,137,112)
C_MUTED = "#6B6256"     # tagline                      rgb(107,98,86)
C_BORDER = "#BCAC9A"    # marco + reglas + divisor     rgb(188,172,154)

# Stacks tipográficos EXACTOS del render canónico (spec_fonts.json § roles).
# En Windows/Chromium: 'Helvetica Neue' no existe → Arial; 'aptos' no resuelve
# (vive en el VFS privado de Office) → cae a Times New Roman regular, que es lo
# que la referencia ref_1700.png realmente muestra en los "vs. …".
FONT_SERIF = "'Times New Roman', serif"
FONT_SANS = "'Helvetica Neue', Arial, sans-serif"
FONT_BRAND = "Newsreader, 'Times New Roman', serif"
FONT_TAGLINE = "'microsoft himalaya'"
FONT_DATE = "'Aptos Display', Aptos, Inter, sans-serif"
FONT_VS = "aptos, 'Times New Roman', serif"

# Geometría medida del original (spec_geometry.json; viewBox 0 0 850 850,
# y de cada <text> = BASELINE medida, x = centro medido, text-anchor=middle).
CX = 425                         # eje central de la tarjeta
CX_OF, CX_BI = 212.5, 637.5      # centros de columna OFICIAL / BINANCE
# Centros de los sub-stats (delta + "vs. …"); asimétricos respecto del centro
# de columna por los margin de la fila flex del original (medidos, no derivados)
CX_OF_DIA, CX_OF_SEM = 125.31, 299.78
CX_BI_DIA, CX_BI_SEM = 550.31, 724.78
# Foto: contenedor full-bleed en x, banda y=223..530; cover con foco 50% 23%
PHOTO_RECT = (0, 223, 850, 307)
PHOTO_FOCUS_Y = 0.23


class BoletinDataError(ValueError):
    """Falta un valor base → el boletín no se emite (no se admite parcial)."""


# ── Formato ─────────────────────────────────────────────────────────────────

def _fmt2(x: float) -> str:
    """10.7 → '10.70'. Punto decimal, 2 decimales (formato del card aprobado)."""
    return f"{x:.2f}"


def _fmt_delta(cur, ref) -> str:
    """Delta en BOB absoluto vs un cierre de referencia.
      - sin cur o sin ref            → '—'  (hueco visible, no se rellena)
      - |Δ| < DELTA_EPS              → '=0.00 BOB'
      - Δ > 0                        → '+X.XX BOB'
      - Δ < 0                        → '-X.XX BOB'
    Mismo criterio de signo/umbral que `deltaLine` de la tab Dólar."""
    if cur is None or ref is None:
        return "—"
    d = cur - ref
    if abs(d) < DELTA_EPS:
        return "=0.00 BOB"
    sign = "+" if d > 0 else "-"
    return f"{sign}{abs(d):.2f} BOB"


# ── Derivación de series (cierre por día calendario BOT) ─────────────────────

def _parse_bot_date(ts: str) -> date:
    """'2026-07-09T14:01:22.061157Z' (UTC) → fecha calendario en zona BOT."""
    dt = datetime.fromisoformat(ts.replace("Z", ""))   # naive, es UTC
    return (dt - timedelta(hours=4)).date()


def _daily_last(ts_list, vals) -> dict:
    """{fecha_BOT: último valor no-null de ese día}. `ts_list` viene cronológico,
    así que el último write por fecha gana → 'cierre' de cada día calendario."""
    out: dict[date, float] = {}
    for ts, v in zip(ts_list, vals):
        if v is None:
            continue
        out[_parse_bot_date(ts)] = v
    return out


def _last_nonnull(vals):
    """Último valor no-null de la serie (= valor actual). None si no hay."""
    for v in reversed(vals or []):
        if v is not None:
            return v
    return None


def _close_on_or_before(daily_map: dict, target: date):
    """Cierre del día `target`; si ese día no tiene dato (hueco), el cierre
    disponible más reciente ANTERIOR. None si no hay ninguno ≤ target."""
    cands = [dt for dt in daily_map if dt <= target]
    if not cands:
        return None
    return daily_map[max(cands)]


def _tco_history_map(meta: dict) -> dict:
    """{fecha: tco} desde meta.bcb_tco_history (una entrada por día, asc)."""
    out: dict[date, float] = {}
    for h in (meta.get("bcb_tco_history") or []):
        if not h or h.get("tco") is None or not h.get("fecha"):
            continue
        try:
            out[date.fromisoformat(h["fecha"])] = h["tco"]
        except ValueError:
            continue
    return out


def compute_values(data: dict, now_utc: datetime | None = None) -> dict:
    """Extrae los 2 valores + 4 deltas del card desde el dict de process_data.
    Lanza BoletinDataError si falta un valor base (TCO o USDT compra actuales)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    today = now_utc.astimezone(BOT_TZ).date()
    ayer = today - timedelta(days=1)
    hace7 = today - timedelta(days=7)

    meta = data.get("meta", {})
    tsm = data.get("ts_metrics", {})

    # OFICIAL = TCO vigente hoy (última fecha ≤ hoy); fallback al último conocido.
    tco_map = _tco_history_map(meta)
    tco_val = _close_on_or_before(tco_map, today)
    if tco_val is None:
        tco_val = meta.get("bcb_tco_last")

    # BINANCE = USDT compra (vb10) actual.
    vb_val = _last_nonnull(tsm.get("vb10"))

    faltantes = [n for n, v in (("oficial (TCO)", tco_val),
                                ("binance (USDT compra)", vb_val)) if v is None]
    if faltantes:
        raise BoletinDataError(
            "boletín no emitido: faltan valores base → " + ", ".join(faltantes))

    # Cierres de referencia (cierre de ayer / cierre de hace 7 días).
    tco_ayer = _close_on_or_before(tco_map, ayer)
    tco_sem = _close_on_or_before(tco_map, hace7)
    vb_map = _daily_last(tsm.get("ts") or [], tsm.get("vb10") or [])
    vb_ayer = _close_on_or_before(vb_map, ayer)
    vb_sem = _close_on_or_before(vb_map, hace7)

    return {
        "oficial": _fmt2(tco_val),
        "oficial_dia": _fmt_delta(tco_val, tco_ayer),
        "oficial_sem": _fmt_delta(tco_val, tco_sem),
        "binance": _fmt2(vb_val),
        "binance_dia": _fmt_delta(vb_val, vb_ayer),
        "binance_sem": _fmt_delta(vb_val, vb_sem),
    }


def _fecha_card(now_bot: datetime) -> str:
    """'17 DE JULIO DE 2026' (mayúsculas, para el card)."""
    return f"{now_bot.day} DE {MESES_MAY[now_bot.month - 1]} DE {now_bot.year}"


def _fecha_caption(now_bot: datetime) -> str:
    """'17/07/2026' (para los captions WhatsApp/Facebook)."""
    return f"{now_bot.day:02d}/{now_bot.month:02d}/{now_bot.year}"


# ── Captions copy-paste ──────────────────────────────────────────────────────

def render_captions(now_utc: datetime | None = None) -> dict:
    """Textos exactos para pegar junto a la imagen. WhatsApp en negrita (`*`),
    Facebook en plano. La fecha deriva de runtime (zona BOT)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    f = _fecha_caption(now_utc.astimezone(BOT_TZ))
    return {
        "whatsapp": f"*Cotización del dólar - {f}*\nwww.finanzasbo.com",
        "facebook": f"Cotización del dólar - {f}\nwww.finanzasbo.com",
    }


# ── Assets embebidos (foto + webfonts) ───────────────────────────────────────

def _data_uri(path: Path, mime: str) -> str:
    """base64 data-URI del archivo. '' si el asset no existe (el SVG degrada
    con gracia — foto ausente o fuente al fallback del stack — no aborta)."""
    try:
        b = path.read_bytes()
    except OSError:
        return ""
    return f"data:{mime};base64," + base64.b64encode(b).decode("ascii")


def _photo_data_uri() -> str:
    return _data_uri(PHOTO_PATH, "image/png")


def _font_style_block() -> str:
    """<style> con las @font-face embebidas (woff2 data:URI) DENTRO del SVG,
    para que el raster vía canvas (SVG→Image→canvas) las tenga disponibles.
    Solo las 2 caras que el render canónico usa (spec_fonts.json):
    Newsreader variable 400-700 (masthead, se usa a 600) e Inter 800 (fecha)."""
    faces = []
    nr = _data_uri(FONT_NEWSREADER_PATH, "font/woff2")
    if nr:
        faces.append(
            "@font-face{font-family:Newsreader;font-style:normal;"
            "font-weight:400 700;src:url(" + nr + ") format('woff2');}")
    inter = _data_uri(FONT_INTER800_PATH, "font/woff2")
    if inter:
        faces.append(
            "@font-face{font-family:Inter;font-style:normal;"
            "font-weight:800;src:url(" + inter + ") format('woff2');}")
    if not faces:
        return ""
    return "<style>" + "".join(faces) + "</style>"


# ── Render del SVG (tarjeta 850×850) ─────────────────────────────────────────
# Geometría y tipografía calcadas del render canónico (spec_geometry.json /
# spec_fonts.json): cada <text> usa la BASELINE medida como y y el centro
# medido como x (text-anchor=middle); reglas/divisor son los rects medidos.

def _stat_block(cx: float, val_delta: str, label: str) -> str:
    """Sub-stat (delta baseline 690, 'vs. …' baseline 709), centrado en cx.
    Delta: 16px Times New Roman 700 ls2 tan. Label: 14.5px 'aptos' (que en el
    render canónico cae a Times New Roman regular) ls2 tinta."""
    return (
        f'<text x="{cx}" y="690" text-anchor="middle" font-family="{FONT_SERIF}" '
        f'font-size="16" font-weight="700" letter-spacing="2" fill="{C_TAN}">'
        f'{_html.escape(val_delta)}</text>'
        f'<text x="{cx}" y="709" text-anchor="middle" font-family="{FONT_VS}" '
        f'font-size="14.5" font-weight="400" letter-spacing="2" fill="{C_INK}">{label}</text>'
    )


def render_svg(vals: dict, fecha_card: str) -> str:
    """SVG 850×850 self-contained (foto y webfonts embebidas base64).
    Orden de pintado = DOM order del original: marco < header < FOTO < stats <
    footer → la foto full-bleed TAPA los bordes laterales del marco en su banda."""
    photo = _photo_data_uri()
    fonts_css = _font_style_block()

    # Foto "cover": contenedor (0,223)-(850,530); nativa 612×408 escalada al
    # ancho 850 → 850×566.67 dibujada en y = 223 − (566.67−307)·0.23 = 163.28
    # (background-position 50% 23% medido), recortada al contenedor.
    px, py, pw, ph = PHOTO_RECT
    img_h = _PHOTO_H * (pw / _PHOTO_W)
    img_y = py - (img_h - ph) * PHOTO_FOCUS_Y
    photo_defs = (
        f'<clipPath id="phclip"><rect x="{px}" y="{py}" width="{pw}" height="{ph}"/></clipPath>'
        if photo else ""
    )
    photo_img = (
        f'<image href="{photo}" xlink:href="{photo}" x="{px}" y="{img_y:.2f}" '
        f'width="{pw}" height="{img_h:.2f}" preserveAspectRatio="none" '
        f'clip-path="url(#phclip)"/>'
        if photo else ""
    )

    return f'''<svg id="dolarCard" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 850 850" width="850" height="850">
{fonts_css}<defs>{photo_defs}</defs>
<rect x="0" y="0" width="850" height="850" fill="{C_BG}"/>
<!-- marco: border-box (22,22,806,802) con borde 1px ADENTRO → path en +0.5 -->
<rect x="22.5" y="22.5" width="805" height="801" fill="none" stroke="{C_BORDER}" stroke-width="1"/>
<!-- masthead -->
<text x="{CX}" y="107" text-anchor="middle" font-family="{FONT_BRAND}" font-size="65" font-weight="600" letter-spacing="0.2" fill="{C_INK}">FinanzasBo</text>
<text x="{CX}" y="135" text-anchor="middle" font-family="{FONT_TAGLINE}" font-style="italic" font-size="27" font-weight="500" fill="{C_MUTED}">Informaci&#243;n econ&#243;mica y financiera de Bolivia</text>
<rect x="104.22" y="166.75" width="105" height="2.5" fill="{C_BORDER}"/>
<rect x="640.77" y="166.75" width="105" height="2.5" fill="{C_BORDER}"/>
<text x="{CX}" y="176" text-anchor="middle" font-family="{FONT_SANS}" font-size="24" font-weight="700" letter-spacing="5" fill="{C_TAN}">COTIZACI&#211;N DEL D&#211;LAR</text>
<text x="{CX}" y="204" text-anchor="middle" font-family="{FONT_DATE}" font-size="21" font-weight="800" letter-spacing="4.8" fill="{C_INK}">{_html.escape(fecha_card)}</text>
<!-- foto (pintada DESPUÉS del marco y el header, como en el original) -->
{photo_img}
<!-- stats -->
<rect x="425" y="558" width="2.5" height="112" fill="{C_BORDER}"/>
<text x="{CX_OF}" y="570" text-anchor="middle" font-family="{FONT_SANS}" font-size="24" font-weight="700" letter-spacing="5" fill="{C_TAN}">OFICIAL</text>
<text x="{CX_BI}" y="570" text-anchor="middle" font-family="{FONT_SANS}" font-size="24" font-weight="700" letter-spacing="5" fill="{C_TAN}">BINANCE</text>
<text x="{CX_OF}" y="659" text-anchor="middle" font-family="{FONT_SERIF}" font-size="100" font-weight="700" fill="{C_INK}">{vals["oficial"]}</text>
<text x="{CX_BI}" y="659" text-anchor="middle" font-family="{FONT_SERIF}" font-size="100" font-weight="700" fill="{C_INK}">{vals["binance"]}</text>
{_stat_block(CX_OF_DIA, vals["oficial_dia"], "vs. d&#237;a anterior")}
{_stat_block(CX_OF_SEM, vals["oficial_sem"], "vs. semana anterior")}
{_stat_block(CX_BI_DIA, vals["binance_dia"], "vs. d&#237;a anterior")}
{_stat_block(CX_BI_SEM, vals["binance_sem"], "vs. semana anterior")}
<!-- footer -->
<text x="{CX}" y="756" text-anchor="middle" font-family="{FONT_SANS}" font-size="17" font-weight="700" letter-spacing="1.5" fill="{C_TAN}">FUENTE: BANCO CENTRAL DE BOLIVIA | BINANCE</text>
<text x="{CX}" y="784" text-anchor="middle" font-family="{FONT_SANS}" font-size="16" font-weight="500" letter-spacing="2" fill="{C_INK}">M&#193;S INFORMACI&#211;N EN:</text>
<text x="{CX}" y="811" text-anchor="middle" font-family="{FONT_SANS}" font-size="20" font-weight="700" letter-spacing="1.5" fill="{C_INK}">finanzasbo.com</text>
</svg>'''


# ── Render de la página HTML ─────────────────────────────────────────────────

_PAGE_TMPL = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Cotización del dólar — FinanzasBo</title>
<!-- boletin generated_at (UTC): {generated_at} -->
<style>
:root{{--bg:#F5EADF;--card:#FFF7F0;--ink:#211E1B;--muted:#6B6256;--border:rgba(33,30,27,.14);--accent:#2c4a6b;--ok:#2C6E49}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);font-family:'Helvetica Neue',Arial,-apple-system,BlinkMacSystemFont,sans-serif;display:flex;flex-direction:column;align-items:center;padding:26px 16px 40px}}
.wrap{{width:100%;max-width:480px}}
.cardbox{{width:100%;border:1px solid var(--border);border-radius:14px;overflow:hidden;box-shadow:0 6px 22px rgba(33,30,27,.10);background:var(--bg)}}
.cardbox svg{{display:block;width:100%;height:auto}}
.imgactions{{display:flex;gap:10px;margin:14px 0 22px}}
.imgactions button{{flex:1;font-family:inherit;font-size:15px;font-weight:600;padding:12px 10px;border-radius:10px;cursor:pointer;border:1px solid var(--accent);transition:background .15s,color .15s}}
button.primary{{color:#fff;background:var(--accent)}}
button.primary:hover{{background:#22405f}}
button.primary.ok{{background:var(--ok);border-color:var(--ok)}}
button.ghost{{color:var(--accent);background:transparent}}
button.ghost:hover{{background:rgba(44,74,107,.08)}}
button.ghost.ok{{color:var(--ok);border-color:var(--ok)}}
.cap{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px 16px 12px;margin-bottom:14px}}
.cap-head{{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}}
.cap-title{{font-size:13px;font-weight:700;letter-spacing:.4px;color:var(--muted);text-transform:uppercase}}
.cap-copy{{font-family:inherit;font-size:13px;font-weight:600;color:#fff;background:var(--accent);border:none;border-radius:8px;padding:7px 15px;cursor:pointer;transition:background .15s}}
.cap-copy:hover{{background:#22405f}}
.cap-copy.ok{{background:var(--ok)}}
pre.cap-text{{margin:0;font-family:'Helvetica Neue',Arial,sans-serif;font-size:14px;line-height:1.5;white-space:pre-wrap;word-break:break-word;color:var(--ink)}}
.foot{{margin-top:8px;font-size:12px;color:var(--muted);text-align:center;line-height:1.5}}
</style>
</head>
<body>
<div class="wrap">
<div class="cardbox">{svg}</div>
<div class="imgactions">
<button type="button" id="copyImg" class="primary">Copiar imagen</button>
<button type="button" id="dlImg" class="ghost">Descargar PNG</button>
</div>
<div class="cap">
<div class="cap-head"><span class="cap-title">WhatsApp</span><button type="button" class="cap-copy" data-copy="wa">Copiar</button></div>
<pre class="cap-text" id="capWa">{cap_wa}</pre>
</div>
<div class="cap">
<div class="cap-head"><span class="cap-title">Facebook</span><button type="button" class="cap-copy" data-copy="fb">Copiar</button></div>
<pre class="cap-text" id="capFb">{cap_fb}</pre>
</div>
<div class="foot">Uso interno &mdash; copi&aacute; la imagen y peg&aacute; el texto del canal que corresponda.</div>
</div>
<script>
(function(){{
  function flash(btn,txt){{var o=btn.textContent;btn.textContent=txt||'Copiado';btn.classList.add('ok');
    setTimeout(function(){{btn.textContent=o;btn.classList.remove('ok');}},1100);}}
  // ── captions ──
  document.querySelectorAll('.cap-copy').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      var pre=document.getElementById(btn.dataset.copy==='wa'?'capWa':'capFb');
      var t=pre.textContent;
      if(navigator.clipboard&&navigator.clipboard.writeText){{
        navigator.clipboard.writeText(t).then(function(){{flash(btn);}}).catch(function(){{fb(pre,btn);}});
      }}else{{fb(pre,btn);}}
    }});
  }});
  function fb(pre,btn){{var r=document.createRange();r.selectNode(pre);var s=getSelection();
    s.removeAllRanges();s.addRange(r);try{{document.execCommand('copy');}}catch(e){{}}s.removeAllRanges();flash(btn);}}
  // ── imagen: SVG → canvas PNG @2x ──
  function renderCanvas(cb){{
    var svg=document.getElementById('dolarCard');
    var xml=new XMLSerializer().serializeToString(svg);
    var url='data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(xml)));
    var img=new Image();
    img.onload=function(){{
      var s=2,c=document.createElement('canvas');c.width=850*s;c.height=850*s;
      var ctx=c.getContext('2d');ctx.drawImage(img,0,0,c.width,c.height);
      c.toBlob(function(b){{cb(b);}},'image/png');
    }};
    img.onerror=function(){{cb(null);}};
    img.src=url;
  }}
  var copyBtn=document.getElementById('copyImg');
  copyBtn.addEventListener('click',function(){{
    renderCanvas(function(blob){{
      if(!blob){{flash(copyBtn,'Error');return;}}
      if(window.ClipboardItem&&navigator.clipboard&&navigator.clipboard.write){{
        navigator.clipboard.write([new ClipboardItem({{'image/png':blob}})])
          .then(function(){{flash(copyBtn);}})
          .catch(function(){{download(blob);flash(copyBtn,'Descargada');}});
      }}else{{download(blob);flash(copyBtn,'Descargada');}}
    }});
  }});
  document.getElementById('dlImg').addEventListener('click',function(){{
    renderCanvas(function(blob){{if(blob)download(blob);}});
  }});
  function download(blob){{
    var a=document.createElement('a');a.href=URL.createObjectURL(blob);
    a.download='cotizacion-dolar.png';document.body.appendChild(a);a.click();
    setTimeout(function(){{URL.revokeObjectURL(a.href);a.remove();}},1000);
  }}
}})();
</script>
</body>
</html>
"""


def render_html(data: dict, now_utc: datetime | None = None) -> str:
    """Página HTML standalone (tarjeta SVG + captions + copiar/descargar imagen).
    Puede lanzar BoletinDataError ANTES de tocar el disco si falta un valor base."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_bot = now_utc.astimezone(BOT_TZ)
    vals = compute_values(data, now_utc)               # puede lanzar
    svg = render_svg(vals, _fecha_card(now_bot))
    caps = render_captions(now_utc)
    return _PAGE_TMPL.format(
        svg=svg,
        cap_wa=_html.escape(caps["whatsapp"]),
        cap_fb=_html.escape(caps["facebook"]),
        generated_at=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def write_boletin(data: dict, base_dir: Path,
                  now_utc: datetime | None = None) -> Path:
    """Genera la página y la escribe en `base_dir/boletin-4k9x/index.html`.
    Devuelve el path escrito. Propaga BoletinDataError si falta un valor base
    (el caller decide: NO sobrescribe el archivo anterior)."""
    html_out = render_html(data, now_utc)              # puede lanzar ANTES de escribir
    out_dir = Path(base_dir) / BOLETIN_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html_out, encoding="utf-8")
    return out_path


def build_from_db(db_path: Path, now_utc: datetime | None = None) -> str:
    """Camino standalone (test local / inspección): corre process_data y devuelve
    el HTML. Importa dashboard localmente para no cargar el módulo pesado salvo
    que se use este camino."""
    from dashboard import process_data
    return render_html(process_data(Path(db_path)), now_utc)


if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser(description="Genera la tarjeta diaria del dólar")
    p.add_argument("--db", type=Path, default=Path("p2p_normalized.db"))
    p.add_argument("--out", type=Path, default=None,
                   help="Directorio base (se crea <base>/boletin-4k9x/index.html). "
                        "Default: solo imprime valores + captions a stderr/stdout.")
    args = p.parse_args()

    from dashboard import process_data
    data = process_data(args.db)
    if args.out:
        path = write_boletin(data, args.out)
        print(f"Boletín: {path} ({path.stat().st_size / 1024:.1f} KB)", file=sys.stderr)
    vals = compute_values(data)
    caps = render_captions()
    print(f"OFICIAL {vals['oficial']}  (día {vals['oficial_dia']} · semana {vals['oficial_sem']})")
    print(f"BINANCE {vals['binance']}  (día {vals['binance_dia']} · semana {vals['binance_sem']})")
    print("---\n" + caps["whatsapp"] + "\n---\n" + caps["facebook"])
