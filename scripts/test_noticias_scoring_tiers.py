#!/usr/bin/env python3
"""
test_noticias_scoring_tiers.py — Tests de M1 (piso Bloomberg) + M2 (tier institucional).

M1: Bloomberg Línea en carril Bolivia que sobrevive los gates duros (exclusión +
    geo-gate) queda con puntaje >= 9, dominando ajustes y el umbral del modelo. Los
    gates duros SÍ lo frenan (no rescata una nota sin ancla ni tema).
M2: existe clasificación tipo-de-fuente (noticiero/institucion) sobre FUENTES; el
    boost +1 se aplica DESPUÉS del corte 6.7 (solo-reordena, no rescata sub-umbral),
    cap a 10; noticieros sin cambio.

Uso:  python scripts/test_noticias_scoring_tiers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import noticias_ingest.scraper as scraper  # noqa: E402
import ingest_noticias as ing  # noqa: E402
from noticias_ingest.transform import build_nota  # noqa: E402

UMBRAL = 6.7  # corte editorial carril Bolivia (ingest_noticias.UMBRAL_PUNTAJE)


def _mk(portal: str, puntaje: float) -> dict:
    """Nota REAL vía build_nota (así el test ve el campo `impact`, que M2 debe recomputar)."""
    return build_nota({"portal": portal, "link": f"http://x/{portal}/{puntaje}",
                       "titulo": f"nota {portal}", "descripcion": "cuerpo", "puntaje": puntaje})


def _lane_filter_and_boost(cands: list[tuple]) -> list[dict]:
    """Tramo REAL de lane_bolivia relevante a M2: filtra por umbral y LUEGO aplica el
    helper real `_boost_institucional` (mismo orden que ingest_noticias.py:356-358)."""
    notas = [_mk(p, s) for p, s in cands]
    seleccion = [n for n in notas if n["puntaje"] >= UMBRAL]
    ing._boost_institucional(seleccion)     # código de producción, no réplica
    seleccion.sort(key=lambda n: -n["puntaje"])
    return seleccion


def run() -> int:
    err: list[str] = []

    # ── M2 metadata: split completo, toda fuente clasificada ──────────────────
    sin_tipo = [f["portal"] for f in scraper.FUENTES if "tipo" not in f]
    if sin_tipo:
        err.append(f"M2: fuentes sin 'tipo': {sin_tipo}")
    inst = {f["portal"] for f in scraper.FUENTES if f["tipo"] == "institucion"}
    esperado_inst = {"BCB", "INE", "MEFP", "ASFI", "Aduana", "CAINCO", "IBCE", "CEPB", "CNI"}
    if inst != esperado_inst:
        err.append(f"M2: split institucion inesperado: {inst} != {esperado_inst}")
    if scraper.es_fuente_institucional("Bloomberg Línea"):
        err.append("M2: Bloomberg Línea es noticiero (prensa), NO institución")
    if not scraper.es_fuente_institucional("INE"):
        err.append("M2: INE debe ser institución")
    if scraper.es_fuente_institucional("El Deber"):
        err.append("M2: El Deber es noticiero, no institución")

    # ── M2 boost: reordena (puntaje E impact), NO rescata sub-umbral, cap a 10 ─
    out = _lane_filter_and_boost([
        ("INE", 7.5),       # institución sobre umbral → +1 = 8.5, cruza banda medio→alto
        ("El Deber", 7.5),  # noticiero → sin cambio (puntaje e impact)
        ("IBCE", 5.8),      # institución SUB-umbral → NO rescatada
        ("BCB", 9.6),       # institución → +1 con cap 10.0
    ])
    by = {n["portal"]: n for n in out}
    if by.get("INE", {}).get("puntaje") != 8.5:
        err.append(f"M2: INE 7.5 debía subir a 8.5, got {by.get('INE', {}).get('puntaje')}")
    # F1 (review): el impact DEBE seguir al puntaje boosteado (7.5 'medio' → 8.5 'alto'),
    # si no, el frontend —que rankea por impact, no por puntaje— no refleja el reordenamiento.
    if by.get("INE", {}).get("impact") != "alto":
        err.append(f"M2/F1: INE boosteada a 8.5 debía tener impact='alto', got {by.get('INE', {}).get('impact')!r}")
    if by.get("El Deber", {}).get("puntaje") != 7.5:
        err.append(f"M2: El Deber (noticiero) no debe cambiar, got {by.get('El Deber', {}).get('puntaje')}")
    if by.get("El Deber", {}).get("impact") != "medio":
        err.append(f"M2: El Deber (7.5) impact debe seguir 'medio', got {by.get('El Deber', {}).get('impact')!r}")
    if "IBCE" in by:
        err.append("M2: IBCE 5.8 (sub-umbral) NO debe entrar por el +1 (rescate prohibido)")
    if by.get("BCB", {}).get("puntaje") != 10.0:
        err.append(f"M2: BCB 9.6 debía capear a 10.0, got {by.get('BCB', {}).get('puntaje')}")
    # reorden: BCB (10.0) primero, luego INE (8.5), luego El Deber (7.5)
    if [n["portal"] for n in out] != ["BCB", "INE", "El Deber"]:
        err.append(f"M2: orden tras boost inesperado: {[n['portal'] for n in out]}")

    # ── M1 piso Bloomberg-Bolivia ─────────────────────────────────────────────
    # pasa gates (ancla Bolivia) → >= 9 aunque el modelo lo puntúe bajo
    p, *_rest, desc = scraper.evaluar(
        "Bolivia y Brasil firman acuerdo de integración gasífera",
        "nota", "Bloomberg Línea")
    if not (p >= 9.0 and desc == ""):
        err.append(f"M1: Bloomberg+Bolivia debía quedar >=9 (got {p}, descartado={desc!r})")
    # gate DURO lo frena igual (sin ancla ni tema económico → geo-gate)
    p2, *_r2, desc2 = scraper.evaluar(
        "Champions League: definición del título", "deportes", "Bloomberg Línea")
    if not (p2 == 0 and desc2 == "falta_bolivia"):
        err.append(f"M1: Bloomberg sin ancla debe caer por geo-gate (got {p2}, {desc2!r})")
    # un noticiero NO-Bloomberg no recibe piso
    p3, *_r3 = scraper.evaluar(
        "Bolivia y Brasil firman acuerdo de integración gasífera", "nota", "El Deber")
    if p3 >= 9.0:
        err.append(f"M1: El Deber NO debe recibir piso Bloomberg (got {p3})")

    if err:
        print("FAIL test_noticias_scoring_tiers:")
        for e in err:
            print("  -", e)
        return 1
    print("OK test_noticias_scoring_tiers: M2 split 9 instituciones/15 noticieros con "
          "'tipo' en toda FUENTES; +1 institucional reordena post-6.7, no rescata sub-umbral, "
          "cap 10; M1 Bloomberg-Bolivia >=9 tras gates duros y frenado por geo-gate; "
          "noticieros no-Bloomberg sin piso.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
