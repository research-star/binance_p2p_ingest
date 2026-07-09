#!/usr/bin/env python3
"""
boletin.py — Boletín diario en texto plano para copy-paste (canal de WhatsApp).

Genera una página standalone, pública y NO linkeada (`/boletin-4k9x/index.html`),
con el resumen del día y un botón "Copiar". El contenido son datos ya públicos en
finanzasbo.com (oficial BCB + P2P USDT + riesgo país EMBI); NO se gatea, NO hay
token, NO se toca Access ni el Worker.

Fuente de datos: el dict que devuelve `dashboard.process_data(db_path)` (símbolo,
no línea). De ahí salen:
  - oficial (BCB): `meta.bcb_tco_last` = TCO = pata COMPRA del oficial (RD 88/2026;
    template.html "compra (= TCO)"). La pata VENTA se deriva TCO + 0,10 Bs
    (`VENTA_REF_SPREAD_BS`, regla RD 88/2026: venta referencial = TCO + 0,10).
  - USDT compra/venta: último `vb10`/`vs10` de `ts_metrics` (VWAP 10% de
    profundidad, el mismo número que las KPIs "USDT Compra/Venta" del dashboard).
    `vb10` (lado BUY = donde el taker COMPRA USDT) = lo que pagás; `vs10`
    (lado SELL) = lo que recibís. Verificado contra normalize.py (side=tradeType)
    y el orden de process_data (buy asc, sell desc).
  - EMBI Bolivia: última observación no-null de `embi_data.series['bolivia']`
    (en bps) + delta vs la observación previa.

Reglas de emisión (adenda del brief, no negociables):
  - Delta = variación contra el ÚLTIMO valor del día calendario anterior (zona
    BOT, UTC-4), determinista respecto de la hora del bake — no "hace 24h".
  - Sin dato de ayer → se omite el paréntesis entero (nunca "0,0%" ni "n/d").
    Un delta que redondea a cero también se omite (no informa, y evita el
    placeholder-looking "0,0%").
  - Si falta un VALOR BASE (oficial, USDT compra/venta, EMBI) el boletín NO se
    emite a medias: `build_boletin` lanza `BoletinDataError`. El caller (bake)
    loguea ruidoso y NO sobrescribe el archivo anterior. Un boletín con hueco es
    peor que uno viejo.
  - Timestamp SIEMPRE derivado de runtime, zona BOT.
  - Copy exacto aprobado por Diego: asteriscos literales (negrita WhatsApp), signo
    menos ASCII, coma decimal + punto de miles, cero emojis/flechas/color/tabla/
    monoespaciado.

NO llama a la API de Anthropic. NO escribe al VPS. Repo-only.
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Constantes ──────────────────────────────────────────────────────────────

BOLETIN_DIRNAME = "boletin-4k9x"  # ruta standalone, fuera del SPA, no enumerable
BOT_TZ = timezone(timedelta(hours=-4))  # hora de Bolivia (UTC-4, sin DST)
VENTA_REF_SPREAD_BS = 0.10  # RD 88/2026: venta referencial = TCO + 0,10 Bs

MESES_ABREV = ["ene", "feb", "mar", "abr", "may", "jun", "jul",
               "ago", "sep", "oct", "nov", "dic"]


class BoletinDataError(ValueError):
    """Falta un valor base → el boletín no se emite (no se admite parcial)."""


# ── Formato de números (locale es: coma decimal, punto de miles, menos ASCII) ─

def _fmt_num(x: float, decimals: int) -> str:
    """12345.6 → '12.345,6'. Signo menos ASCII '-' (nunca U+2212)."""
    neg = x < 0
    s = f"{abs(x):,.{decimals}f}"           # formato US: '12,345.60'
    s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")  # swap , <-> .
    return ("-" + s) if neg else s


def _fmt_pct(delta: float) -> str:
    """Delta % con signo explícito y 1 decimal: 0.85 → '+0,8'; -0.52 → '-0,8'."""
    r = round(delta, 1)
    sign = "-" if r < 0 else "+"
    return f"{sign}{_fmt_num(abs(r), 1)}"


def _fmt_pbs(delta: float) -> str:
    """Delta EMBI en puntos básicos, entero con signo: -4 → '-4 pbs'."""
    r = round(delta)
    sign = "-" if r < 0 else "+"
    return f"{sign}{_fmt_num(abs(r), 0)} pbs"


# ── Derivación de series ─────────────────────────────────────────────────────

def _parse_bot_date(ts: str):
    """'2026-07-09T14:01:22.061157Z' (UTC) → fecha calendario en zona BOT."""
    dt = datetime.fromisoformat(ts.replace("Z", ""))  # naive, es UTC
    return (dt - timedelta(hours=4)).date()


def _daily_last(ts_list, vals) -> dict:
    """{fecha_BOT: último valor no-null de ese día}. ts_list viene cronológico,
    así que el último write por fecha gana."""
    out = {}
    for ts, v in zip(ts_list, vals):
        if v is None:
            continue
        out[_parse_bot_date(ts)] = v
    return out


def _usdt_side(ts_metrics: dict, key: str):
    """Devuelve (valor_latest, delta_pct_vs_ayer). El delta es None si no hay al
    menos dos días calendario con dato. `key` ∈ {'vb10','vs10'}."""
    ts_list = ts_metrics.get("ts") or []
    vals = ts_metrics.get(key) or []
    dl = _daily_last(ts_list, vals)
    if not dl:
        return None, None
    dias = sorted(dl)
    latest = dl[dias[-1]]
    if len(dias) < 2:
        return latest, None
    prev = dl[dias[-2]]
    if not prev:  # None o 0 → sin base para el %
        return latest, None
    return latest, (latest / prev - 1) * 100.0


def _embi_bolivia(embi_data: dict):
    """(valor_latest_bps, delta_bps_vs_obs_previa). delta None si no hay previa."""
    series = (embi_data or {}).get("series", {}).get("bolivia")
    if not series:
        return None, None
    idxs = [i for i, v in enumerate(series) if v is not None]
    if not idxs:
        return None, None
    last_v = series[idxs[-1]]
    if len(idxs) < 2:
        return last_v, None
    prev_v = series[idxs[-2]]
    return last_v, (last_v - prev_v)


# ── Render de texto plano ────────────────────────────────────────────────────

def render_texto(data: dict, now_utc: datetime | None = None) -> str:
    """Arma el texto plano exacto del boletín. Lanza BoletinDataError si falta un
    valor base. El texto es EXACTAMENTE lo que se copia al portapapeles."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    now_bot = now_utc.astimezone(BOT_TZ)

    meta = data.get("meta", {})
    ts_metrics = data.get("ts_metrics", {})

    tco = meta.get("bcb_tco_last")          # pata COMPRA del oficial
    usdt_compra, d_compra = _usdt_side(ts_metrics, "vb10")
    usdt_venta, d_venta = _usdt_side(ts_metrics, "vs10")
    embi, d_embi = _embi_bolivia(data.get("embi_data", {}))

    faltantes = [n for n, v in (("oficial (TCO)", tco),
                                ("USDT compra", usdt_compra),
                                ("USDT venta", usdt_venta),
                                ("EMBI Bolivia", embi)) if v is None]
    if faltantes:
        raise BoletinDataError(
            "boletín no emitido: faltan valores base → " + ", ".join(faltantes))

    oficial_compra = tco                       # lo que recibís vendiendo USD
    oficial_venta = tco + VENTA_REF_SPREAD_BS  # lo que pagás comprando USD

    fecha = f"{now_bot.day} {MESES_ABREV[now_bot.month - 1]} {now_bot.year}"
    hhmm = now_bot.strftime("%H:%M")

    def _paren_pct(d):
        # Se omite si no hay dato de ayer o si redondea a cero (evita "0,0%").
        if d is None or round(d, 1) == 0.0:
            return ""
        return f"  ({_fmt_pct(d)}% vs ayer)"

    def _paren_pbs(d):
        if d is None or round(d) == 0:
            return ""
        return f"  ({_fmt_pbs(d)})"

    lineas = [
        f"*FinanzasBo* — {fecha}, {hhmm}",
        "",
        "*Si compras dólares* (lo que pagas)",
        f"Oficial: Bs {_fmt_num(oficial_venta, 2)}",
        f"USDT: Bs {_fmt_num(usdt_compra, 2)}{_paren_pct(d_compra)}",
        "",
        "*Si vendes dólares* (lo que recibes)",
        f"Oficial: Bs {_fmt_num(oficial_compra, 2)}",
        f"USDT: Bs {_fmt_num(usdt_venta, 2)}{_paren_pct(d_venta)}",
        "",
        f"*Riesgo país*: {_fmt_num(embi, 0)} puntos{_paren_pbs(d_embi)}",
        "",
        "Oficial: BCB. USDT: mediana P2P.",
        "finanzasbo.com",
    ]
    return "\n".join(lineas)


