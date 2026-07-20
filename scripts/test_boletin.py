#!/usr/bin/env python3
"""
test_boletin.py — Tests de la tarjeta diaria del dólar (boletin.py), sin DB ni red.

Cubre el contrato de la tarjeta imagen (reemplazo del boletín de texto):
  - valores        — OFICIAL = TCO vigente hoy ; BINANCE = USDT compra (vb10)
                     actual, ambos a 2 decimales con punto.
  - cierre_ayer    — el delta día usa el CIERRE (último valor) del día calendario
                     anterior (BOT), no una ventana móvil de 24h ni el penúltimo
                     snapshot global.
  - cierre_7d      — el delta semana usa el cierre del día calendario de hace 7d.
  - delta_cero     — |Δ| < eps → "=0.00 BOB" (no signo).
  - delta_hueco    — sin cierre de referencia (serie corta) → "—" (hueco visible).
  - falta_base     — sin TCO o sin USDT compra → BoletinDataError (no parcial).
  - captions       — WhatsApp con negrita (`*`), Facebook plano, fecha DD/MM/YYYY.
  - runtime_ts     — fecha del card y del caption derivan de runtime; el HTML
                     cambia bake-a-bake por generated_at.
  - html           — noindex, trae el SVG (#dolarCard) y ambos captions.

Uso:  python scripts/test_boletin.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # salida utf-8 aun en consolas cp1252 (Windows) — el reporte lleva '—', 'é', 'Δ'
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

import boletin as m  # noqa: E402

# ── Fixtures ─────────────────────────────────────────────────────────────────
# now = 09-jul 14:35 BOT. today=09, ayer=08, hace7=02.
NOW = datetime(2026, 7, 9, 18, 35, 0, tzinfo=timezone.utc)

# vb10: 02 (cierre semana) 10.50 ; 08 tiene DOS snapshots (10.60 temprano y 10.74
# tarde = cierre de ayer) ; 09 (hoy, actual) 10.73. El delta día debe usar 10.74
# (cierre de 08), no 10.60 (penúltimo) ni un snapshot "~24h atrás".
TS = ["2026-07-02T12:00:00Z", "2026-07-08T10:00:00Z",
      "2026-07-08T23:00:00Z", "2026-07-09T14:00:00Z"]
VB = [10.50, 10.60, 10.74, 10.73]
TCO_HIST = [{"fecha": "2026-07-02", "tco": 10.24},
            {"fecha": "2026-07-08", "tco": 10.75},
            {"fecha": "2026-07-09", "tco": 10.75}]


def _data(vb=VB, ts=TS, tco_last=10.75, tco_hist=None):
    return {
        "meta": {"bcb_tco_last": tco_last,
                 "bcb_tco_history": TCO_HIST if tco_hist is None else tco_hist},
        "ts_metrics": {"ts": ts, "vb10": vb},
    }


def run() -> int:
    err: list[str] = []

    def eq(label, got, exp):
        if got != exp:
            err.append(f"{label}: got {got!r}, esperaba {exp!r}")

    # ── valores + cierre_ayer + cierre_7d ────────────────────────────────────
    v = m.compute_values(_data(), NOW)
    eq("oficial", v["oficial"], "10.75")
    eq("binance", v["binance"], "10.73")
    # oficial: 10.75 vs cierre 08 (10.75) → =0.00 ; vs cierre 02 (10.24) → +0.51
    eq("oficial_dia", v["oficial_dia"], "=0.00 BOB")
    eq("oficial_sem", v["oficial_sem"], "+0.51 BOB")
    # binance: 10.73 vs cierre 08 (10.74) → -0.01 ; vs cierre 02 (10.50) → +0.23
    eq("binance_dia", v["binance_dia"], "-0.01 BOB")
    eq("binance_sem", v["binance_sem"], "+0.23 BOB")

    # cierre_ayer determinista: si el delta usara el PENÚLTIMO global (10.60) daría
    # +0.13; si usara una ventana rolling-24h (snapshot 08 10:00Z=10.60) también.
    # Que dé -0.01 confirma que usa el CIERRE de ayer (10.74).
    if v["binance_dia"] != "-0.01 BOB":
        err.append("cierre_ayer: el delta día NO usó el cierre de ayer (10.74)")

    # ── delta_cero: |Δ|<eps → '=0.00 BOB' ────────────────────────────────────
    if "=0.00 BOB" != v["oficial_dia"]:
        err.append("delta_cero: TCO sin cambio debería ser '=0.00 BOB'")

    # ── delta_hueco: un solo día → sin cierre de referencia → '—' ─────────────
    solo_hoy = _data(vb=[10.73], ts=["2026-07-09T14:00:00Z"],
                     tco_hist=[{"fecha": "2026-07-09", "tco": 10.75}])
    vh = m.compute_values(solo_hoy, NOW)
    eq("hueco_oficial_dia", vh["oficial_dia"], "—")
    eq("hueco_oficial_sem", vh["oficial_sem"], "—")
    eq("hueco_binance_dia", vh["binance_dia"], "—")
    eq("hueco_binance_sem", vh["binance_sem"], "—")
    # pero los VALORES sí salen
    eq("hueco_binance_val", vh["binance"], "10.73")

    # ── falta_base: sin TCO o sin vb10 → BoletinDataError ─────────────────────
    for nombre, df in (
        ("tco", _data(tco_last=None, tco_hist=[])),
        ("vb10", _data(vb=[None, None, None, None])),
    ):
        try:
            m.compute_values(df, NOW)
            err.append(f"falta_base[{nombre}]: NO lanzó BoletinDataError")
        except m.BoletinDataError:
            pass
        except Exception as e:  # noqa: BLE001
            err.append(f"falta_base[{nombre}]: lanzó {type(e).__name__}, "
                       "esperaba BoletinDataError")

    # write_boletin NO escribe si falta base (no parcial)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        try:
            m.write_boletin(_data(vb=[None]), Path(td), NOW)
            err.append("falta_base: write_boletin escribió pese a faltar base")
        except m.BoletinDataError:
            if (Path(td) / m.BOLETIN_DIRNAME / "index.html").exists():
                err.append("falta_base: quedó un index.html parcial en disco")

    # ── captions: WhatsApp negrita (*), Facebook plano, fecha DD/MM/YYYY ──────
    caps = m.render_captions(NOW)
    eq("cap_wa", caps["whatsapp"],
       "*Cotización del dólar - 09/07/2026*\nwww.finanzasbo.com")
    eq("cap_fb", caps["facebook"],
       "Cotización del dólar - 09/07/2026\nwww.finanzasbo.com")
    if caps["facebook"].startswith("*") or "*" in caps["facebook"]:
        err.append("captions: Facebook no debería llevar asteriscos (negrita)")

    # ── fecha del card en mayúsculas ─────────────────────────────────────────
    eq("fecha_card", m._fecha_card(NOW.astimezone(m.BOT_TZ)), "9 DE JULIO DE 2026")

    # ── runtime_ts + html ────────────────────────────────────────────────────
    h1 = m.render_html(_data(), NOW)
    NOW2 = datetime(2026, 7, 9, 18, 42, 0, tzinfo=timezone.utc)  # +7 min
    h2 = m.render_html(_data(), NOW2)
    if h1 == h2:
        err.append("runtime_ts: el HTML no cambió con distinto now_utc (generated_at fijo)")
    if 'content="noindex,nofollow"' not in h1:
        err.append("html: falta el <meta robots noindex,nofollow>")
    if 'id="dolarCard"' not in h1:
        err.append("html: falta el SVG de la tarjeta (#dolarCard)")
    if "10.75" not in h1 or "10.73" not in h1:
        err.append("html: faltan los valores en el SVG")
    # ambos captions embebidos (é escapada en el <pre>)
    if "09/07/2026" not in h1:
        err.append("html: falta la fecha del caption")

    # el día del card cambia día a día (runtime)
    NOW_MANANA = datetime(2026, 7, 10, 18, 35, 0, tzinfo=timezone.utc)
    if m._fecha_card(NOW.astimezone(m.BOT_TZ)) == m._fecha_card(NOW_MANANA.astimezone(m.BOT_TZ)):
        err.append("runtime_ts: la fecha del card no cambió de día a día")

    # ── finde: la BCB timbra la publicación del viernes en SÁBADO → se re-fecha al
    #    lunes; el finde arrastra el valor del viernes; salto el LUNES (Diego 2026-07-20:
    #    lo del jueves vale hasta el domingo, lo del viernes entra en validez el lunes) ─
    from dashboard import (_redate_weekend_publications,  # deferido: dashboard no toca DB al importar
                           _fill_weekends_tco)
    # Data CRUDA como la timbra la BCB. 2026-07-20 = lunes → 24 vie, 25 sáb, 26 dom, 27 lun.
    raw = [{"fecha": "2026-07-23", "tco": 6.95},                              # jue (vig jue)
           {"fecha": "2026-07-24", "tco": 6.96, "source": "bcb_tco_portada"},  # vie = A (valor del finde)
           {"fecha": "2026-07-25", "tco": 6.98, "source": "bcb_tco_portada"}]  # SÁB timbrado = pub. del viernes → rige lunes (B)
    redated = _redate_weekend_publications(raw)
    rf = {h["fecha"]: h for h in redated}
    # el sábado timbrado se movió al lunes (27); no queda entrada PUBLICADA de finde
    eq("redate_sin_sabado", "2026-07-25" in rf, False)
    eq("redate_lunes_val", rf.get("2026-07-27", {}).get("tco"), 6.98)
    filled = _fill_weekends_tco(redated)
    byf = {h["fecha"]: h for h in filled}
    # sáb/dom sintéticos = valor del VIERNES (A=6.96), NO del lunes (B=6.98)
    eq("finde_sab_tco", byf.get("2026-07-25", {}).get("tco"), 6.96)
    eq("finde_dom_tco", byf.get("2026-07-26", {}).get("tco"), 6.96)
    eq("finde_sab_src", byf.get("2026-07-25", {}).get("source"), "bcb_tco_fin_semana")
    if byf.get("2026-07-27", {}).get("source") == "bcb_tco_fin_semana":
        err.append("finde: el lunes (ya re-fechado) no debería quedar como sintético")

    def _wk(nowdt):
        d = {"meta": {"bcb_tco_last": 6.98, "bcb_tco_history": filled},
             "ts_metrics": {"ts": ["2026-07-24T14:00:00Z"], "vb10": [10.0]}}
        return m.compute_values(d, nowdt)

    vs = _wk(datetime(2026, 7, 25, 18, 35, 0, tzinfo=timezone.utc))  # sáb 14:35 BOT
    vd = _wk(datetime(2026, 7, 26, 18, 35, 0, tzinfo=timezone.utc))  # dom
    vl = _wk(datetime(2026, 7, 27, 18, 35, 0, tzinfo=timezone.utc))  # lun
    # sábado y domingo: valor del viernes (6.96) y delta día PLANO
    eq("finde_sab_val", vs["oficial"], "6.96")
    eq("finde_sab_dia", vs["oficial_dia"], "=0.00 BOB")
    eq("finde_dom_val", vd["oficial"], "6.96")
    eq("finde_dom_dia", vd["oficial_dia"], "=0.00 BOB")
    # lunes: recién ahí salta al valor nuevo (6.98), delta +0.02
    eq("finde_lun_val", vl["oficial"], "6.98")
    eq("finde_lun_dia", vl["oficial_dia"], "+0.02 BOB")

    if err:
        print("FAIL test_boletin:")
        for e in err:
            print("  -", e)
        return 1
    print("OK test_boletin: OFICIAL=TCO y BINANCE=USDT compra a 2 decimales; los "
          "deltas día/semana usan el CIERRE del día calendario anterior / de hace "
          "7 días (BOT), no ventana móvil; |Δ|<eps → '=0.00 BOB'; sin cierre de "
          "referencia → '—'; falta de valor base aborta sin escribir parcial; "
          "captions WhatsApp(negrita)/Facebook(plano) con fecha DD/MM/YYYY; el "
          "HTML lleva noindex + el SVG del card + ambos captions.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
