#!/usr/bin/env python3
"""
test_bcb_tco_portada.py — Tests de parse_homepage_tco (scraper del TCO, vía portada).

Blinda la regresión del 2026-07-01: el BCB rediseñó el card 'Tipo de cambio oficial'
de la portada (https://www.bcb.gob.bo/) y pasó del dúo HOY/MAÑANA
(`bcb-tco-duo-num`) a un ÚNICO valor vigente (`bcb-tco-num`) fechado por
`<time datetime>`. El parser viejo devolvía 0 entradas → bcb_tco.json congelado.

Sub-tests:
  actual     — fixture REAL de la portada (2026-07-01): 1 entrada, TCO 9.76 vig. 01-jul.
  viejo      — snippet del formato dúo previo: 2 entradas (HOY + MAÑANA), fallback vivo.
  vacio      — HTML sin el card is-tc-oficial → [] (sin crash, sin falsos positivos).
  css_only   — la clase solo en el <style> (sin markup) → [] (no captura el CSS).

Uso:  python scripts/test_bcb_tco_portada.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest_bcb_tco as m  # noqa: E402

FIXTURE = ROOT / "scripts" / "fixtures" / "bcb_tco_portada_2026-07-01.html"

# Formato VIEJO (dúo HOY/MAÑANA), reducido a lo que el parser necesita.
VIEJO = (
    '<article class="bcb-kpi2-card is-tc-oficial">'
    '  <time datetime="2026-06-29">LUNES 29 DE JUNIO, 2026</time>'
    '  <div class="bcb-tco-duo-label">Hoy <span>Hasta 00:00</span></div>'
    '  <div class="bcb-tco-duo-num">9,73</div>'
    '  <div class="bcb-tco-duo-label">Mañana <span>MARTES 30 DE JUNIO, 2026</span></div>'
    '  <div class="bcb-tco-duo-num">9,76</div>'
    "</article>"
)

# Solo el CSS de la clase, sin markup del card (no debe capturar nada).
CSS_ONLY = (
    "<style>.bcb-kpi2-card.is-tc-oficial{color:#fff}"
    ".bcb-tco-num{font-size:34px}.bcb-tco-duo-num{font-weight:950}</style>"
    "<body><p>sin card</p></body>"
)


def run() -> int:
    errores: list[str] = []

    # actual — fixture real
    if not FIXTURE.exists():
        errores.append(f"falta el fixture {FIXTURE}")
    else:
        html = m._decode(FIXTURE.read_bytes())
        got = m.parse_homepage_tco(html)
        if got != [{"fecha": "2026-07-01", "tco": 9.76}]:
            errores.append(f"actual: esperaba [01-jul 9.76], got {got!r}")

    # viejo — dúo HOY/MAÑANA (fallback)
    got = m.parse_homepage_tco(VIEJO)
    if got != [{"fecha": "2026-06-29", "tco": 9.73},
               {"fecha": "2026-06-30", "tco": 9.76}]:
        errores.append(f"viejo: esperaba [29-jun 9.73, 30-jun 9.76], got {got!r}")

    # vacio — sin card
    if m.parse_homepage_tco("<html><body>nada</body></html>") != []:
        errores.append("vacio: esperaba [] sin card is-tc-oficial")

    # css_only — clase solo en <style>
    if m.parse_homepage_tco(CSS_ONLY) != []:
        errores.append("css_only: el CSS de la clase NO debe producir entradas")

    if errores:
        print("FAIL test_bcb_tco_portada:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_bcb_tco_portada: portada actual (bcb-tco-num, 1 valor + <time>) "
          "parsea 01-jul 9.76; fallback dúo viejo (bcb-tco-duo-num HOY/MAÑANA) intacto; "
          "sin card o clase-solo-CSS devuelven [] (sin falsos positivos).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
