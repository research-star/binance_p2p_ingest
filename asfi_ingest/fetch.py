"""fetch.py — Descarga del listado y PDFs de Hechos Relevantes ASFI (appweb2).

appweb2.asfi.gob.bo GEO-BLOQUEA IPs no bolivianas a nivel de red (drop de
conexión, validado 2026-07-05: directo desde Hetzner = timeout; proxy
residencial DataImpulse con exit por defecto = 502 del gateway; con sufijo
`__cr.bo` en el usuario = 200 vía exit La Paz/Cobija). Por eso TODA request
de este módulo sale por el proxy con geo-targeting Bolivia, derivado del
mismo PROXY_URL del .env que ya usa el scraper de noticias (PR #146).

Sin PROXY_URL en el entorno, listar/descargar devuelven None/[] (fail-safe,
no crash) — el wrapper de cron loguea y sale limpio.

Reintentos: el pool residencial rota exit por request y un intento puede dar
502/timeout aunque el siguiente funcione — validado en la sesión de calibración.
"""
from __future__ import annotations

import logging
import os
import re
import time

import requests

log = logging.getLogger(__name__)

BASE = "https://appweb2.asfi.gob.bo/PaginasPublicas2/VistaHechosRelevantes/"
LISTA_URL = BASE + "ListaPublicacionHechoRelevante.aspx?Gestion={gestion}"
VISOR_URL = BASE + "VisorDocumentos.aspx?variable1={guid}"
REFERER = "https://www.asfi.gob.bo/la/hechos-relevantes-{gestion}"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

TIMEOUT_S = 90
REINTENTOS = 3
PAUSA_S = 3          # entre reintentos
PAUSA_DESCARGA_S = 2  # entre PDFs (rate-limit cortés)

# <a class="linkpublicacion" ... href="VisorDocumentos.aspx?variable1=GUID">Título</a>
_RE_LINK = re.compile(
    r'VisorDocumentos\.aspx\?variable1=([0-9a-f-]{36})"[^>]*>([^<]+)</a>')


def proxy_bo() -> str | None:
    """PROXY_URL del entorno con geo-targeting Bolivia (sufijo DataImpulse
    `__cr.bo` en el usuario). None si no hay proxy configurado."""
    raw = os.environ.get("PROXY_URL", "").strip()
    if not raw:
        return None
    return re.sub(r"^(https?)://([^:]+):", r"\1://\2__cr.bo:", raw, count=1)


def _get(url: str, referer: str, proxy: str) -> requests.Response | None:
    proxies = {"http": proxy, "https": proxy}
    for intento in range(1, REINTENTOS + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT_S, proxies=proxies,
                             headers={"User-Agent": UA, "Referer": referer})
            if r.status_code == 200 and r.content:
                return r
            log.warning(f"[asfi_fetch] intento {intento}: HTTP {r.status_code} {url[:90]}")
        except requests.RequestException as e:
            log.warning(f"[asfi_fetch] intento {intento}: {type(e).__name__}: {str(e)[:120]}")
        if intento < REINTENTOS:
            time.sleep(PAUSA_S)
    return None


def listar_reportes(gestion: int) -> list[tuple[str, str]]:
    """[(guid, titulo)] del listado de la gestión, en el orden de la página
    (más reciente primero). Lista vacía si no hay proxy o el fetch falla."""
    proxy = proxy_bo()
    if not proxy:
        log.warning("[asfi_fetch] sin PROXY_URL — no puedo llegar a appweb2 (geo-block)")
        return []
    r = _get(LISTA_URL.format(gestion=gestion),
             REFERER.format(gestion=gestion), proxy)
    if r is None:
        return []
    vistos, out = set(), []
    for guid, titulo in _RE_LINK.findall(r.text):
        if guid not in vistos:
            vistos.add(guid)
            out.append((guid, " ".join(titulo.split())))
    return out


def descargar_pdf(guid: str, gestion: int) -> bytes | None:
    """Bytes del PDF del visor, o None. Valida magic %PDF (el visor devuelve
    HTML de error con 200 en algunos fallos)."""
    proxy = proxy_bo()
    if not proxy:
        return None
    r = _get(VISOR_URL.format(guid=guid),
             REFERER.format(gestion=gestion), proxy)
    if r is None or not r.content.startswith(b"%PDF"):
        if r is not None:
            log.warning(f"[asfi_fetch] {guid}: respuesta no-PDF "
                        f"({r.headers.get('Content-Type', '?')}, {len(r.content)}B)")
        return None
    return r.content
