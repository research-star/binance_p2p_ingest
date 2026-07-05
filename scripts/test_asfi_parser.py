#!/usr/bin/env python3
"""
test_asfi_parser.py — Tests del módulo ASFI (parser + resumen + candado).

Sub-tests:
  parser_fixture — PDF REAL del Reporte Informativo (03-jul-2026): fecha,
                   secciones/categorías dentro del vocabulario, entidades
                   pobladas, items con arranque canónico, tags coherentes.
  tags           — clasificador de keywords: casos positivos + el falso
                   positivo "cuenta designada" ≠ personal (regresión).
  extracto       — fallback extractivo: primera oración, cap 200, corte limpio.
  extract        — grupo + campos estructurados (préstamo/cupón/emisión/personal
                   + regresión: desembolso de patrimonio autónomo ≠ préstamo).
  candado        — resumen.resumir_item SIN autorizado=True lanza RuntimeError
                   (con key presente); sin key devuelve None sin llamar red.
  cap            — con cap agotado no hay POST (fail-closed devuelve None).

Uso:  python scripts/test_asfi_parser.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from asfi_ingest import extract, parser, resumen  # noqa: E402

FIXTURE = ROOT / "scripts" / "fixtures" / "asfi_reporte_2026-07-03.pdf"


def t_parser_fixture(errores: list):
    rep = parser.extraer_reporte(str(FIXTURE))
    if rep["fecha"] != "2026-07-03":
        errores.append(f"fecha: {rep['fecha']!r} != 2026-07-03")
    items = rep["items"]
    if not (18 <= len(items) <= 30):
        errores.append(f"items: {len(items)} fuera de rango esperado [18,30]")
    secciones = {it["seccion"] for it in items}
    if not secciones <= parser.SECCIONES:
        errores.append(f"secciones fuera de vocabulario: {secciones - parser.SECCIONES}")
    cats = {it["categoria"] for it in items if it["categoria"]}
    if not cats <= parser.CATEGORIAS:
        errores.append(f"categorías fuera de vocabulario: {cats - parser.CATEGORIAS}")
    sin_entidad = [it for it in items if not it["entidad"]]
    if sin_entidad:
        errores.append(f"{len(sin_entidad)} items sin entidad en el fixture")
    # Spot-checks de contenido conocido del reporte del 03-jul
    ents = {it["entidad"] for it in items}
    for esperado in ("Fortaleza Leasing S.A.", "Droguería INTI S.A.",
                     "Banco Ganadero S.A."):
        if esperado not in ents:
            errores.append(f"entidad esperada ausente: {esperado}")
    resol = [it for it in items if it["seccion"] == "Resoluciones Administrativas"]
    if not any(it["entidad"].startswith("ASFI/549/2026") for it in resol):
        errores.append("resolución ASFI/549/2026 no parseada como entidad")
    ganadero = [it for it in items if it["entidad"] == "Banco Ganadero S.A."]
    if not any("compromisos" in it["tags"] for it in ganadero):
        errores.append("compromisos financieros de Banco Ganadero sin tag")
    if not any("13.82%" in it["texto"] for it in ganadero):
        errores.append("tabla de compromisos (CAP 13.82%) no quedó en el texto")


def t_tags(errores: list):
    casos = [
        ("Autorizar la Oferta Pública e inscribir la Emisión de Bonos X", "emision", True),
        ("procedió al pago del Cupón N° 9 de la Serie Única", "cupon", True),
        ("presentó renuncia al cargo de Gerente", "personal", True),
        ("la Junta General Ordinaria de Accionistas determinó", "junta", True),
        ("los fondos disponibles en la cuenta designada", "personal", False),  # regresión
        ("realizó un desembolso de Bs7.000.000,00", "prestamo", True),
    ]
    for texto, tag, debe in casos:
        tiene = tag in parser.clasificar_tags(texto, "Noticias")
        if tiene != debe:
            errores.append(f"tags: {texto[:40]!r} → {tag} esperado={debe} obtuvo={tiene}")
    if "resolucion" not in parser.clasificar_tags("RESUELVE: PRIMERO.-", "Resoluciones Administrativas"):
        errores.append("tags: sección Resoluciones no aporta tag 'resolucion'")


def t_extracto(errores: list):
    r = resumen.extracto("Comunica que pagará dividendos el 3 de julio de 2026. "
                         "Detalle adicional que no debería entrar.")
    if r != "Comunica que pagará dividendos el 3 de julio de 2026.":
        errores.append(f"extracto primera-oración: {r!r}")
    largo = resumen.extracto("palabra " * 60)
    if len(largo) > resumen.RESUMEN_MAX_CHARS or largo.endswith(" "):
        errores.append(f"extracto cap/corte: len={len(largo)}")


def t_extract(errores: list):
    """Clasificación de grupo + extracción de campos (casos reales de calibración)."""
    def item(seccion, texto, entidad="X S.A."):
        it = {"seccion": seccion, "categoria": "", "entidad": entidad,
              "texto": texto, "tags": parser.clasificar_tags(texto, seccion)}
        return extract.enriquecer(it)

    it = item("Hechos Relevantes",
              "Ha comunicado que, el 31 de diciembre de 2025, el Banco BISA S.A., "
              "procedió al desembolso por un monto de Bs25.000.000,00 en calidad de "
              "préstamo de dinero.")
    if it["grupo"] != "prestamos":
        errores.append(f"extract: préstamo → grupo {it['grupo']}")
    c = it.get("campos", {})
    if c.get("banco") != "Banco BISA S.A." or c.get("monto") != "Bs 25,0 M":
        errores.append(f"extract: campos préstamo {c}")

    it = item("Noticias",
              "Comunica que, el pago del Cupón N° 38 de la Emisión de Bonos GAS & "
              "ELECTRICIDAD S.A. (Serie B), se realizará a partir del 6 de julio de 2026.")
    c = it.get("campos", {})
    if it["grupo"] != "cupones" or c.get("cupon_n") != "38" \
            or c.get("instrumento") != "Bonos GAS & ELECTRICIDAD S.A." \
            or c.get("estado") != "programado":
        errores.append(f"extract: cupón {it['grupo']} {c}")

    it = item("Resoluciones Administrativas",
              "RESUELVE: PRIMERO.- Autorizar la Oferta Pública e inscribir la Emisión "
              "de Bonos denominada \u201cBONOS TIENDA AMIGA II\u201d de TIENDA AMIGA ER S.A., "
              "bajo el Número de Registro ASFI/DSV-ED-TAE-030/2026 y Clave de Pizarra "
              "TAE-N1U-26.")
    c = it.get("campos", {})
    if it["grupo"] != "emisiones" or c.get("emisor") != "TIENDA AMIGA ER S.A." \
            or c.get("instrumento") != "BONOS TIENDA AMIGA II" \
            or c.get("registro") != "ASFI/DSV-ED-TAE-030/2026":
        errores.append(f"extract: emisión {it['grupo']} {c}")

    # Desembolso de patrimonio autónomo NO es préstamo bancario (regresión iBolsa)
    it = item("Noticias",
              "Comunica que, en calidad de Administrador del Patrimonio Autónomo LAS "
              "LOMAS, se efectuó el desembolso correspondiente al capital de operaciones "
              "del Originador.")
    if it["grupo"] == "prestamos":
        errores.append("extract: desembolso de patrimonio autónomo cayó en préstamos")

    it = item("Noticias",
              "Comunica que, la señora Dennise Karina Nistahuz Ibañez, presentó renuncia "
              "el 2 de julio de 2026, a los cargos: Responsable de Gestión de Riesgos.")
    c = it.get("campos", {})
    if it["grupo"] != "personal" or c.get("persona") != "Dennise Karina Nistahuz Ibañez" \
            or c.get("movimiento") != "renuncia":
        errores.append(f"extract: personal {it['grupo']} {c}")


    # V3: grupos nuevos (feedback Diego 2026-07-05)
    it = item("Hechos Relevantes",
              "Comunica que, en reunión de Directorio de 2 de julio de 2026, se aprobó "
              "la convocatoria a Junta General Ordinaria de Accionistas, a realizarse el "
              "14 de julio de 2026 a Hrs. 09:30: 1. Distribución y tratamiento de "
              "Resultados de la Gestión 2025.")
    c = it.get("campos", {})
    if it["grupo"] != "juntas" or c.get("tipo") != "Ordinaria" \
            or c.get("fecha_junta") != "14 de julio de 2026" \
            or "distribución de resultados" not in c.get("agenda", ""):
        errores.append(f"extract: convocatoria MADISA {it['grupo']} {c}")

    it = item("Hechos Relevantes",
              "Ha comunicado que la Junta determinó: 1. La remoción de los señores: "
              "Oscar Álvarez Daher y Stevo Ostoic Gonzales de sus cargos de Directores "
              "Titulares. 2. Nombrar como Directores Titulares a los señores: Sergio "
              "Antonio Gottret Valdez y Víctor Eduardo Durán Saavedra.")
    cambios = it.get("campos", {}).get("cambios", [])
    salen = [x["persona"] for x in cambios if x["tipo"] == "sale"]
    entran = [x["persona"] for x in cambios if x["tipo"] == "entra"]
    if it["grupo"] != "directorio" or len(salen) != 2 or len(entran) != 2 \
            or "Oscar Álvarez Daher" not in salen:
        errores.append(f"extract: directorio {it['grupo']} salen={salen} entran={entran}")

    it = item("Noticias",
              "Comunica que, los Compromisos Financieros son: Coeficiente de Adecuación "
              "Patrimonial (CAP)(i) CAP>=11% 13.82% Índice de Liquidez (IL)(i) IL>= 50% "
              "66.38% Coeficiente de Apalancamiento Financiero (CAF): CAF <=2,00 1,93")
    inds = {x["sigla"]: x for x in it.get("campos", {}).get("indicadores", [])}
    if it["grupo"] != "compromisos" or "CAP" not in inds or not inds["CAP"]["ok"] \
            or "CAF" not in inds or not inds["CAF"]["ok"]:
        errores.append(f"extract: indicadores {inds}")
    it = item("Noticias",
              "Ha comunicado que, los Compromisos Financieros son los siguientes: "
              "Coeficiente de Adecuación Patrimonial mayor o igual al 11% Al 31/12/2025, "
              "el promedio del Coeficiente de Adecuación Patrimonial fue de 13,07%.")
    inds = it.get("campos", {}).get("indicadores", [])
    if not any(x["sigla"] == "CAP" and x["ok"] for x in inds):
        errores.append(f"extract: indicador verbal BCP {inds}")

    it = item("Hechos Relevantes",
              "Ha comunicado que en reunión de Directorio se determinó: Aprobar la "
              "contratación de la firma BERTHINASSURANCE GROUP AUDITORÍA & CONSULTORÍA "
              "S.R.L. para la realización de la Auditoría Externa correspondiente a la "
              "gestión 2026.")
    c = it.get("campos", {})
    if it["grupo"] != "auditorias" or "BERTHINASSURANCE" not in c.get("firma", ""):
        errores.append(f"extract: auditoría {it['grupo']} {c}")


def t_candado(errores: list):
    prev = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        # Sin key → None sin red ni candado.
        if resumen.resumir_item("X", "texto") is not None:
            errores.append("candado: sin key debería devolver None")
        # Con key pero sin autorizado → RuntimeError ANTES de cualquier POST.
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fake"
        try:
            resumen.resumir_item("X", "texto sustantivo de prueba")
            errores.append("candado: sin autorizado=True debería lanzar RuntimeError")
        except RuntimeError:
            pass
    finally:
        if prev is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = prev


def t_cap(errores: list):
    import sqlite3
    prev = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-fake"
    conn = sqlite3.connect(":memory:")
    try:
        resumen.init_spend_schema(conn)
        mes = resumen._mes_utc()
        conn.execute("INSERT INTO asfi_api_spend (mes, est_usd) VALUES (?, ?)",
                     (mes, 99.0))
        conn.commit()
        # Cap agotado → None (fail-closed, sin POST — con key fake, un POST real
        # fallaría distinto: acá esperamos None limpio ANTES de tocar red).
        r = resumen.resumir_item("X", "texto sustantivo", autorizado=True, conn=conn)
        if r is not None:
            errores.append(f"cap: agotado debería dar None, dio {r!r}")
        # conn=None → cap ilegible → fail-closed None.
        r2 = resumen.resumir_item("X", "texto sustantivo", autorizado=True, conn=None)
        if r2 is not None:
            errores.append("cap: conn=None debería fail-closear a None")
    finally:
        conn.close()
        if prev is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = prev


def run() -> int:
    errores: list = []
    for t in (t_parser_fixture, t_tags, t_extracto, t_extract, t_candado, t_cap):
        t(errores)
    if errores:
        print("FAIL test_asfi_parser:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_asfi_parser: fixture real 03-jul parsea fecha/secciones/entidades/"
          "tags (incl. tabla compromisos Banco Ganadero); clasificador sin falso "
          "positivo 'designada'; extracto con cap 200; extract clasifica grupo y "
          "campos (préstamo/cupón/emisión/personal, patrimonio autónomo ≠ préstamo); "
          "candado lanza sin autorizado; "
          "cap agotado y conn=None fail-closean sin POST.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
