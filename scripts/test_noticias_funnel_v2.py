#!/usr/bin/env python3
"""
test_noticias_funnel_v2.py — Arnés de regresión del funnel BO v2 (ticket
noticias-funnel-v2, WS7). Cubre los rediseños de WS1 (geo-gate ancla|tema),
WS2 (léxico de ancla), WS3 (tema post-conflicto), WS4 (opinión) y WS5 (cultural).

Asserts mínimos (brief):
  - RESCATE: notas económicas SIN nombre-país (ej. "el dólar referencial baja a
    Bs 9,92") SOBREVIVEN el geo-gate (no mueren 'falta_bolivia').
  - LEGIT: el set legítimo previamente publicado (titulares reales del carril BO)
    sigue pasando — cero pérdida de recall vs el gate viejo.
  - OPINIÓN: piezas de opinión/columna quedan con score < 6.7 (penalización ×0.7).
  - CULTURAL: color folklórico/ceremonial muere ('keyword_excluida').
  - INTERNACIONAL: ningún título claramente internacional SIN tema ni ancla (CR7,
    Mbappé, Lula, Greenspan, OEA/Venezuela) entra al set final.

El modelo TF-IDF se stubea (prob=0.9) para ejercitar la rama del modelo sin el
.pkl: con stub 0.9, una nota dura puntúa 9.0 y una opinión 0.9×0.7 → 6.3 (<6.7).
Determinista. Uso: python scripts/test_noticias_funnel_v2.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Salida UTF-8: los titulares reales traen ñ/ó/í y la consola Windows (cp1252)
# crashea al imprimir el reporte de fallos. No afecta la lógica del test.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import scraper
from noticias_ingest.transform import build_nota


class _ModeloStub:
    """Modelo disponible con prob alta para forzar la rama del modelo (no el fallback)."""
    disponible = True

    def puntaje(self, titulo: str, descripcion: str) -> float:
        return 0.9


# ── Fixture representativo del carril BO ──────────────────────────────────────
# Derivado de titulares reales (noticias_ingest/data/candidatos_2026-06-11.csv) +
# los casos-objetivo del brief. No hay snapshot real con kill-reason en repo (data/
# es gitignored y solo persiste sobrevivientes), así que el fixture es sintético-
# representativo, no un dump live — pero los LEGIT son títulos reales publicados.

# A. RESCATES — economía BO que NO nombra el país; antes morían 'falta_bolivia'.
RESCATES = [
    "El dólar referencial baja a 9,92 tras la última jornada cambiaria",
    "La inflación mensual se acelera y encarece la canasta básica",
    "Tras el desbloqueo, mejora la transitabilidad en el eje troncal",
    "Empresarios cruceños piden reactivar las exportaciones de soya",
    "El Servicio de Impuestos Nacionales amplía el plazo de declaraciones",
    "El BCB anuncia nuevas medidas sobre las reservas internacionales",
]

# B. LEGIT — titulares reales ya publicados (CSV 2026-06-11). Deben pasar limpio.
LEGIT = [
    "Diputado Rolando Pacheco advierte riesgos por acuerdos del litio",
    "Productores de quinua denuncian caída de precios y freno de exportaciones por conflictos",
    "Gobierno nuevamente descarta Estado de excepción y apuesta por el diálogo frente a bloqueos",
    "94 bloqueos afectan Bolivia; Cochabamba sigue siendo el epicentro del cierre de rutas",
    "Avícolas, lecheros, bananeros, agropecuarios e industriales, golpeados por los bloqueos",
]

# C. OPINIÓN — anclada (pasa el geo-gate) pero penalizada ×0.7 → score < 6.7.
#    (titulo, url). Detección por marcador de título o por sección de URL.
OPINION = [
    ("OPINIÓN: el costo económico de los bloqueos en Bolivia", ""),
    ("El rumbo del dólar paralelo en Bolivia", "https://eldeber.com.bo/opinion/columna-economica_1"),
    ("La economía boliviana y el litio | OPINIÓN |", ""),
    ("Reflexiones sobre las reservas del BCB", "https://lostiempos.com/columna/analisis_2"),
]

# D. CULTURAL — color folklórico/ceremonial sin ángulo económico → muere.
CULTURAL = [
    "Miles celebran el año nuevo aymara en Tiwanaku",
    "La entrada folklórica de Urkupiña convoca a miles de danzarines",
    "Ceremonia ancestral marca el solsticio de invierno en el altiplano",
]

# E. INTERNACIONAL — sin tema económico NI ancla BO → muere en el geo-gate, NO entra
#    al set final. (El intl CON tema sin ancla es el riesgo v1 diferido: lo contiene
#    el umbral 6.7 + el modelo, no este gate — fuera del assert por decisión cerrada.)
INTERNACIONAL = [
    "Cristiano Ronaldo renueva su contrato con un club de Arabia Saudita",
    "Mbappé marca un gol decisivo en la Champions League",
    "Lula se reúne con Trump en Washington para hablar de aranceles",
    "Greenspan opina sobre la última decisión de la Reserva Federal",
    "La OEA debate una resolución sobre la crisis de Venezuela",
]


def run() -> int:
    scraper.get_modelo = lambda: _ModeloStub()
    err: list[str] = []

    def ev(titulo, descripcion="", portal="El Deber", url=""):
        es_op = scraper.es_opinion(titulo, url)
        r = scraper.evaluar(titulo, descripcion, portal, es_opinion=es_op)
        return {"puntaje": r[0], "tema": r[1], "descartado_por": r[7], "es_opinion": es_op}

    # A. RESCATES: deben sobrevivir el geo-gate (no 'falta_bolivia', puntaje > 0).
    for t in RESCATES:
        g = ev(t)
        if g["descartado_por"] == "falta_bolivia" or g["puntaje"] == 0:
            err.append(f"RESCATE debería sobrevivir el geo-gate: {t!r} -> {g}")

    # B. LEGIT: el set publicado sigue pasando limpio (descartado_por == "").
    for t in LEGIT:
        g = ev(t)
        if g["descartado_por"] != "":
            err.append(f"LEGIT (recall previo) debería pasar: {t!r} -> {g}")

    # C. OPINIÓN: detectada y con score < 6.7 (penalización ×0.7).
    for titulo, url in OPINION:
        g = ev(titulo, url=url)
        if not g["es_opinion"]:
            err.append(f"OPINIÓN no detectada: {titulo!r} url={url!r}")
        elif g["puntaje"] >= 6.7:
            err.append(f"OPINIÓN debería quedar < 6.7 (×0.7): {titulo!r} -> puntaje={g['puntaje']}")

    # D. CULTURAL: muere por exclusión ('keyword_excluida').
    for t in CULTURAL:
        g = ev(t)
        if g["descartado_por"] != "keyword_excluida":
            err.append(f"CULTURAL debería morir 'keyword_excluida': {t!r} -> {g}")

    # E. INTERNACIONAL (sin tema ni ancla): NO entra al set final (puntaje 0).
    for t in INTERNACIONAL:
        g = ev(t)
        if g["puntaje"] != 0:
            err.append(f"INTERNACIONAL no debería entrar al set final: {t!r} -> {g}")

    # F. Data layer: una pieza de opinión lleva category='opinion'.
    cand_op = {
        "portal": "El Deber", "tema": "Tipo de cambio / Dólar", "descripcion": "x", "cuerpo": "",
        "link": "https://eldeber.com.bo/opinion/columna_1", "titulo": "OPINIÓN: el dólar",
        "puntaje": 6.3, "tema_hits": 10, "entidades": [], "es_opinion": True,
    }
    nota = build_nota(cand_op, datetime.now(timezone.utc))
    if nota["category"] != "opinion":
        err.append(f"build_nota: opinión debería llevar category='opinion', dio {nota['category']!r}")
    # ...y una nota dura mantiene su category derivada del tema (no 'opinion').
    cand_hard = dict(cand_op, es_opinion=False, link="https://eldeber.com.bo/economia/x")
    nota_h = build_nota(cand_hard, datetime.now(timezone.utc))
    if nota_h["category"] != "finanzas":
        err.append(f"build_nota: nota dura Dólar debería ser 'finanzas', dio {nota_h['category']!r}")

    if err:
        print("FAIL test_noticias_funnel_v2:")
        for e in err:
            print("  -", e)
        return 1
    print(f"OK test_noticias_funnel_v2: {len(RESCATES)} rescates sobreviven + "
          f"{len(LEGIT)} legit pasan + {len(OPINION)} opinión < 6.7 + "
          f"{len(CULTURAL)} cultural muere + {len(INTERNACIONAL)} intl fuera del set + "
          f"category='opinion' en data.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
