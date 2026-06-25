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
    # Fuentes nuevas (calibración 2026-06-21; pendiente validar yield en VPS).
    "La Patria": "lapatria",
    "El Mundo": "elmundo",
    "BCB": "bcb",
    "INE": "ine",
    "MEFP": "mefp",
    "ASFI": "asfi",
    "Aduana": "aduana",
    "CAINCO": "cainco",
    "IBCE": "ibce",
    "CEPB": "cepb",
    "CNI": "cni",
}

# 11 temas (+ fallback "General") → category editorial de 5 cubos:
# {economia, finanzas, politica, internacional, otros}.
#   · Economía  = economía real/productiva (energía, agro, minería, comercio,
#                 infraestructura, alimentos, precios).
#   · Finanzas  = dólar/tipo de cambio, banca, deuda, riesgo país.
#   · Política  = electoral + conflicto social/bloqueos (afecta la actividad).
#   · Internacional = carril Latam (lo marca el campo `carril`, no este mapa).
#   · Otros     = nota boliviana relevante SIN tema de negocios (diplomacia,
#                 seguridad, etc.). NO se descarta: entra como relleno por
#                 relevancia cuando faltan noticias de negocios. Es el destino
#                 de "General" (calibración 2026-06-21: matar General tiraba
#                 ~60-70% de noticia relevante mal rotulada — ver evaluar()).
# El tema fino (oro, dólar, YPFB…) y la confianza viven en `tema`/`tema_hits`/
# `topics`, no en category. El carril Latam se marca con carril='latam'
# (build_nota_latam) y su category es 'internacional'.
TEMA_CATEGORIA = {
    "Combustibles / YPFB": "economia",
    "Tipo de cambio / Dólar": "finanzas",
    "Litio / Minería": "economia",
    "Agropecuario / Soya": "economia",
    "Deuda / Finanzas": "finanzas",
    "Inflación / Precios": "economia",
    "Exportaciones / Comercio": "economia",
    "Inversión / Infraestructura": "economia",
    "Elecciones / Política económica": "politica",
    "Bloqueos / Conflictos": "politica",
    "EMAPA / Alimentos": "economia",
    "General": "otros",
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


def _truncar(texto: str, maximo: int, elipsis: bool = True) -> str:
    """Trunca en límite de palabra. Nunca corta a mitad de palabra.
    elipsis=True agrega '…' (detail); elipsis=False corta limpio (summary: el
    slot del card no debe terminar en '…')."""
    texto = (texto or "").strip()
    if len(texto) <= maximo:
        return texto
    corte = texto.rfind(" ", 0, maximo)
    if corte < maximo // 2:
        corte = maximo
    return texto[:corte].rstrip(" ,;:.") + ("…" if elipsis else "")


# Abreviaturas (es-BO) que llevan punto pero NO terminan oración — evitan cortar
# en "EE.UU.", "$us.", "Dr.", "art.", etc. al armar el resumen extractivo.
_ABREV = {
    "ee", "uu", "art", "núm", "num", "no", "nro", "etc", "dr", "dra", "sr", "sra",
    "srta", "lic", "ing", "arq", "av", "ud", "uds", "pág", "pag", "vol", "cap",
    "us", "bs", "aprox", "máx", "mín", "gral", "tel", "ref", "depto", "ej",
}
# Candidato a fin de oración: signo . ! ? + espacio + arranque de oración nueva
# (mayúscula/acento, dígito, o apertura de comillas/interrogación/exclamación).
_FIN_ORACION = re.compile(r'([.!?])\s+(?=[«"“¿¡A-ZÁÉÍÓÚÑ0-9])')


def _oraciones(texto: str) -> list:
    """Parte texto en oraciones (heurística stdlib). Tolera abreviaturas e
    iniciales comunes es-BO; no es perfecta, pero no corta en 'EE.UU.'/'$us.'."""
    texto = (texto or "").strip()
    if not texto:
        return []
    out, ini = [], 0
    for m in _FIN_ORACION.finditer(texto):
        izq = texto[ini:m.start()].strip()
        ult = re.split(r"[\s(]+", izq)[-1].lower().rstrip(".") if izq else ""
        # punto tras abreviatura o inicial de ≤2 letras → no es fin de oración
        if m.group(1) == "." and (ult in _ABREV or (len(ult) <= 2 and ult.isalpha())):
            continue
        out.append(texto[ini:m.start() + 1].strip())
        ini = m.end()
    resto = texto[ini:].strip()
    if resto:
        out.append(resto)
    return [o for o in out if o]


def _resumen_extractivo(texto: str, maximo: int = SUMMARY_MAX) -> str:
    """Resumen = 1-2 oraciones completas que entren en `maximo` chars (mejora
    estética sobre el corte duro a 200; sin IA, calibración 2026-06-21). Si el
    texto ya entra, se devuelve tal cual; si ni la primera oración entra, cae a
    _truncar con corte LIMPIO (sin elipsis: el slot del card no termina en '…',
    calibración 2026-06-25)."""
    texto = (texto or "").strip()
    if not texto or len(texto) <= maximo:
        return texto
    acc = ""
    for o in _oraciones(texto)[:2]:  # como mucho 2 oraciones
        cand = (acc + " " + o).strip() if acc else o
        if len(cand) > maximo:
            break
        acc = cand
    return acc if acc else _truncar(texto, maximo, elipsis=False)


def impact_de_puntaje(puntaje: float) -> str:
    """Bandas cerradas por el brief: >=8 alto · 7-7.99 medio · resto bajo.
    (El piso efectivo es 6.7: el corte de selección de ingest_noticias.py.)"""
    if puntaje >= 8.0:
        return "alto"
    if puntaje >= 7.0:
        return "medio"
    return "bajo"


def categoria_de_tema(tema: str) -> str:
    return TEMA_CATEGORIA.get(tema, "otros")


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

    summary = _resumen_extractivo(descripcion or cuerpo, SUMMARY_MAX)
    detail = _truncar(cuerpo, DETAIL_MAX) if cuerpo else descripcion
    dominio = urlparse(cand["link"]).netloc.replace("www.", "")

    return {
        "id": hash_link(cand["link"]),
        "date": ahora_bo.strftime("%Y-%m-%d"),
        "time": ahora_bo.strftime("%H:%M"),
        "source": PORTAL_SLUGS.get(portal, _slugify(portal)),
        # Opinión (WS4 funnel-v2) tiene categoría propia en el data layer; si no, la
        # category sale del tema. (El frontend hoy deriva el rótulo del `tema`, no de
        # este campo: 'opinion' viaja a la DB/payload pero es inerte en la UI hasta el
        # ticket visual — verificado SAFE, no rompe ni esconde nada.)
        "category": "opinion" if cand.get("es_opinion") else categoria_de_tema(tema),
        "carril": "bolivia",   # carril del feed (frontend parte Bolivia/Latam por acá, no por category)
        "title": cand["titulo"].strip(),
        "summary": summary,
        # Origen del summary: arranca 'extractivo' (lo de arriba); resumen_ia.aplicar
        # lo sube a 'ia' si la IA resume con éxito. El frontend marca con asterisco
        # todo lo que NO sea 'ia'. (Col summary_origen, migración 0007.)
        "summary_origen": "extractivo",
        "detail": detail,
        "topics": [tema] if tema and tema != "General" else [],
        "impact": impact_de_puntaje(cand["puntaje"]),
        "sourceNote": f"{portal} · {dominio}",
        "url": cand["link"],
        # og:image hotlinkeable de la nota (carril BO, FASE 2a); None si el portal
        # no lo expone o no bajó HTML (El Deber). NULL en la columna image_url.
        "image_url": cand.get("image_url") or None,
        # Campos de auditoría (van a la DB, no al payload del frontend)
        "portal": portal,
        "tema": tema,
        # Confianza del tema (clasificación v1) + entidades; al payload para el
        # matching de galería futuro (gate sugerido: imagen específica si confianza>=10).
        "tema_hits": cand.get("tema_hits"),
        "entidades": cand.get("entidades") or [],
        "puntaje": cand["puntaje"],
        "score_crudo": cand.get("score_crudo"),
        "score_ajustado": cand.get("score_ajustado"),
        "created_at_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_nota_latam(pub_utc: datetime, entry, ahora_utc: datetime | None = None) -> dict:
    """Entry RSS de Bloomberg Línea (sección Latinoamérica) → nota.

    Sin scoring: impact='medio' fijo (v1) y puntaje=0.0 como sentinela del
    carril (la columna es NOT NULL; 0 nunca colisiona con el carril Bolivia,
    cuyo piso editorial es 6.7). date/time = pubDate REAL convertido a hora
    Bolivia — la UI hoy no muestra hora, pero se persiste igual.
    """
    from .scraper import limpiar_html  # import local para evitar ciclo

    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
    pub_bo = pub_utc.astimezone(BOLIVIA_TZ)

    descripcion = limpiar_html(getattr(entry, "summary", "") or "")
    contenido = ""
    cont = getattr(entry, "content", None)
    if cont:
        contenido = limpiar_html(cont[0].value or "")
        # Bloomberg embebe bloques "Ver más: <link relacionado>" dentro del
        # cuerpo; al aplanar el HTML quedan pegados al texto. Cortar ahí.
        contenido = contenido.split("Ver más:")[0].strip()

    link = entry.link
    guid = getattr(entry, "id", "") or link
    autor = (getattr(entry, "author", "") or "").strip()
    source_note = f"Bloomberg Línea · {autor}" if autor else "Bloomberg Línea · bloomberglinea.com"

    return {
        "id": hash_link(guid),
        "date": pub_bo.strftime("%Y-%m-%d"),
        "time": pub_bo.strftime("%H:%M"),
        "source": "bloomberg",
        "category": "internacional",   # carril Latam → category 'internacional'; el carril va aparte
        "carril": "latam",        # discriminador del carril Latam (antes era category=='latam')
        "title": (getattr(entry, "title", "") or "").strip(),
        "summary": _resumen_extractivo(descripcion, SUMMARY_MAX),
        "summary_origen": "extractivo",  # resumen_ia.aplicar lo sube a 'ia' en éxito (col 0007)
        "detail": _truncar(contenido, DETAIL_MAX) if contenido else descripcion,
        "topics": [],
        "impact": "medio",
        "sourceNote": source_note,
        "url": link,
        "portal": "Bloomberg Línea",
        "tema": "",
        # Latam no clasifica tema (sin scoring) ni se usa para galería (slot=bandera):
        # confianza 0 y entidades vacías, consistente con puntaje=0.0 sentinela.
        "tema_hits": 0,
        "entidades": [],
        "puntaje": 0.0,
        "score_crudo": None,
        "score_ajustado": None,
        "created_at_utc": ahora_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