# ── Render de la página HTML ─────────────────────────────────────────────────

_PAGE_TMPL = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Boletín FinanzasBo</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<!-- boletin generated_at (UTC): {generated_at} -->
<style>
:root{{--bg-primary:#FBEDE3;--card:#FFF7F0;--text:#211E1B;--muted:#6B6256;--border:rgba(33,30,27,0.14);--accent:#2c4a6b;--ok:#2C6E49}}
*{{box-sizing:border-box}}
body{{margin:0;min-height:100vh;background:var(--bg-primary);color:var(--text);font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;display:flex;align-items:flex-start;justify-content:center;padding:32px 16px}}
.wrap{{width:100%;max-width:440px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:22px 22px 18px;box-shadow:0 6px 22px rgba(33,30,27,.07)}}
pre#boletin{{margin:0;font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;font-size:15px;line-height:1.55;white-space:pre-wrap;word-break:break-word}}
.actions{{display:flex;justify-content:flex-end;margin-top:16px}}
button#copy{{font-family:inherit;font-size:14px;font-weight:600;color:#fff;background:var(--accent);border:none;border-radius:9px;padding:10px 20px;cursor:pointer;transition:background .15s}}
button#copy:hover{{background:#22405f}}
button#copy.ok{{background:var(--ok)}}
.foot{{margin-top:14px;font-size:12px;color:var(--muted);text-align:center}}
</style>
</head>
<body>
<div class="wrap">
<div class="card">
<pre id="boletin">{texto}</pre>
<div class="actions"><button id="copy" type="button">Copiar</button></div>
</div>
<div class="foot">Uso interno — pegar en el canal.</div>
</div>
<script>
(function(){{
  var pre=document.getElementById('boletin'),btn=document.getElementById('copy');
  function flash(){{var o=btn.textContent;btn.textContent='Copiado';btn.classList.add('ok');
    setTimeout(function(){{btn.textContent=o;btn.classList.remove('ok');}},1000);}}
  btn.addEventListener('click',function(){{
    var txt=pre.textContent;
    if(navigator.clipboard&&navigator.clipboard.writeText){{
      navigator.clipboard.writeText(txt).then(flash).catch(fallback);
    }}else{{fallback();}}
    function fallback(){{
      var r=document.createRange();r.selectNode(pre);
      var s=window.getSelection();s.removeAllRanges();s.addRange(r);
      try{{document.execCommand('copy');}}catch(e){{}}
      s.removeAllRanges();flash();
    }}
  }});
}})();
</script>
</body>
</html>
"""


def render_html(data: dict, now_utc: datetime | None = None) -> str:
    """Página HTML standalone. El <pre> contiene el texto exacto (HTML-escapado);
    `pre.textContent` en el navegador reconstruye byte-idéntico el texto plano que
    devuelve `render_texto` (lo que se copia al portapapeles)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    texto = render_texto(data, now_utc)
    return _PAGE_TMPL.format(
        texto=_html.escape(texto),
        generated_at=now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def write_boletin(data: dict, base_dir: Path,
                  now_utc: datetime | None = None) -> Path:
    """Genera la página y la escribe en `base_dir/boletin-4k9x/index.html`.
    Devuelve el path escrito. Propaga BoletinDataError si falta un valor base
    (el caller decide: NO sobrescribe el archivo anterior)."""
    html_out = render_html(data, now_utc)  # puede lanzar ANTES de tocar el disco
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

    p = argparse.ArgumentParser(description="Genera el boletín diario standalone")
    p.add_argument("--db", type=Path, default=Path("p2p_normalized.db"))
    p.add_argument("--out", type=Path, default=None,
                   help="Directorio base (se crea <base>/boletin-4k9x/index.html). "
                        "Default: solo imprime el texto a stdout.")
    args = p.parse_args()

    from dashboard import process_data
    data = process_data(args.db)
    if args.out:
        path = write_boletin(data, args.out)
        print(f"Boletín: {path} ({path.stat().st_size} bytes)", file=sys.stderr)
    print(render_texto(data))
