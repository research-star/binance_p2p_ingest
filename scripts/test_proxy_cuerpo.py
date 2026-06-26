#!/usr/bin/env python3
"""test_proxy_cuerpo.py — Cableado del proxy residencial opt-in en scrape_cuerpo.

Determinista, SIN red y SIN API: monkeypatchea los clientes HTTP de scraper.py para
inspeccionar los kwargs de cada get() y el output. Cubre:

  - GUARD DE REGRESIÓN: portal NO-flagged (usar_proxy=False) → curl_cffi/cloudscraper
    se llaman SIN el kwarg `proxies` (call byte-idéntico a hoy).
  - WIRING: usar_proxy=True + PROXY_URL en el entorno → `proxies={http,https}` se pasa.
  - FAIL-SAFE: usar_proxy=True SIN PROXY_URL → directo (sin `proxies`); 403 en toda la
    cadena → ("","") sin crash.
  - El flag `proxy_cuerpo` está en El Deber y AUSENTE en el resto (opt-in default OFF).

Uso: python scripts/test_proxy_cuerpo.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from noticias_ingest import scraper

# HTML de artículo con og:image en el <head> (parse real de _og_image vía BeautifulSoup).
ART_HTML = (
    "<html><head>"
    "<meta property='og:image' content='https://img.eldeber.com.bo/foto.jpg'>"
    "</head><body><article><p>" + ("cuerpo real del artículo. " * 40) +
    "</p></article></body></html>"
)
OG_ESPERADO = "https://img.eldeber.com.bo/foto.jpg"
CUERPO_STUB = "Cuerpo extraído por trafilatura (stub determinista de 60+ chars)."


class _Resp:
    def __init__(self, status, text):
        self.status_code = status
        self.text = text


class _Scraper:
    """Stub de cloudscraper.create_scraper() — registra kwargs de .get()."""
    def __init__(self, sink, resp):
        self._sink = sink
        self._resp = resp

    def get(self, url, **kw):
        self._sink.append(("cloudscraper", kw))
        return self._resp


def run() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    errores = []

    # ── Estructura de FUENTES: opt-in default OFF ────────────────────────────
    eldeber = next((f for f in scraper.FUENTES if f["portal"] == "El Deber"), None)
    if not eldeber or eldeber.get("proxy_cuerpo") is not True:
        errores.append("El Deber debería tener proxy_cuerpo=True")
    flagged = [f["portal"] for f in scraper.FUENTES if f.get("proxy_cuerpo")]
    if flagged != ["El Deber"]:
        errores.append(f"solo El Deber debería estar flagged (got {flagged})")

    # ── Harness: monkeypatch de clientes + trafilatura.extract ───────────────
    orig_curl = scraper.curl_requests
    orig_traf_extract = scraper.trafilatura.extract
    orig_cs = getattr(scraper, "cloudscraper", None)
    orig_fetch = scraper.trafilatura.fetch_url
    scraper.trafilatura.extract = lambda *a, **k: CUERPO_STUB

    class _Curl:
        def __init__(self, sink, resp):
            self._sink, self._resp = sink, resp

        def get(self, url, **kw):
            self._sink.append(("curl_cffi", kw))
            return self._resp

    def correr(usar_proxy, resp_status=200, cs_status=200, fetch_html=None):
        """Corre scrape_cuerpo con curl_cffi/cloudscraper mockeados; devuelve
        (resultado, llamadas) donde llamadas=[(cliente, kwargs), ...]."""
        sink = []
        scraper.curl_requests = _Curl(sink, _Resp(resp_status, ART_HTML))
        scraper.trafilatura.fetch_url = lambda *a, **k: fetch_html
        if orig_cs is not None:
            scraper.cloudscraper = type("M", (), {
                "create_scraper": staticmethod(lambda *a, **k: _Scraper(sink, _Resp(cs_status, ART_HTML)))})
        res = scraper.scrape_cuerpo("https://eldeber.com.bo/pais/x_1", usar_proxy=usar_proxy)
        return res, sink

    try:
        # (A) GUARD DE REGRESIÓN: sin flag → SIN kwarg proxies (byte-idéntico).
        os.environ["PROXY_URL"] = "http://u:p@gw.example:823"  # presente pero usar_proxy=False
        (cuerpo, og), llamadas = correr(usar_proxy=False)
        if any("proxies" in kw for _, kw in llamadas):
            errores.append(f"GUARD: portal no-flagged no debe pasar proxies (llamadas={llamadas})")
        if cuerpo != CUERPO_STUB or og != OG_ESPERADO:
            errores.append(f"GUARD: output inesperado (cuerpo={cuerpo!r}, og={og!r})")

        # (B) WIRING: flag + PROXY_URL → proxies={http,https} en el get de curl_cffi.
        os.environ["PROXY_URL"] = "http://u:p@gw.example:823"
        (cuerpo, og), llamadas = correr(usar_proxy=True)
        curl_calls = [kw for c, kw in llamadas if c == "curl_cffi"]
        if not curl_calls or curl_calls[0].get("proxies") != {
                "http": "http://u:p@gw.example:823", "https": "http://u:p@gw.example:823"}:
            errores.append(f"WIRING: curl_cffi debió recibir proxies (got {curl_calls})")
        if cuerpo != CUERPO_STUB or og != OG_ESPERADO:
            errores.append(f"WIRING: output inesperado (cuerpo={cuerpo!r}, og={og!r})")

        # (C1) FAIL-SAFE: flag pero PROXY_URL ausente → directo (sin proxies).
        os.environ.pop("PROXY_URL", None)
        (cuerpo, og), llamadas = correr(usar_proxy=True)
        if any("proxies" in kw for _, kw in llamadas):
            errores.append(f"FAIL-SAFE: sin PROXY_URL no debe pasar proxies (llamadas={llamadas})")
        if cuerpo != CUERPO_STUB:
            errores.append(f"FAIL-SAFE: con 200 directo debería extraer cuerpo (got {cuerpo!r})")

        # (C2) FAIL-SAFE no-crash: 403 en toda la cadena (curl 403, fetch None,
        # cloudscraper 403) → ("","") sin excepción.
        os.environ.pop("PROXY_URL", None)
        (cuerpo, og), llamadas = correr(usar_proxy=True, resp_status=403, cs_status=403, fetch_html=None)
        if (cuerpo, og) != ("", ""):
            errores.append(f"FAIL-SAFE: 403 en cadena debería dar ('','') (got {(cuerpo, og)!r})")

    finally:
        scraper.curl_requests = orig_curl
        scraper.trafilatura.extract = orig_traf_extract
        scraper.trafilatura.fetch_url = orig_fetch
        if orig_cs is not None:
            scraper.cloudscraper = orig_cs
        os.environ.pop("PROXY_URL", None)

    if errores:
        print("FAIL test_proxy_cuerpo:")
        for e in errores:
            print("  -", e)
        return 1
    print("OK test_proxy_cuerpo: proxy_cuerpo opt-in solo El Deber; GUARD no-flagged sin "
          "kwarg proxies (call idéntico); WIRING pasa proxies con PROXY_URL; FAIL-SAFE "
          "sin PROXY_URL cae a directo y 403-en-cadena da ('','') sin crash.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
