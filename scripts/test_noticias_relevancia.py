#!/usr/bin/env python3
"""
test_noticias_relevancia.py — Tests de las compuertas de relevancia de evaluar()
(FASE: clasificación de noticias, incremento 1).

Verifica:
  - Geo-gate UNIVERSAL: toda nota debe anclar en Bolivia (término geográfico/adjetivo
    o entidad boliviana). El ruido extranjero se descarta en TODOS los portales,
    no solo en PORTALES_EXIGEN_BOLIVIA.
  - Matar el fallback "General→economía": una nota sin tema real solo entra si trae
    evidencia económica (entidad económica). Si no, se descarta — no se disfraza de
    ECONOMÍA.

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

    # 2. Bolivia + sin tema + sin entidad económica: se descarta (no finge ECONOMÍA).
    check("General sin evidencia económica",
          ev("Gran concierto reúne a miles de personas en Santa Cruz este fin de semana"),
          "general_sin_clasificar")

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

    if errores:
        print("FAIL test_noticias_relevancia:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_noticias_relevancia: geo-gate universal + General→economía eliminado "
          "(extranjero y General-sin-económica descartados; económicas y ancladas por "
          "entidad pasan).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
