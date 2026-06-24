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
    ("OPINIÓN — El dólar paralelo y la economía boliviana", ""),  # em-dash (U+2014), fix review
    ("El rumbo del dólar paralelo en Bolivia", "https://eldeber.com.bo/opinion/columna-economica_1"),
    ("La economía boliviana y el litio | OPINIÓN |", ""),
    ("Reflexiones sobre las reservas del BCB", "https://lostiempos.com/columna/analisis_2"),
]

# G. TEMA-CORRECTNESS (fix review WS3): el vocabulario de recuperación económica SIN
#    contexto de conflicto NO debe caer en 'Bloqueos / Conflictos' (→ politica); y el
#    post-conflicto real SÍ debe caer ahí. (titulo, debe_ser_bloqueos)
TEMA_CHECK = [
    ("Reactivación económica impulsa la inversión extranjera directa", False),
    ("La transitabilidad de la nueva autopista mejora el comercio", False),
    ("Gobierno destaca la reconstrucción del país en salud y educación", False),
    ("Tras el desbloqueo, mejora la transitabilidad en el eje troncal", True),
    ("Reactivación económica tras el levantamiento de los bloqueos", True),
    ("Brigadas parlamentarias investigan los bloqueos en el trópico", True),
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


def _check_embudo() -> list:
    """WS6: el embudo unificado (res['funnel']) debe reconciliar entran→insert.
    Maneja lane_bolivia con un correr_scraper stubeado + LAST_FUNNEL poblado y
    verifica las identidades aritméticas (incluido el bucket kill_sin_razon que
    cierra el modo degradado y el stage scheme_patrocinado del filtro de URL)."""
    import sqlite3
    import types
    import ingest_noticias as ing
    from noticias_ingest import resumen_ia

    e: list[str] = []
    base = {"tema": "Tipo de cambio / Dólar", "tema_hits": 10, "entidades": [], "descripcion": "x",
            "cuerpo": "", "puntaje": 9.0, "score_crudo": 0.9, "score_ajustado": 0.9,
            "ajuste_aplicado": "—", "es_opinion": False}
    cands = [
        {**base, "portal": "El Deber", "titulo": "El dólar sube en Bolivia",
         "link": "https://eldeber.com.bo/economia/a"},
        {**base, "portal": "El Deber", "titulo": "Reservas del BCB en alza",
         "link": "https://eldeber.com.bo/economia/b"},
        {**base, "portal": "El Deber", "titulo": "Nota patrocinada",
         "link": "https://eldeber.com.bo/marcas/promo_c"},  # filtrada por es_url_patrocinada
    ]
    # 60 kills conocidos + sobreviven 5; evaluados 70 → kill_sin_razon = 5 (degradado).
    descs = ([{"descartado_por": "falta_bolivia"}] * 40
             + [{"descartado_por": "keyword_excluida"}] * 15
             + [{"descartado_por": "umbral"}] * 5)
    scraper.LAST_FUNNEL.clear()
    scraper.LAST_FUNNEL.update({"entran": 100, "cache_skip": 30, "evaluados": 70,
                               "sobreviven": 5, "unicos": 3})
    saved = (scraper.correr_scraper, scraper.marcar_urls_vistas, resumen_ia.aplicar)
    scraper.correr_scraper = lambda *a, **k: (cands, descs, ["El Deber"], [])
    scraper.marcar_urls_vistas = lambda v: None
    resumen_ia.aplicar = lambda f: 0
    try:
        conn = sqlite3.connect(":memory:")
        ing.init_schema(conn)
        args = types.SimpleNamespace(umbral=6.7, top=10, dry_run=True, db=":memory:")
        res = ing.lane_bolivia(conn, args, datetime.now(timezone.utc), "2026-06-23", [])
        conn.close()
    finally:
        scraper.correr_scraper, scraper.marcar_urls_vistas, resumen_ia.aplicar = saved

    f = res.get("funnel")
    if not f:
        return ["WS6 embudo: res['funnel'] ausente"]
    if f["evaluados"] != f["entran"] - f["cache_skip"]:
        e.append(f"WS6 embudo: evaluados({f['evaluados']}) != entran-cache_skip({f['entran']-f['cache_skip']})")
    suma = (f["sobreviven"] + f["kill_keyword_excluida"] + f["kill_falta_bolivia"]
            + f["kill_umbral_modelo"] + f["kill_sin_razon"])
    if suma != f["evaluados"]:
        e.append(f"WS6 embudo: sobreviven+kills+sin_razon({suma}) != evaluados({f['evaluados']})")
    if f["kill_sin_razon"] != 5:
        e.append(f"WS6 embudo: kill_sin_razon esperado 5 (modo degradado), dio {f['kill_sin_razon']}")
    if f["scheme_patrocinado"] != len(cands) - f["candidatos"]:
        e.append(f"WS6 embudo: scheme_patrocinado({f['scheme_patrocinado']}) != "
                 f"pre-filtro-candidatos({len(cands)-f['candidatos']})")
    return e


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

    # G. TEMA-CORRECTNESS: recuperación económica sin conflicto NO va a Bloqueos→política.
    for titulo, debe_bloqueos in TEMA_CHECK:
        tema = scraper._tema(titulo)[0]
        es_bloqueos = (tema == "Bloqueos / Conflictos")
        if es_bloqueos != debe_bloqueos:
            esperado = "Bloqueos/Conflictos" if debe_bloqueos else "NO Bloqueos (economía/General)"
            err.append(f"TEMA mal ruteado: {titulo!r} -> {tema!r} (esperado {esperado})")

    # H. WS6 — el embudo unificado reconcilia aritméticamente (entran→insert).
    err += _check_embudo()

    if err:
        print("FAIL test_noticias_funnel_v2:")
        for e in err:
            print("  -", e)
        return 1
    print(f"OK test_noticias_funnel_v2: {len(RESCATES)} rescates sobreviven + "
          f"{len(LEGIT)} legit pasan + {len(OPINION)} opinión < 6.7 + "
          f"{len(CULTURAL)} cultural muere + {len(INTERNACIONAL)} intl fuera del set + "
          f"category='opinion' + {len(TEMA_CHECK)} tema-correctness + embudo reconcilia.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
