#!/usr/bin/env python3
"""
test_noticias_dedup_tema.py — Blinda el fix de clasificacion+dedup del par cacao
(El Deber/El Mundo, 2026-07-08) y sus guardas de regresion.

Cubre:
  - Cambio 1 (tema): el VERBO exportar (exporto/exporta/exportaron) clasifica en
    'Exportaciones / Comercio' (antes solo el sustantivo). Guardas: la auto-gatera
    del verbo se acota con exclude de metaforas ("exporta cultura/talento"); el verbo
    'importar' NO se agrega (context 'importac' no matchea "importa=tener importancia").
  - Cambio 1b (Inversion): el verbo invertir (invirtio/invierte) clasifica en
    'Inversion / Infraestructura' cuando co-ocurre con contexto de obra/monto.
  - B1 (_titulo_limpio): recorta colas tipo-dominio de publisher (elmundo.com.bo, ...)
    via allow-list EXPLICITA; NO recorta un dominio ajeno no listado.
  - B2 (entidades commodity): cacao/quinua/... se detectan como entidad para el rescate
    de capa B, pero NO anclan geograficamente (fuera de ENTIDADES_BOLIVIANAS): una nota
    de cacao 100% extranjera sigue cortada por el geo-gate.
  - End-to-end: el par cacao real agrupa via _mismo_evento (titulo>=0.50 + entidad
    compartida); dos eventos de cacao DISTINTOS (titulo bajo) NO colapsan.
  - Alias de referente (clave_dedup): EEUU/Estados Unidos/EE.UU. pliegan al mismo token
    (sube la similitud cross-outlet); el verbo "usa" NO se pliega (colision evitada).
  - Ancla-monto (es_repetida/_mismo_evento): un monto exacto compartido + titulo>=0.62
    rescata gemelos sin commodity ni entidad (par El Dia/Unitel 2026-07-16); guarda de
    over-merge: mismo monto redondo con titulo <0.62 (evento distinto) NO colapsa.

El modelo TF-IDF se stubea (como en test_noticias_relevancia). Uso:
  python scripts/test_noticias_dedup_tema.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import scraper
from ingest_noticias import _mismo_evento, es_repetida

# Par cacao real (prod 2026-07-08). Con acentos como llegan del feed.
DEBER_T = "Bolivia exportó $us 11 millones en cacao durante 2025 - El Deber"
DEBER_D = ("Bolivia exportó 1.040 toneladas de cacao y derivados por 11 millones de dólares "
           "en 2025, llegando a 16 mercados internacionales con Alemania como principal destino.")
MUNDO_T = "Exportaciones de cacao generaron $us 11 millones en 2025 - elmundo.com.bo"
MUNDO_D = ("Las 1.040 toneladas de cacao boliviano exportadas en 2025 llegaron a 16 países, "
           "siendo Alemania el principal destino con el 45,2% de las ventas.")


class _ModeloStub:
    disponible = True

    def puntaje(self, titulo: str, descripcion: str) -> float:
        return 0.9


def run() -> int:
    scraper.get_modelo = lambda: _ModeloStub()
    err = []

    def eq(desc, got, exp):
        if got != exp:
            err.append(f"{desc}: got {got!r}, esperado {exp!r}")

    def ok(desc, cond):
        if not cond:
            err.append(desc)

    # ── Cambio 1: verbo exportar clasifica (era el bug del par cacao) ──
    tema_d, conf_d = scraper._tema(DEBER_T, DEBER_D)
    eq("DEBER (verbo exporto) -> tema", tema_d, "Exportaciones / Comercio")
    ok(f"DEBER conf>=1 (got {conf_d})", conf_d >= 1)
    tema_m, _ = scraper._tema(MUNDO_T, MUNDO_D)
    eq("MUNDO (sustantivo) -> tema", tema_m, "Exportaciones / Comercio")

    # Guarda: metafora no-comercial de exportar NO clasifica (exclude).
    eq("exporta cultura -> General (exclude)",
       scraper._tema("Bolivia exporta cultura y talento al mundo entero")[0], "General")

    # Guarda: verbo 'importar=tener importancia' NO dispara Exportaciones (context 'importac').
    eq("no le importa -> General",
       scraper._tema("A la gente no le importa la política nacional")[0], "General")
    eq("no importa el resultado -> General",
       scraper._tema("No importa el resultado, importa el esfuerzo del equipo")[0], "General")
    # 'importante'/'importancia' no debe gatear el weak de importacion.
    eq("es importante -> no Exportaciones",
       scraper._tema("Es importante la unidad del país, dice un analista")[0] != "Exportaciones / Comercio", True)
    # El sustantivo importacion SIGUE clasificando (no se rompio).
    eq("importaciones (sustantivo) sigue clasificando",
       scraper._tema("Las importaciones de vehículos crecieron según la Aduana Nacional")[0],
       "Exportaciones / Comercio")

    # ── Cambio 1b: verbo invertir clasifica con contexto de obra/monto ──
    eq("invirtio + planta/millones -> Inversion",
       scraper._tema("El Estado invirtió $us 500 millones en la nueva planta siderúrgica")[0],
       "Inversión / Infraestructura")

    # ── B1: _titulo_limpio recorta dominio de publisher pero NO un dominio ajeno ──
    eq("B1 recorta elmundo.com.bo",
       scraper._titulo_limpio(MUNDO_T),
       "Exportaciones de cacao generaron $us 11 millones en 2025")
    eq("B1 recorta - El Deber",
       scraper._titulo_limpio(DEBER_T),
       "Bolivia exportó $us 11 millones en cacao durante 2025")
    # Dominio ajeno NO listado: no se recorta (allow-list, no TLD generico).
    ajeno = "Presentan la nueva plataforma - ejemplo.com.ar"
    eq("B1 no recorta dominio ajeno", scraper._titulo_limpio(ajeno), ajeno)

    # ── B2: entidades commodity ──
    ent_d = scraper.detectar_entidades(DEBER_T, DEBER_D)
    ent_m = scraper.detectar_entidades(MUNDO_T, MUNDO_D)
    ok(f"DEBER detecta Cacao (got {ent_d})", "Cacao" in ent_d)
    ok(f"MUNDO detecta Cacao (got {ent_m})", "Cacao" in ent_m)
    # Geo-gate anti-leak: commodity NO ancla Bolivia. Nota de cacao 100% extranjera
    # (produccion, sin verbo/sustantivo de exportacion -> tema General) sigue cortada.
    for foranea in ("Costa de Marfil y Ghana lideran la producción mundial de cacao",
                    "Ecuador es el mayor productor de cacao fino de la región"):
        r = scraper.evaluar(foranea, "", "El Deber")
        eq(f"geo-gate corta cacao extranjero: {foranea[:35]}", r[7], "falta_bolivia")
    ok("Cacao NO esta en ENTIDADES_BOLIVIANAS", "Cacao" not in scraper.ENTIDADES_BOLIVIANAS)

    # ── End-to-end: el par real agrupa (capa B: titulo>=0.50 + entidad compartida) ──
    nd = {"title": DEBER_T, "entidades": ent_d}
    nm = {"title": MUNDO_T, "entidades": ent_m}
    ok("par cacao real AGRUPA (mismo evento)", _mismo_evento(nd, nm) is True)

    # Over-merge: dos eventos de cacao DISTINTOS con titulo bajo NO colapsan aunque
    # compartan la entidad 'Cacao' (el piso de titulo sigue mandando).
    otro_t = "Cacaoteros del Alto Beni bloquean la vía exigiendo mejor precio"
    otro = {"title": otro_t, "entidades": scraper.detectar_entidades(otro_t)}
    sim_lejos = scraper.similitud(scraper._titulo_limpio(DEBER_T), scraper._titulo_limpio(otro_t))
    ok(f"eventos de cacao distintos NO colapsan (sim {sim_lejos:.3f} < 0.50)",
       _mismo_evento(nd, otro) is False)

    # ── Mitigaciones de la review adversarial ──
    # Inversión: guarda del verbo "invertir=revertir" (marcador/tendencia/roles) con
    # context amplio ('millones'). El true-positive de arriba (planta siderúrgica) sigue OK.
    ok("invirtio el marcador + millones NO es Inversion",
       scraper._tema("El equipo invirtió el marcador cuando faltaban millones de segundos")[0]
       != "Inversión / Infraestructura")
    ok("invierte los roles + millones NO es Inversion",
       scraper._tema("El humor invierte los roles y recauda millones en taquilla")[0]
       != "Inversión / Infraestructura")
    # Export: metáfora socio-política vetada por exclude.
    eq("exporta pobreza -> General",
       scraper._tema("Bolivia exporta pobreza a los países vecinos según un informe")[0], "General")
    # Deuda: gap 'endeudamiento' (endeud* no lo cubría 'deuda' por word-boundary).
    eq("endeudamiento -> Deuda",
       scraper._tema("Crece el endeudamiento de los hogares bolivianos, alerta un estudio")[0],
       "Deuda / Finanzas")
    # B2: commodities de exportación como entidad (incl. girasol/chía: colisión con nombre
    # propio aceptada como marginal, decisión de Diego).
    for c in ("Cacao", "Quinua", "Castana", "Cafe", "Girasol", "Chia"):
        ok(f"{c} es entidad", c in scraper._ENTIDADES)
    ok("Cacao NO en geo-gate (no ancla extranjero)", "Cacao" not in scraper.ENTIDADES_BOLIVIANAS)

    # ── Dedup inter-día (es_repetida) ─────────────────────────────────────
    # (2) Rescate por COMMODITY compartido en banda [0.50,0.62): dos notas de cacao con
    # título 0.519 (wording distinto, sin monto) agrupan por la entidad 'Cacao'.
    CA1 = "El cacao boliviano gana nuevos mercados en Europa pese a la sequía"
    CA2 = "Pese a la sequía, el cacao de Bolivia conquista mercados europeos"
    ok("es_repetida: rescate commodity (Cacao) en banda 0.50-0.62",
       es_repetida(CA2, ["Cacao"], [(CA1, {"Cacao"})]) is True)
    # (1) Título ≥0.70 atrapa el near-dup exacto (acentos plegados por clave_dedup).
    ok("es_repetida: título >=0.70 atrapa near-dup exacto",
       es_repetida("Bolivia exportó $us 11 millones en cacao durante 2025",
                   [], [(DEBER_T, set())]) is True)
    # Guarda anti sobre-supresión: entidad INSTITUCIONAL (BCB, no commodity) NO rescata
    # en banda. Títulos 0.543<0.70, comparten BCB pero BCB∉commodity y sin monto → NO repite.
    IN1 = "El BCB reporta una caída en las reservas internacionales del país"
    IN2 = "BCB implementa nuevas medidas para el mercado cambiario nacional"
    ok("es_repetida: entidad institucional (BCB) NO rescata en banda",
       es_repetida(IN2, ["BCB"], [(IN1, {"BCB"})]) is False)
    # Commodity compartido pero título <0.50 → NO repite (el piso de título sigue mandando).
    ok("es_repetida: commodity pero título <0.50 NO repite",
       es_repetida("Cacaoteros del Alto Beni bloquean la vía exigiendo mejor precio",
                   ["Cacao"], [(DEBER_T, {"Cacao"})]) is False)

    # ── Alias de referente: EEUU == Estados Unidos == EE.UU. (clave_dedup) ──
    ok("clave_dedup pliega EEUU y Estados Unidos al mismo token",
       scraper.clave_dedup("Bolivia y EEUU firman acuerdo") ==
       scraper.clave_dedup("Bolivia y Estados Unidos firman acuerdo"))
    ok("es_repetida: alias sube el título ≥0.70 (EEUU vs Estados Unidos)",
       es_repetida("Bolivia y EEUU firman un acuerdo de cooperación comercial",
                   [], [("Bolivia y Estados Unidos firman un acuerdo de cooperación comercial",
                         set())]) is True)
    # Guarda: el verbo español "usa" NO se pliega a Estados Unidos (colisión evitada).
    ok("clave_dedup no pliega el verbo 'usa'",
       "estadosunidos" not in scraper.clave_dedup("El gobierno usa recursos públicos del Estado"))

    # ── Ancla-monto: rescata gemelos sin commodity ni entidad (par El Día/Unitel real) ──
    ELDIA = "Acuerdo entre Bolivia y Estados Unidos contempla cooperación de hasta $us 40 millones"
    UNITEL = ("Bolivia y EEUU suscriben memorándum que proyecta cooperación de hasta "
              "$us 40 millones para desarrollo")
    eq("montos() extrae la cifra con escala", scraper.montos(ELDIA), frozenset({"40_millon"}))
    ok("es_repetida: ancla-monto atrapa El Día/Unitel (0.649, $us 40 millones)",
       es_repetida(UNITEL, [], [(ELDIA, set())]) is True)
    ok("_mismo_evento: ancla-monto agrupa El Día/Unitel intra-corrida",
       _mismo_evento({"title": ELDIA, "entidades": []},
                     {"title": UNITEL, "entidades": []}) is True)
    # Over-merge guard: mismo monto redondo pero evento distinto (título 0.585<0.62) NO repite.
    ok("es_repetida: monto compartido pero título <0.62 (evento distinto) NO repite",
       es_repetida("El Gobierno invertirá $us 2.000 millones en nuevas carreteras",
                   [], [("El BCB reporta reservas internacionales por $us 2.000 millones",
                         set())]) is False)

    if err:
        print("FAIL test_noticias_dedup_tema:")
        for e in err:
            print("  -", e)
        return 1
    print("OK test_noticias_dedup_tema: verbo exportar/invertir clasifica + guardas "
          "(metafora/importa) + B1 recorta dominio publisher (allow-list) + B2 commodity "
          "como entidad SIN leak geo-gate + par cacao agrupa (capa B) + no over-merge + "
          "alias de referente (EEUU=Estados Unidos, verbo 'usa' safe) + ancla-monto "
          "(El Día/Unitel rescatado, cifra redonda distinta NO colapsa).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
