#!/usr/bin/env python3
"""test_resumen_ia.py — Degradación elegante del resumen IA.

Sin ANTHROPIC_API_KEY (o con NOTICIAS_RESUMEN=0): habilitado()=False, resumir()
devuelve None y aplicar() es no-op (conserva el extracto). NUNCA hace red en este
test. Uso: python scripts/test_resumen_ia.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import resumen_ia


def run() -> int:
    errores = []

    # Sin key → deshabilitado; resumir None; aplicar no-op (conserva summary).
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("NOTICIAS_RESUMEN", None)
    if resumen_ia.habilitado():
        errores.append("habilitado() debería ser False sin ANTHROPIC_API_KEY")
    if resumen_ia.resumir("Titular de prueba", "cuerpo de prueba") is not None:
        errores.append("resumir() debería devolver None sin key")
    notas = [{"title": "T", "detail": "D", "summary": "extracto original"}]
    n = resumen_ia.aplicar(notas)
    if n != 0 or notas[0]["summary"] != "extracto original":
        errores.append(f"aplicar() debería ser no-op sin key (n={n}, summary={notas[0]['summary']!r})")

    # Con key pero flag apagado → deshabilitado (no llama a la API).
    os.environ["ANTHROPIC_API_KEY"] = "sk-test-no-se-usa"
    os.environ["NOTICIAS_RESUMEN"] = "0"
    if resumen_ia.habilitado():
        errores.append("habilitado() debería ser False con NOTICIAS_RESUMEN=0")
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("NOTICIAS_RESUMEN", None)

    # _es_fallo: centinela / rechazo / vacío → True (degrada a extractivo);
    # un resumen real → False (se persiste como 'ia').
    fallo_si = ["INSUFICIENTE", "Insuficiente.", "No puedo resumir esta noticia porque…",
                "La noticia trata sobre Colombia, no Bolivia.", "Lo siento, no me es posible.", "", "   ",
                # V2.1: INSUFICIENTE + explicación pegada (prefijo anclado) → fallo
                "INSUFICIENTE\n\n(El texto solo contiene el titular.)",
                "INSUFICIENTE: el texto no aporta datos verificables.",
                "INSUFICIENTE — sin contenido más allá del título.",
                "INSUFICIENTE (no hay cuerpo)."]
    for t in fallo_si:
        if not resumen_ia._es_fallo(t):
            errores.append(f"_es_fallo({t!r}) debería ser True")
    fallo_no = ["El BCB anunció nuevas medidas para el tipo de cambio.",
                "De la Espriella conformará su gabinete con foco en seguridad y empleo.",
                # La palabra "insuficiente" en el cuerpo (no al inicio) NO es fallo
                "La cosecha fue insuficiente este año, según el informe del INE.",
                "Producción insuficiente para la demanda interna, advierte la CNI."]
    for t in fallo_no:
        if resumen_ia._es_fallo(t):
            errores.append(f"_es_fallo({t!r}) debería ser False")

    if errores:
        print("FAIL test_resumen_ia:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_resumen_ia: sin key → resumir None + aplicar no-op; flag off respetado; "
          "_es_fallo distingue centinela/rechazo/vacío de resumen real.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
