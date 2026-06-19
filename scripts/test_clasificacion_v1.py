#!/usr/bin/env python3
"""
test_clasificacion_v1.py — Batería de aceptación del clasificador de tema v1
(FASE 3, Capa 1). Corre _tema() + detectar_entidades() sobre titulares reales y
sintéticos de noticias económicas bolivianas (batería diseñada por workflow de 3
enfoques + síntesis). Verifica que los falsos positivos del recon ya no disparan
tema errado y que los casos buenos no regresan.

NO toca DB ni red: _tema es keyword-puro (el modelo TF-IDF es ortogonal, da
relevancia). Uso: python scripts/test_clasificacion_v1.py

Casos 'must': aceptación dura (4 trampas del recon + casos buenos + entidades).
Casos 'soft': el síntesis los marcó como límite conocido (dependen de
KEYWORDS_EXCLUIR upstream que _tema no aplica) o decisión flageada — se reportan,
no fallan el build.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from noticias_ingest.scraper import _tema, detectar_entidades

G = "General"
# (titulo, tema_esperado, entidades_esperadas⊆, modo)
BATERIA = [
    # ── 4 trampas del recon (deben quedar arregladas) ──
    ("Mas mujeres estudian, pero no lideran la innovacion: la deuda pendiente de la educacion boliviana", G, [], "must"),
    ("Bolivia protegera su Amazonia con una inversion de mas de 18 millones de dolares", "Inversión / Infraestructura", [], "must"),
    ("Gobierno y COB inician dialogo en ambientes del BCB", G, ["Gobierno", "COB", "BCB"], "must"),
    ("Bolivia recibio 272 millones de dolares en remesas en lo que va del ano", G, [], "must"),
    # ── casos buenos que NO deben regresar ──
    ("94 bloqueos afectan Bolivia; Cochabamba epicentro del cierre de rutas", "Bloqueos / Conflictos", [], "must"),
    ("Chile hace nuevo envio de ayuda a Bolivia para enfrentar el desabastecimiento de combustible", "Combustibles / YPFB", [], "must"),
    ("La deuda externa de Bolivia llega a 14.418 millones de dolares", "Deuda / Finanzas", [], "must"),
    ("Cotizacion del dolar paralelo sube; brecha con el oficial se amplia", "Tipo de cambio / Dólar", [], "must"),
    ("YLB firma contrato para industrializar el carbonato de litio del salar de Uyuni", "Litio / Minería", ["YLB"], "must"),
    ("ANAPO proyecta mayor cosecha de soya en la zafra de verano", "Agropecuario / Soya", ["ANAPO"], "must"),
    # ── trampas de substring (oro/deuda/dólar/entidad-lugar) ──
    ("Bolivia gana medalla de oro en los Juegos Suramericanos", G, [], "must"),
    ("Tigre y Bolivar empatan en clasico paceno por la Liga", G, [], "must"),
    ("Feminicidio en El Alto: detienen al presunto autor del crimen", G, [], "must"),
    ("El Gobierno destaca su deuda social saldada con los mas pobres", G, ["Gobierno"], "must"),
    ("Filas en surtidores de Santa Cruz por falta de diesel para el agro", "Combustibles / YPFB", [], "must"),
    ("BCB sube reservas internacionales y defiende el tipo de cambio fijo", "Tipo de cambio / Dólar", ["BCB"], "must"),
    ("Productores de maiz y trigo piden mejores precios al Gobierno", "Agropecuario / Soya", ["Gobierno"], "must"),
    ("Fitch baja la calificacion crediticia de Bolivia por el deficit fiscal", "Deuda / Finanzas", ["Fitch"], "must"),
    ("Inversion emocional: como criar hijos resilientes, segun una psicologa", G, [], "must"),
    ("FMI desembolsa prestamo a Bolivia para reforzar reservas", "Deuda / Finanzas", ["FMI"], "must"),
    ("INE reporta que la inflacion acumulada llega al 7% y encarece la canasta basica", "Inflación / Precios", ["INE"], "must"),
    ("Aduana decomisa contrabando de ropa usada valorado en 2 millones de dolares", "Exportaciones / Comercio", ["Aduana"], "must"),
    ("Las reservas internacionales del BCB caen y el dolar paralelo se dispara", "Tipo de cambio / Dólar", ["BCB"], "must"),
    ("YPFB anuncia normalizacion del abastecimiento de diesel en surtidores del eje troncal", "Combustibles / YPFB", ["YPFB"], "must"),
    ("ASFI advierte sobre creditos fraudulentos en el sistema financiero boliviano", "Deuda / Finanzas", ["ASFI"], "must"),
    ("El plan de oro del gobierno para reactivar la economia", G, ["Gobierno"], "must"),
    ("Ahorrar es una deuda con vos mismo: educacion financiera para jovenes", G, [], "must"),
    ("Productores de cine boliviano piden creditos para sus proyectos", G, [], "must"),
    ("Paro cardiaco obliga a suspender el partido en el estadio", G, [], "must"),
    ("Gobierno y la Aduana incautan contrabando de gasolina en la frontera", "Combustibles / YPFB", ["Gobierno", "Aduana"], "must"),
    ("Suben los precios de la canasta basica y la inflacion preocupa a las familias", "Inflación / Precios", [], "must"),
    ("FMI proyecta que el deficit fiscal de Bolivia superara el 7% del PIB", "Deuda / Finanzas", ["FMI"], "must"),
    ("El BCB anuncia nuevas medidas para sostener las reservas internacionales", "Tipo de cambio / Dólar", ["BCB"], "must"),
    ("Bolivia gana medalla de oro en atletismo; tambien sube el dolar paralelo ese dia", "Tipo de cambio / Dólar", [], "must"),
    # soft: ambigüedad genuina soya(strong+weak=11) vs bloqueo(strong=10) — la síntesis lo flageó como desempate
    ("Productores de soya rechazan el bloqueo de la carretera a Santa Cruz", "Bloqueos / Conflictos", [], "soft"),
    ("El TSE define el calendario electoral para la segunda vuelta", "Elecciones / Política económica", ["TSE"], "must"),
    ("EMAPA garantiza abastecimiento de arroz y azucar a precio subvencionado", "EMAPA / Alimentos", ["EMAPA"], "must"),
    ("Bonos del tesoro boliviano captan 500 millones en el mercado de capitales", "Deuda / Finanzas", [], "must"),
    ("Gremialistas anuncian paro y marcha en La Paz contra los impuestos", "Bloqueos / Conflictos", [], "must"),
    ("Senasag certifica frigorificos para exportar carne bovina a China", "Agropecuario / Soya", ["SENASAG"], "must"),
    ("Comibol reactiva la mina de estano de Huanuni tras inversion estatal", "Litio / Minería", ["COMIBOL"], "must"),
    ("El IBCE reporta caida de exportaciones no tradicionales en el primer trimestre", "Exportaciones / Comercio", ["IBCE"], "must"),
    # ── soft: límites conocidos (upstream KEYWORDS_EXCLUIR) o decisiones flageadas ──
    ("Lula y Sheinbaum debaten sobre litio en cumbre de la CELAC", G, [], "soft"),
    ("Capturan a banda que asaltaba surtidores en El Alto", G, [], "soft"),
    ("Aduana retiene mercaderia china en zona franca por subfacturacion", "Exportaciones / Comercio", ["Aduana"], "soft"),
    ("El precio del oro en los mercados internacionales alcanza maximo historico", G, [], "soft"),
    ("La CAF aprueba credito de 200 millones de dolares para una carretera", "Inversión / Infraestructura", ["CAF"], "soft"),
    ("El dolar se mantiene estable mientras el Gobierno destaca su politica economica", G, ["Gobierno"], "soft"),
    ("Diputados debaten el presupuesto general del Estado para 2027", G, [], "soft"),
]


def run():
    must_fail, soft_fail = [], []
    for titulo, tema_exp, ents_exp, modo in BATERIA:
        tema, conf = _tema(titulo)
        ents = detectar_entidades(titulo)
        ok_tema = (tema == tema_exp)
        ok_ents = set(ents_exp) <= set(ents)
        if not (ok_tema and ok_ents):
            row = (titulo[:62], tema_exp, f"{tema} (c={conf})", ents_exp, ents)
            (must_fail if modo == "must" else soft_fail).append(row)

    total = len(BATERIA)
    must = sum(1 for *_, m in BATERIA if m == "must")
    print(f"Batería clasificación v1: {total} casos ({must} must, {total - must} soft)")
    print(f"  must: {must - len(must_fail)}/{must} OK · soft: {total - must - len(soft_fail)}/{total - must} OK")

    if soft_fail:
        print("\n  soft (límite conocido / flageado — no falla el build):")
        for t, exp, got, ee, ge in soft_fail:
            print(f"    ~ esperaba {exp!r} → obtuvo {got}  | {t}")

    if must_fail:
        print("\nFAIL — casos 'must' fallidos:")
        for t, exp, got, ee, ge in must_fail:
            print(f"  - esperaba {exp!r} ({ee}) → obtuvo {got} ents={ge}  | {t}")
        return 1
    print("\nOK: las 4 trampas del recon arregladas + casos buenos sin regresión + entidades.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
