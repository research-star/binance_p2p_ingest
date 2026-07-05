"""parser.py — Reporte Informativo ASFI (PDF) → items estructurados.

El PDF es un layout DevExpress estable (validado contra los 122 reportes de
2026): secciones en Arial-Bold >13pt, categorías y entidades en Arial-Bold
12pt, cuerpo en Arial regular. El texto plano de pypdf sale en orden de
lectura correcto, así que la estrategia es híbrida:

  1. extract_text() plano = stream maestro de líneas (orden confiable).
  2. Un visitor recolecta QUÉ líneas son bold y cuáles son sección (>13pt).
  3. Cada línea del stream se clasifica contra esos sets + vocabulario fijo
     de categorías + heurísticas de razón social.

Trampa principal: las tablas de calificadoras y de compromisos financieros
también usan bold en celdas ("EMISOR", "DATEC LTDA.", "Bonos DATEC II").
Reglas anti-tabla:
  - En categoría de calificadoras, solo una línea que parezca nombre de
    calificadora (Calificadora/Ratings/Moody/AESA/PCR) corta entidad; el
    resto del bold es cuerpo (celdas).
  - Fuera de eso, un bold solo corta entidad si parece razón social
    (_ES_ENTIDAD) o ID de trámite ASFI/…; los demás bold (headers de tabla,
    "Ver Adjunto") se anexan al item abierto.

Salida por reporte: {"fecha": "YYYY-MM-DD", "items": [{seccion, categoria,
entidad, texto, tags}]}. Sin resumen IA acá — eso lo agrega resumen.py.
"""
from __future__ import annotations

import io
import re
import unicodedata

from pypdf import PdfReader

# ── Vocabularios (survey 122 reportes ene–jul 2026) ─────────────────────────

SECCIONES = {
    "Hechos Relevantes",
    "Noticias",
    "Resoluciones Administrativas",
    "Cartas Circulares",
    "Cartas de Autorización",
    "Cartas de Aclaración",
}

CATEGORIAS = {
    "Agencias de Bolsa",
    "Almacenes Generales de Depósito",
    "AUTORIDAD DE SUPERVISIÓN DEL SISTEMA FINANCIERO",
    "Bolsas de Valores",
    "Empresas de Arrendamiento Financiero",
    "Empresas de Auditoría",
    "Empresas de Seguros Generales",
    "Empresas de Seguros de Personas",
    "Empresas Privadas (Emisores)",
    "Entidades Calificadoras de Riesgos Extranjeras",
    "Entidades Calificadoras de Riesgos Nacionales",
    "Entidades de Depósito de Valores",
    "Fondos de Inversión",
    "Instituciones Financieras de Desarrollo",
    "Sociedades Administradoras de Fondos de Inversión",
    "Sociedades de Titularización",
    "SOCIEDADES CONTROLADORAS DE GRUPOS FINANCIEROS",
}

_CATEGORIAS_CALIFICADORAS = {
    "Entidades Calificadoras de Riesgos Nacionales",
    "Entidades Calificadoras de Riesgos Extranjeras",
}

# Boilerplate de página (header/footer del template DevExpress) — se descarta.
_BOILERPLATE = (
    "El contenido de la información presentada al RMV",
    "presente e inscriba, así como su difusión",
    "DIRECCIÓN DE SUPERVISIÓN DE VALORES",
    "REGISTRO DEL MERCADO DE VALORES",
    "REPORTE INFORMATIVO",
)
_RE_FOOTER = re.compile(r"^\d+/\d+$")
_RE_FECHA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")

# ID de trámite como header de entidad (Resoluciones / Cartas):
#   "ASFI/549/2026 de 26 de junio de 2026", "ASFI/DSV/CC-1428 de 24 de junio…",
#   "ASFI/DSV/R-293741 de 22 de diciembre de 2025".
_RE_TRAMITE = re.compile(r"^ASFI/\S+(?:\s+de\s+\d{1,2}\s+de\s+\w+\s+de\s+\d{4})?\s*$")

# Razón social / nombre de entidad supervisada (para bold 12pt fuera de tabla).
_ES_ENTIDAD = re.compile(
    r"(S\.\s?A\.|S\.\s?R\.\s?L\.|LTDA\.?|Ltda\.?|R\.\s?L\.|"
    r"\bIFD\b|\bFRIF\b|\bSAFI\b|\bFIC\b|"
    r"Agencia de Bolsa|Fondo de Inversión|Sociedad de Titularización|"
    r"Sociedad Administradora|Bolsa Boliviana|Banco\b|Fundación|Cooperativa|"
    r"Gobierno Autónomo|Entidad de Depósito|Droguería|Compañía)",
)
_ES_CALIFICADORA = re.compile(r"Calificadora|Ratings|Moody|AESA|Pacific Credit")

