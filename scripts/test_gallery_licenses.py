#!/usr/bin/env python3
"""Sync de licencias de galería — GALLERY-CREDITS.md ↔ dashboard.GALLERY_LICENSES.

Reproducible y sin deps: `python scripts/test_gallery_licenses.py` (exit 0 = OK, 1 = falla).
Parsea la tabla de GALLERY-CREDITS.md (única fuente narrativa) y assertea igualdad EXACTA
con GALLERY_LICENSES (la vista machine-readable): una sola verdad efectiva, dos vistas
sincronizadas. Si alguien edita una y olvida la otra, esto rompe. Además chequea el
contrato del brief (46 assets, 41 con atrib / 5 clean) y el helper de %.
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")  # consola Windows cp1252 → no crashear por glifos no-ASCII
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard import (  # noqa: E402
    GALLERY_LICENSES, GALLERY_ATTRIB_REQUIRED, gallery_attrib_stats,
)

PASS, FAIL = 0, 0


def check(desc, got, expected):
    global PASS, FAIL
    ok = got == expected
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  [{'OK ' if ok else 'FALLA'}] {desc}\n          got={got!r} exp={expected!r}" if not ok
          else f"  [OK ] {desc}")


def parse_credits():
    """{‘slug-k’: (licencia, atrib_bool)} desde la tabla markdown de GALLERY-CREDITS.md.
    Filas de datos: empiezan con '| `' (slug entre backticks). Columnas:
    slug | k | archivo | tema | autor | licencia | atrib. | origen."""
    path = os.path.join(ROOT, 'GALLERY-CREDITS.md')
    with open(path, encoding='utf-8') as fh:
        lines = fh.read().splitlines()
    out = {}
    for ln in lines:
        if not ln.lstrip().startswith('| `'):
            continue
        cols = [c.strip() for c in ln.split('|')]
        # cols[0]='' (antes del primer '|'); datos en cols[1..]
        slug = cols[1].strip('` ')
        k = cols[2].strip()
        licencia = cols[6].strip()
        atrib_raw = cols[7].strip().lower()
        assert atrib_raw in ('sí', 'si', 'no'), f"atrib. inesperada: {atrib_raw!r} en fila {slug}-{k}"
        out[f'{slug}-{k}'] = (licencia, atrib_raw != 'no')
    return out


print("== SYNC: GALLERY-CREDITS.md ↔ GALLERY_LICENSES ==")
credits = parse_credits()
check("credits parseados == GALLERY_LICENSES (igualdad exacta)", credits, GALLERY_LICENSES)
check("keys de credits == keys de GALLERY_LICENSES", set(credits), set(GALLERY_LICENSES))

print("== CONTRATO del brief (46 assets, 41 atrib / 5 clean) ==")
check("46 assets en total", len(GALLERY_LICENSES), 46)
check("41 requieren atribución", len(GALLERY_ATTRIB_REQUIRED), 41)
clean = sorted(k for k, (lic, req) in GALLERY_LICENSES.items() if not req)
check("5 clean = agro-2, agro-3, banco-central-3, combustibles-3, fmi-1",
      clean, ['agro-2', 'agro-3', 'banco-central-3', 'combustibles-3', 'fmi-1'])

print("== HELPER de % (len-based) ==")
pct_global, por_slug = gallery_attrib_stats()
check("pct_global = 41/46*100", round(pct_global, 4), round(100.0 * 41 / 46, 4))
check("agro = 1/3 con atrib (2 PD clean)", round(por_slug['agro'], 4), round(100.0 / 3, 4))
check("litio = 100% (4/4 con atrib)", por_slug['litio'], 100.0)
check("por_slug cubre todos los slugs de GALLERY_SETS", set(por_slug),
      {k.rsplit('-', 1)[0] for k in GALLERY_LICENSES})

print(f"\nRESULTADO: {PASS} OK, {FAIL} FALLA   (atrib global: {pct_global:.1f}%)")
sys.exit(1 if FAIL else 0)
