"""
transform.py — Candidato del scraper → nota con el schema de la tab Noticias.

Schema por nota (contrato con template.html, HANDOFF.md § Frontend tab
Noticias): {id, source, category, date:'YYYY-MM-DD', time:'HH:MM', title,
summary, detail, topics:[..], impact:'alto|medio|bajo', sourceNote}.
Se agrega `url` (link al artículo original) para que el frontend pueda
enlazar la nota — campo extra, no rompe el schema.

date/time son la fecha/hora de la CORRIDA en hora Bolivia (UTC-4 fijo,
sin DST): el pipeline corre 1 vez al día, todas las notas comparten
timestamp y eso es honesto (no inventamos horas de publicación).
"""

import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from .scraper import hash_link

BOLIVIA_TZ = timezone(timedelta(hours=-4))  # Bolivia no observa DST

# Slugs estables por portal — keys de NOTICIAS_PORTALS en template.html.
# Cubre los 13 portales de FUENTES; un portal nuevo sin slug caería al
# fallback _slugify (y al fallback visual del frontend).
PORTAL_SLUGS = {
    "El Deber": "eldeber",
    "Correo del Sur": "correosur",
    "Unitel": "unitel",
    "La Razón": "larazon",
    "Bloomberg Línea": "bloomberg",
    "Eju!": "eju",
    "El Día": "eldia",
    "Brújula Digital": "brujula",
    "Noticias Fides": "fides",
    "Erbol": "erbol",
    "Urgente.bo": "urgente",
    "Opinión": "opinion",
    "Los Tiempos": "lostiempos",
}

# 11 temas de boletines (+ fallback "General") → 6 categorías del frontend.
# "mundo" queda sin tema fuente: el scraper solo cubre prensa boliviana y
# el gate TERMINOS_BOLIVIA descarta lo internacional sin ángulo local.
TEMA_CATEGORIA = {
    "Combustibles / YPFB": "hidrocarburos",
    "Tipo de cambio / Dólar": "economia",
    "Litio / Minería": "mineria",
    "Agropecuario / Soya": "agro",
    "Deuda / Finanzas": "economia",
    "Inflación / Precios": "economia",
    "Exportaciones / Comercio": "economia",
    "Inversión / Infraestructura": "economia",
    "Elecciones / Política económica": "politica",
    "Bloqueos / Conflictos": "politica",
    "EMAPA / Alimentos": "agro",
    "General": "economia",
}

SUMMARY_MAX = 200
DETAIL_MAX = 400


def _slugify(portal: str) -> str:
    s = portal.lower()
    s = re.sub(r"[áàä]", "a", s)
    s = re.sub(r"[éèë]", "e", s)
    s = re.sub(r"[íìï]", "i", s)
    s = re.sub(r"[óòö]", "o", s)
    s = re.sub(r"[úùü]", "u", s)
    return re.sub(r"[^a-z0-9]", "", s) or "desconocido"


def _truncar(texto: str, maximo: int) -> str:
    """Trunca en límite de palabra con elipsis. Nunca corta a mitad de palabra."""
    texto = (texto or "").strip()
    if len(texto) <= maximo:
        return texto
    corte = texto.rfind(" ", 0, maximo)
    if corte < maximo // 2:
        corte = maximo
    return texto[:corte].rstrip(" ,;:.") + "…"


def impact_de_puntaje(puntaje: float) -> str:
    """Bandas cerradas por el brief: >=8 alto · 7-7.99 medio · resto bajo.
    (El piso efectivo es 6.7: el corte de selección de ingest_noticias.py.)"""
    if puntaje >= 8.0:
        return "alto"
    if puntaje >= 7.0:
        return "medio"
    return "bajo"


def categoria_de_tema(tema: str) -> str:
    return TEMA_CATEGORIA.get(tema, "economia")


def build_nota(cand: dict, ahora_utc: datetime | None = None) -> dict:
    """Candidato del scraper → fila/nota con el schema del frontend.

    summary: descripcion del RSS; si no hay (portales solo-scrape), extracto
    del cuerpo. detail: extracto del cuerpo (~400 chars, NUNCA el cuerpo
    completo: finanzasbo.com es un sitio público y el contenido es de los
    portales); si no hubo cuerpo, cae a la descripcion completa.
    """
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
    ahora_bo = ahora_utc.astimezone(BOLIVIA_TZ)

    portal = cand["portal"]
    tema = cand.get("tema") or ""
    descripcion = (cand.get("descripcion") or "").strip()
    cuerpo = (cand.get("cuerpo") or "").strip()

    summary = _truncar(descripcion, SUMMARY_MAX) if descripcion else _truncar(cuerpo, SUMMARY_MAX)
    detail = _truncar(cuerpo, DETAIL_MAX) if cuerpo else descripcion
    dominio = urlparse(cand["link"]).netloc.replace("www.", "")

    return {
        "id": hash_link(cand["link"]),
        "date": ahora_bo.strftime("%Y-%m-%d"),
        "time": ahora_bo.strftime("%H:%M"),
        "source": PORTAL_SLUGS.get(portal, _slugify(portal)),
        "category": categoria_de_tema(tema),
        "title": cand["titulo"].strip(),
        "summary": summary,
        "detail": detail,
        "topics": [tema] if tema and tema != "General" else [],
        "impact": impact_de_puntaje(cand["puntaje"]),
        "sourceNote": f"{portal} · {dominio}",
        "url": cand["link"],
        # Campos de auditoría (van a la DB, no al payload del frontend)
        "portal": portal,
        "tema": tema,
        "puntaje": cand["puntaje"],
        "score_crudo": cand.get("score_crudo"),
        "score_ajustado": cand.get("score_ajustado"),
        "created_at_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