# Arranques de comunicado — separan items múltiples bajo la misma entidad.
_RE_ITEM_START = re.compile(
    r"^(Ha comunicado|Comunica(?:n|ron)?\b|Comunicó|Mediante carta|RESUELVE)"
)

# ── Tags (clasificación determinística por keywords) ────────────────────────

_TAGS = [
    ("emision", re.compile(
        r"oferta pública|programa de emisiones|emisión de (bonos|pagarés|acciones|valores|cuotas)|"
        r"pagarés bursátiles", re.I)),
    ("cupon", re.compile(
        r"pago del cupón|amortización de capital|cupón n|agente pagador", re.I)),
    ("calificacion", re.compile(
        r"calificación de riesgo|sesiones de comité|perspectiva", re.I)),
    ("compromisos", re.compile(
        r"compromisos financieros|coeficiente de adecuación patrimonial|"
        r"índice de liquidez|índice de cobertura|coeficiente de cobertura", re.I)),
    ("junta", re.compile(r"junta general|asamblea general", re.I)),
    ("personal", re.compile(
        r"renuncia|design(ó|a\b|ación)|desvincul|remoci(ó|o)n|nombramiento|"
        r"\ba\.i\.|vacaciones|acefal", re.I)),
    ("prestamo", re.compile(r"desembolso|préstamo de dinero", re.I)),
    ("dividendos", re.compile(r"dividendos", re.I)),
    ("uso_fondos", re.compile(
        r"recursos captados|capital de operaciones|capital de inversión|"
        r"destino de los recursos", re.I)),
    ("titularizacion", re.compile(r"patrimonio autónomo", re.I)),
    ("auditoria", re.compile(r"auditoría externa|firma de auditoría", re.I)),
]
_MAX_TAGS = 3


def clasificar_tags(texto: str, seccion: str) -> list[str]:
    """Tags por keywords, primeros _MAX_TAGS que matcheen (orden = prioridad).
    Las secciones administrativas aportan su propio tag de fondo."""
    tags = [nombre for nombre, rx in _TAGS if rx.search(texto)][:_MAX_TAGS]
    if seccion == "Resoluciones Administrativas" and "resolucion" not in tags:
        tags.append("resolucion")
    elif seccion.startswith("Cartas") and "tramite" not in tags:
        tags.append("tramite")
    return tags


# ── Extracción ───────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Normaliza whitespace para comparar línea plana vs línea del visitor."""
    return " ".join(s.split())


def _lineas_bold(page) -> tuple[set[str], set[str]]:
    """(bold_12, secciones_locales) — textos normalizados de líneas 100% bold.

    Agrupa runs del visitor por coordenada Y del text-matrix (misma línea
    visual). Una línea es bold si TODOS sus runs son bold. Además agrega los
    runs bold individuales al set: en tablas, la línea plana a veces contiene
    solo la celda ("DATEC LTDA.") aunque el visitor la agrupe con otras.
    """
    lineas: dict[float, list] = {}

    def vis(text, cm, tm, font_dict, font_size):
        t = text.strip()
        if not t:
            return
        fname = str(font_dict.get("/BaseFont", "")) if font_dict else ""
        y = round(tm[5], 0)
        lineas.setdefault(y, []).append((tm[4], t, "Bold" in fname, font_size or 0))

    page.extract_text(visitor_text=vis)
    bold12: set[str] = set()
    secciones: set[str] = set()
    for runs in lineas.values():
        bolds = [r for r in runs if r[2]]
        for _, t, _, s in bolds:  # celdas sueltas (ver docstring)
            if s <= 13:
                bold12.add(_norm(t))
        if bolds and len(bolds) == len(runs):
            txt = _norm(" ".join(t for _, t, _, _ in sorted(runs)))
            if max(s for *_, s in runs) > 13:
                secciones.add(txt)
            else:
                bold12.add(txt)
    return bold12, secciones


