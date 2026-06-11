"""
latam.py — Carril Latam: sección Latinoamérica de Bloomberg Línea vía RSS.

SIN scoring y SIN filtro de contenido (decisión de Diego): el criterio
editorial de Bloomberg ES el filtro. Selección: ítems con pubDate en las
últimas 24 h, orden pubDate desc; el cupo diario (5) lo aplica
ingest_noticias.py con presupuesto INDEPENDIENTE del top-10 Bolivia.

Fuente primaria: el feed de la sección (URL del brief). Al momento del
desarrollo (2026-06-11) ese endpoint devuelve 500 — y las variantes
/category/latam/ y /category/latinoamérica/ devuelven shells válidos pero
vacíos — así que hay FALLBACK documentado: el feed raíz de outboundfeeds
(100 ítems) filtrado por path /latinoamerica/ en el link, que es la misma
taxonomía de sección de Bloomberg por otro camino. Si Bloomberg arregla el
feed de sección, la fuente primaria vuelve sola. No se toca /pf/api/v3/*
(bloqueado en robots.txt).
"""

import logging
import time
from datetime import datetime, timezone, timedelta

import feedparser
import requests

log = logging.getLogger(__name__)

FEED_SECCION = ("https://www.bloomberglinea.com/arc/outboundfeeds/rss/"
                "category/latinoamerica/?outputType=xml")
FEED_RAIZ = "https://www.bloomberglinea.com/arc/outboundfeeds/rss/?outputType=xml"
PATH_SECCION = "latinoamerica"

VENTANA_HORAS = 24
TIMEOUT_S = 20

# User-Agent de navegador realista (requisito del brief; Arc sirve los
# outboundfeeds sin auth pero conviene no parecer bot genérico).
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
}


def _fetch(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
        if r.status_code != 200:
            log.warning(f"  [latam] {url.split('?')[0]} -> HTTP {r.status_code}")
            return None
        return feedparser.parse(r.content)
    except Exception as e:
        log.warning(f"  [latam] fetch falló: {e}")
        return None


def _es_de_seccion(entry) -> bool:
    try:
        return entry.link.split("/")[3] == PATH_SECCION
    except (AttributeError, IndexError):
        return False


def fetch_entries_latam() -> list:
    """Entries de la sección Latinoamérica: feed de sección si responde con
    ítems; si no, feed raíz. En AMBOS casos se filtra por path
    /latinoamerica/ del link: verificado 2026-06-11, el feed de sección
    (cuando responde) mezcla ítems de /mercados/ y /linea-deportiva/ —
    el path es la taxonomía confiable. Lista vacía si todo falla (el
    caller decide la semántica de fallo del carril)."""
    # El fallback se decide sobre la lista YA FILTRADA: el feed de sección
    # puede responder 200 con ítems pero ninguno de la sección.
    feed = _fetch(FEED_SECCION)
    entries = [e for e in feed.entries if _es_de_seccion(e)] if feed else []
    if entries:
        log.info(f"  [latam] feed sección: {len(feed.entries)} ítems, "
                 f"{len(entries)} de /{PATH_SECCION}/")
        return entries

    log.info("  [latam] feed de sección sin ítems de la sección — fallback a feed raíz")
    feed = _fetch(FEED_RAIZ)
    if not feed:
        return []
    entries = [e for e in feed.entries if _es_de_seccion(e)]
    log.info(f"  [latam] feed raíz: {len(feed.entries)} ítems, "
             f"{len(entries)} de /{PATH_SECCION}/")
    return entries


def entries_ultimas_24h(entries: list, ahora_utc: datetime | None = None) -> list:
    """Filtra por pubDate dentro de la ventana y ordena pubDate desc.
    Ítems sin pubDate parseable se descartan (la fecha real es requisito
    del carril)."""
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
    corte = ahora_utc - timedelta(hours=VENTANA_HORAS)
    con_fecha = []
    for e in entries:
        pp = getattr(e, "published_parsed", None)
        if not pp:
            continue
        try:
            pub = datetime(*pp[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if pub >= corte:
            con_fecha.append((pub, e))
    con_fecha.sort(key=lambda t: t[0], reverse=True)
    return [(pub, e) for pub, e in con_fecha]
