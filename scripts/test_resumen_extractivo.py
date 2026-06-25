#!/usr/bin/env python3
"""test_resumen_extractivo.py — Resumen extractivo sin IA (calibración 2026-06-21).

Verifica:
  - Texto ya corto (≤200) se devuelve tal cual.
  - 1-2 oraciones completas que entran en 200 → ambas, terminando en signo, SIN elipsis.
  - Corte por oración: si la 2ª no entra, queda solo la 1ª (sin elipsis).
  - Abreviaturas (EE.UU.) no parten la oración a la mitad.
  - 1ª oración > 200 → fallback a corte por palabra LIMPIO, sin elipsis.

Uso: python scripts/test_resumen_extractivo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest.transform import _resumen_extractivo


def run() -> int:
    errores = []

    def chk(cond, msg):
        if not cond:
            errores.append(msg)

    # 1. Texto corto → tal cual.
    t1 = "El dólar paralelo bajó a Bs 9,92 este viernes."
    chk(_resumen_extractivo(t1) == t1, f"texto corto debería volver igual | {t1!r}")

    # 2. Dos oraciones que entran → ambas, sin elipsis, terminando en punto.
    s1 = "El dólar paralelo subió hoy en Bolivia."
    s2 = "Importadores y comerciantes expresan preocupación por la brecha cambiaria."
    r2 = _resumen_extractivo(s1 + " " + s2)
    chk(r2 == s1 + " " + s2, f"dos oraciones cortas → ambas | got={r2!r}")
    chk("…" not in r2, "no debería tener elipsis cuando corta por oración")

    # 3. Abreviatura EE.UU. no parte la oración.
    ab = ("Bolivia accede a ayuda de EE.UU. para enfrentar a los carteles de narcos. "
          "El Gobierno confirmó el acuerdo.")
    r3 = _resumen_extractivo(ab)
    chk("EE.UU. para enfrentar" in r3, f"EE.UU. no debería partirse | got={r3!r}")
    chk(r3.endswith("."), f"debería terminar en oración completa | got={r3!r}")
    chk("…" not in r3, "abreviatura: no elipsis")

    # 4. Solo la 1ª oración entra (la 2ª excede los 200).
    larga2 = ("El dólar subió.", )  # placeholder no usado
    primera = "El Banco Central reportó un movimiento moderado en las reservas internacionales del país."
    segunda = ("Analistas del sector financiero advirtieron que la tendencia podría sostenerse durante "
               "varias semanas si no se aplican medidas correctivas inmediatas y sostenidas en el tiempo.")
    r4 = _resumen_extractivo(primera + " " + segunda)
    chk(r4 == primera, f"si la 2ª no entra, solo la 1ª | got={r4!r}")

    # 5. Primera oración > 200 → fallback a corte LIMPIO por palabra, SIN elipsis
    #    (el slot del card no debe terminar en '…', calibración 2026-06-25).
    muy_larga = ("El Banco Central informó que las reservas internacionales registraron una variación "
                 "significativa durante el último trimestre del año debido a múltiples factores económicos "
                 "y financieros que afectaron al mercado cambiario nacional de manera sostenida")
    r5 = _resumen_extractivo(muy_larga)
    chk(not r5.endswith("…"), f"1ª oración larga → corte limpio SIN elipsis | got={r5!r}")
    chk(len(r5) <= 200, f"fallback no debería exceder 200 | len={len(r5)}")
    chk(muy_larga.startswith(r5), f"corte debería ser prefijo limpio | got={r5!r}")

    if errores:
        print("FAIL test_resumen_extractivo:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_resumen_extractivo: oraciones completas + abreviaturas + corte por "
          "oración + fallback corte limpio (sin elipsis).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
