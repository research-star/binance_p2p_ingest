#!/usr/bin/env python3
"""
test_boletin.py — Tests del boletín diario (boletin.py), sin DB ni red.

Cubre la aceptación de la adenda del brief:
  - copy/formato   — texto exacto aprobado por Diego (asteriscos literales, coma
                     decimal + punto de miles, menos ASCII, sin emojis/flechas).
  - sin_ayer       — sin dato del día calendario anterior → SIN paréntesis (nunca
                     "0,0%" ni placeholder).
  - delta_cero     — un delta que redondea a cero también se omite (no "0,0%").
  - falta_base     — falta un valor base → build lanza BoletinDataError (no parcial).
  - runtime_ts     — el timestamp deriva de runtime (dos now_utc distintos → dos
                     encabezados distintos; NO está fijo).
  - copy_identico  — el texto del <pre> (textContent, HTML-unescaped) es
                     byte-idéntico al que devuelve render_texto.
  - delta_calendario — el delta usa el ÚLTIMO valor del día anterior (BOT), no
                     "hace 24h", determinista respecto de la hora del bake.

Uso:  python scripts/test_boletin.py
"""
from __future__ import annotations

import html as _html
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import boletin as m  # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────
# ts en UTC. En BOT (UTC-4): 08 12:00Z→08:00 08-jul; 09 12:00Z→08:00 09-jul.
# Dos días calendario BOT (08 y 09) con dos snapshots el 09 (gana el último).

def _data(vb_series, vs_series, ts_series, tco, embi_series,
          embi_fechas=None):
    return {
        "meta": {"bcb_tco_last": tco},
        "ts_metrics": {"ts": ts_series, "vb10": vb_series, "vs10": vs_series},
        "embi_data": {
            "fechas": embi_fechas or [],
            "series": {"bolivia": embi_series},
        },
    }


TS_2D = ["2026-07-08T12:00:00Z", "2026-07-09T12:00:00Z", "2026-07-09T14:30:00Z"]
NOW = datetime(2026, 7, 9, 18, 35, 0, tzinfo=timezone.utc)  # 14:35 BOT


