#!/usr/bin/env python3
"""
test_noticias_relevancia.py — Tests de las compuertas de relevancia de evaluar()
(FASE: clasificación de noticias, incremento 1).

Verifica:
  - Geo-gate UNIVERSAL: toda nota debe anclar en Bolivia (término geográfico/adjetivo
    o entidad boliviana). El ruido extranjero se descarta en TODOS los portales,
    no solo en PORTALES_EXIGEN_BOLIVIA.
  - "General" NO se descarta: una nota boliviana relevante sin tema de negocios entra
    como categoría 'otros' (relleno), no se disfraza de ECONOMÍA ni se tira. La crisis
    política (estado de excepción, etc.) cae en el tema político, no en General.

El modelo TF-IDF se stubea (prob alta) para ejercitar la rama del modelo sin el
.pkl. Uso: python scripts/test_noticias_relevancia.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import scraper


class _ModeloStub:
    """Simula modelo disponible con prob alta para forzar la rama del modelo."""
    disponible = True

    def puntaje(self, titulo: str, descripcion: str) -> float:
        return 0.9


def run() -> int:
    scraper.get_modelo = lambda: _ModeloStub()
    errores = []

    def ev(titulo, descripcion="", portal="El Deber"):
        r = scraper.evaluar(titulo, descripcion, portal)
        return {"puntaje": r[0], "tema": r[1], "entidades": r[3], "descartado_por": r[7]}

    def check(desc, got, exp):
        if got["descartado_por"] != exp:
            errores.append(f"{desc}: descartado_por={got['descartado_por']!r} "
                           f"(esperado {exp!r}) | {got}")

    # 1. Extranjero sin Bolivia: geo-gate universal lo corta (El Deber NO estaba en
    #    PORTALES_EXIGEN_BOLIVIA, así que antes pasaba).
    check("extranjero sin Bolivia",
          ev("Hombre arrojó a un niño al foso de los cocodrilos en un zoológico de Reino Unido"),
          "falta_bolivia")

    # 2. Bolivia + General + sin tema de negocios (diplomacia): YA NO se descarta —
    #    entra como 'otros' (relleno por relevancia). Calibración 2026-06-21: matar
    #    General tiraba ~60-70% de noticia relevante mal rotulada.
    g2 = ev("Canciller boliviano se reúne con su par de Brasil en La Paz")
    check("General sin negocios → se conserva (otros)", g2, "")
    if g2["tema"] != "General":
        errores.append(f"esperaba tema General (se conserva como otros) | {g2}")

    # 3. Bolivia + General + entidad económica (BCB): se conserva.
    g = ev("El BCB participó de un acto protocolar en La Paz")
    check("General con entidad económica", g, "")
    if "BCB" not in g["entidades"]:
        errores.append(f"esperaba entidad BCB detectada | {g}")

    # 4. Nota económica clara con Bolivia: pasa.
    check("económica con Bolivia",
          ev("El dólar paralelo sube en Bolivia y preocupa a importadores"),
          "")

    # 5. Ancla por entidad boliviana (YPFB) sin término geográfico literal: pasa geo-gate.
    y = ev("YPFB anuncia millonaria inversión en nuevos pozos de gas")
    if y["descartado_por"] == "falta_bolivia":
        errores.append(f"YPFB debería anclar Bolivia por entidad | {y}")

    # 6. Crisis política (estado de excepción): cae en tema político (Bloqueos /
    #    Conflictos), no en General → category 'politica'. Calibración 2026-06-21.
    c = ev("Gobierno promulga el estado de excepción para liberar las carreteras del país")
    check("crisis política se conserva", c, "")
    if c["tema"] != "Bloqueos / Conflictos":
        errores.append(f"estado de excepción debería ser 'Bloqueos / Conflictos' | {c}")

    if errores:
        print("FAIL test_noticias_relevancia:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_relevancia: geo-gate universal (extranjero descartado) + "
          "General se conserva como 'otros' (no se descarta) + crisis política cae en "
          "tema político + ancla por entidad.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