def _reflow(lineas: list[str]) -> str:
    """Une líneas envueltas en párrafos legibles. Corta línea nueva ante
    enumeraciones ("1.", "- ", "PRIMERO.-") para conservar la estructura."""
    out: list[str] = []
    for ln in lineas:
        nueva = bool(re.match(r"^(\d+\.\s|[-•]\s|(PRIMERO|SEGUNDO|TERCERO|CUARTO|"
                              r"QUINTO|SEXTO|SÉPTIMO|OCTAVO|NOVENO|DÉCIMO)\b)", ln))
        if out and not nueva:
            out[-1] = out[-1] + " " + ln
        else:
            out.append(ln)
    return "\n".join(out).strip()


def extraer_reporte(pdf: "str | bytes") -> dict:
    """Parsea un Reporte Informativo (path o bytes) → dict estructurado.

    Nunca lanza por contenido inesperado dentro del PDF (líneas raras caen a
    cuerpo del item abierto o se descartan si no hay contexto); sí propaga
    errores de lectura del PDF en sí (archivo corrupto → el caller decide).
    """
    reader = PdfReader(io.BytesIO(pdf) if isinstance(pdf, bytes) else pdf)

    fecha = None
    items: list[dict] = []
    seccion = categoria = entidad = None
    cuerpo: list[str] = []          # líneas del item abierto
    entidad_pend: list[str] = []    # header de entidad multilínea en armado

    def cerrar_item():
        nonlocal cuerpo
        texto = _reflow(cuerpo)
        cuerpo = []
        if not texto or seccion is None:
            return
        items.append({
            "seccion": seccion,
            "categoria": categoria or "",
            "entidad": entidad or "",
            "texto": texto,
            "tags": clasificar_tags(texto, seccion),
        })

    for page in reader.pages:
        bold12, secciones_pg = _lineas_bold(page)
        plano = page.extract_text() or ""
        for cruda in plano.split("\n"):
            ln = _norm(cruda)
            if not ln:
                continue
            # Boilerplate/footer de página
            if any(ln.startswith(b) for b in _BOILERPLATE) or _RE_FOOTER.match(ln):
                continue
            if ln == "Fecha:":
                continue
            m = _RE_FECHA.match(ln)
            if m and fecha is None:
                fecha = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                continue

            # Sección (bold >13pt, validada contra vocabulario)
            if ln in SECCIONES and (ln in secciones_pg or ln in bold12):
                cerrar_item()
                seccion, categoria, entidad = ln, None, None
                entidad_pend = []
                continue

            es_bold = ln in bold12

            # Categoría (vocabulario fijo + bold)
            if es_bold and ln in CATEGORIAS:
                cerrar_item()
                categoria, entidad = ln, None
                entidad_pend = []
                continue

            # Header de entidad / anti-tabla (ver docstring del módulo)
            if es_bold:
                en_calificadoras = categoria in _CATEGORIAS_CALIFICADORAS
                if _RE_TRAMITE.match(ln):
                    cerrar_item()
                    entidad = ln
                    entidad_pend = []
                    continue
                if en_calificadoras:
                    if _ES_CALIFICADORA.search(ln) and not cuerpo:
                        # nombre de calificadora solo corta si no hay tabla
                        # abierta (dentro de tabla, "Pacific…" es celda)
                        cerrar_item()
                        entidad = ln
                        continue
                    if _ES_CALIFICADORA.search(ln) and len(ln) < 60 and \
                            not any("Comité" in c for c in cuerpo[-3:]):
                        cerrar_item()
                        entidad = ln
                        continue
                    cuerpo.append(ln)  # celda de tabla de ratings
                    continue
                if _ES_ENTIDAD.search(ln) and not _RE_ITEM_START.match(ln):
                    # Puede venir envuelta en 2-3 líneas bold consecutivas;
                    # acumulamos y cerramos al primer no-bold.
                    if entidad_pend:
                        entidad_pend.append(ln)
                    else:
                        cerrar_item()
                        entidad_pend = [ln]
                    continue
                if entidad_pend:
                    entidad_pend.append(ln)
                    continue
                if cuerpo:
                    cuerpo.append(ln)  # bold decorativo dentro del item (Ver Adjunto, headers de tabla)
                continue

            # No-bold: si había entidad multilínea en armado, se sella acá.
            if entidad_pend:
                entidad = _norm(" ".join(entidad_pend))
                entidad_pend = []

            if _RE_ITEM_START.match(ln):
                cerrar_item()
                cuerpo.append(ln)
            elif cuerpo:
                cuerpo.append(ln)
            elif seccion is not None:
                cuerpo.append(ln)  # item sin arranque canónico (tablas, adjuntos)

    if entidad_pend:  # entidad colgada al final (sin cuerpo) — descartar
        entidad_pend = []
    cerrar_item()

    return {"fecha": fecha, "items": items}