def run() -> int:
    err: list[str] = []

    # ── copy/formato: caso completo con deltas ───────────────────────────────
    # vb10: ayer(08) 10.30 → hoy(09) último 10.40  → +0,97% → "+1,0"
    # vs10: ayer(08) 10.20 → hoy(09) último 10.10  → -0,98% → "-1,0"
    # tco 10.10 → oficial_venta 10.20 / oficial_compra 10.10
    # embi: ...423.7 → 428.9 (última) → delta +5 pbs
    d = _data([10.30, 10.35, 10.40], [10.20, 10.15, 10.10], TS_2D,
              10.10, [423.7, 428.9])
    txt = m.render_texto(d, NOW)
    esperado = (
        "*FinanzasBo* — 9 jul 2026, 14:35\n"
        "\n"
        "*Si compras dólares* (lo que pagas)\n"
        "Oficial: Bs 10,20\n"
        "USDT: Bs 10,40  (+1,0% vs ayer)\n"
        "\n"
        "*Si vendes dólares* (lo que recibes)\n"
        "Oficial: Bs 10,10\n"
        "USDT: Bs 10,10  (-1,0% vs ayer)\n"
        "\n"
        "*Riesgo país*: 429 puntos  (+5 pbs)\n"
        "\n"
        "Oficial: BCB. USDT: mediana P2P.\n"
        "finanzasbo.com"
    )
    if txt != esperado:
        err.append("copy/formato: texto no coincide.\n--- got ---\n"
                    + txt + "\n--- exp ---\n" + esperado)

    # menos ASCII, nunca U+2212
    if "−" in txt:
        err.append("copy/formato: apareció el menos tipográfico U+2212")
    # sin emojis/flechas comunes
    if any(c in txt for c in "▲▼→↑↓📊💵"):
        err.append("copy/formato: apareció un emoji/flecha prohibido")

    # ── punto de miles ───────────────────────────────────────────────────────
    if m._fmt_num(1842, 0) != "1.842":
        err.append(f"miles: 1842 → {m._fmt_num(1842, 0)!r}, esperaba '1.842'")
    if m._fmt_num(12.45, 2) != "12,45":
        err.append(f"decimal: 12.45 → {m._fmt_num(12.45, 2)!r}, esperaba '12,45'")

    # ── sin_ayer: un solo día calendario → sin paréntesis, sin "0,0%" ─────────
    d1 = _data([10.40], [10.10], ["2026-07-09T14:30:00Z"], 10.10, [428.9])
    txt1 = m.render_texto(d1, NOW)
    if "vs ayer" in txt1 or "%" in txt1:
        err.append("sin_ayer: no debería haber delta % (apareció paréntesis)")
    if "0,0" in txt1 or "n/d" in txt1.lower():
        err.append("sin_ayer: apareció '0,0' o 'n/d' (placeholder prohibido)")
    if "USDT: Bs 10,40\n" not in txt1 + "\n":
        err.append("sin_ayer: la línea USDT debería cerrar sin espacios colgando")

    # EMBI con una sola observación → sin paréntesis
    if "pbs" in txt1:
        err.append("sin_ayer: EMBI con una sola obs no debería mostrar delta pbs")

    # ── delta_cero: variación que redondea a 0 → se omite (no "0,0%") ─────────
    # vb10 ayer 10.40 → hoy 10.40 (delta 0%) ; vs10 ayer 100 → hoy 100.02 (~+0,02%→0,0)
    dz = _data([10.40, 10.40], [100.0, 100.02],
               ["2026-07-08T12:00:00Z", "2026-07-09T12:00:00Z"], 10.10, [428.9, 428.9])
    txtz = m.render_texto(dz, NOW)
    if "0,0%" in txtz:
        err.append("delta_cero: apareció '0,0%' (debe omitirse el paréntesis)")
    if "vs ayer" in txtz:
        err.append("delta_cero: no debería haber paréntesis con delta ~0")
    # EMBI sin cambio (428.9 → 428.9) → sin paréntesis pbs
    if "pbs" in txtz:
        err.append("delta_cero: EMBI sin cambio no debería mostrar '(... pbs)'")

    # ── falta_base: cada valor base ausente aborta (no parcial) ───────────────
    faltas = [
        ("tco", _data([10.4, 10.4], [10.1, 10.1], TS_2D[1:], None, [428.9])),
        ("vb10", _data([None, None], [10.1, 10.1], TS_2D[1:], 10.1, [428.9])),
        ("vs10", _data([10.4, 10.4], [None, None], TS_2D[1:], 10.1, [428.9])),
        ("embi", _data([10.4, 10.4], [10.1, 10.1], TS_2D[1:], 10.1, [])),
    ]
    for nombre, df in faltas:
        try:
            m.render_texto(df, NOW)
            err.append(f"falta_base[{nombre}]: NO lanzó BoletinDataError")
        except m.BoletinDataError:
            pass
        except Exception as e:  # noqa: BLE001
            err.append(f"falta_base[{nombre}]: lanzó {type(e).__name__}, "
                       f"esperaba BoletinDataError")

    # write_boletin NO debe escribir archivo si falta base (no parcial)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        try:
            m.write_boletin(faltas[0][1], Path(td), NOW)
            err.append("falta_base: write_boletin escribió pese a faltar base")
        except m.BoletinDataError:
            if (Path(td) / m.BOLETIN_DIRNAME / "index.html").exists():
                err.append("falta_base: quedó un index.html parcial en disco")

    # ── runtime_ts: dos now_utc → dos encabezados (NO fijo) ───────────────────
    NOW2 = datetime(2026, 7, 9, 18, 42, 0, tzinfo=timezone.utc)  # 14:42 BOT
    if m.render_texto(d, NOW).splitlines()[0] == m.render_texto(d, NOW2).splitlines()[0]:
        err.append("runtime_ts: el encabezado no cambió con distinto now_utc (fijo)")
    h1 = m.render_html(d, NOW)
    h2 = m.render_html(d, NOW2)
    if h1 == h2:
        err.append("runtime_ts: el HTML no cambió con distinto now_utc (fijo)")
    if 'name="robots" content="noindex,nofollow"' not in h1:
        err.append("html: falta el <meta robots noindex,nofollow>")

    # ── copy_identico: textContent del <pre> == render_texto (byte a byte) ─────
    # Extrae el contenido del <pre> del HTML y lo des-escapa (== textContent).
    marca_ini, marca_fin = '<pre id="boletin">', "</pre>"
    seg = h1[h1.index(marca_ini) + len(marca_ini):h1.index(marca_fin)]
    if _html.unescape(seg) != m.render_texto(d, NOW):
        err.append("copy_identico: el texto del <pre> no es byte-idéntico a render_texto")

    # ── delta_calendario: usa el ÚLTIMO valor de AYER, no el penúltimo global ──
    # Ayer (08) tiene 2 snapshots: 10.00 y 10.20 (último=10.20). Hoy (09)=10.40.
    # Delta correcto vs último de ayer (10.20): +1,96% → "+2,0", NO vs 10.00.
    dcal = _data(
        [10.00, 10.20, 10.40],
        [10.0, 10.0, 10.0],
        ["2026-07-08T10:00:00Z", "2026-07-08T14:00:00Z", "2026-07-09T14:00:00Z"],
        10.10, [428.9, 428.9])
    latest, delta = m._usdt_side(dcal["ts_metrics"], "vb10")
    if latest != 10.40:
        err.append(f"delta_calendario: latest {latest}, esperaba 10.40")
    if round(delta, 1) != 2.0:
        err.append(f"delta_calendario: delta {delta:.3f}%, esperaba ~+1,96 "
                   f"(vs último de ayer 10.20, no vs 10.00)")

    if err:
        print("FAIL test_boletin:")
        for e in err:
            print("  -", e)
        return 1
    print("OK test_boletin: copy exacto + formato es (coma decimal, miles, menos "
          "ASCII); sin-ayer y delta-cero omiten paréntesis (nunca '0,0%'); falta "
          "de valor base aborta sin escribir parcial; timestamp deriva de runtime; "
          "el <pre> es byte-idéntico al texto copiado; el delta usa el último "
          "valor del día calendario anterior (BOT).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
