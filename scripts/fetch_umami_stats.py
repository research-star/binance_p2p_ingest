#!/usr/bin/env python3
"""
fetch_umami_stats.py — Fetch unique visitors counts from Umami Cloud API.

Devuelve {"visits_today", "visits_month", "fetched_at"} para alimentar el
header del dashboard (Visitas hoy / Visitas mes).

- "Hoy" y "mes" se calculan en zona horaria America/La_Paz (UTC-4, sin DST en
  Bolivia). "Mes" = del día 1 del mes calendario actual a "ahora".
- Usa `visitors` (unique visitors), no `pageviews`.
- Falla graceful: en error de red/API/env vars, devuelve None en el campo y
  loguea un warning a stderr. Nunca levanta.
- 2 calls a la API (una por período). Timeout 10s, 1 retry con backoff 2s.

CLI manual (cuando estén credenciales en .env):
    UMAMI_API_KEY=... UMAMI_WEBSITE_ID=... UMAMI_HOST=https://api.umami.is \
        python -m scripts.fetch_umami_stats
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Bolivia no observa DST. UTC-4 fijo.
BOLIVIA_TZ = timezone(timedelta(hours=-4))

# Umami Cloud usa `x-umami-api-key`. Self-hosted con login usa `Authorization:
# Bearer`. Las credenciales que Diego está creando son de Cloud, así que el
# default es el header de Cloud. Override vía env UMAMI_AUTH_HEADER si hace
# falta (ej. self-host).
DEFAULT_AUTH_HEADER = "x-umami-api-key"

# Path prefix del API. Umami Cloud expone /v1/websites/...; self-hosted expone
# /api/websites/.... Validado empíricamente contra api.umami.is el 2026-05-18
# (/api → 405, /v1 → 200). Override vía env UMAMI_API_PATH_PREFIX.
DEFAULT_API_PATH_PREFIX = "/v1"

TIMEOUT_S = 10
RETRY_BACKOFF_S = 2


def _emit(msg: str) -> None:
    print(f"[umami] {msg}", file=sys.stderr, flush=True)


def _period_bounds_ms(now_utc: datetime | None = None) -> tuple[tuple[int, int], tuple[int, int]]:
    """Devuelve ((today_start_ms, today_end_ms), (month_start_ms, month_end_ms))
    en epoch ms, calculando los bordes en horario de Bolivia."""
    now_utc = now_utc or datetime.now(timezone.utc)
    now_bo = now_utc.astimezone(BOLIVIA_TZ)
    today_start_bo = now_bo.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start_bo = today_start_bo.replace(day=1)
    end_ms = int(now_utc.timestamp() * 1000)
    return (
        (int(today_start_bo.timestamp() * 1000), end_ms),
        (int(month_start_bo.timestamp() * 1000), end_ms),
    )


def _request_stats(host: str, website_id: str, api_key: str,
                   auth_header: str, path_prefix: str,
                   start_ms: int, end_ms: int) -> dict:
    qs = urlencode({"startAt": start_ms, "endAt": end_ms})
    prefix = path_prefix if path_prefix.startswith("/") else "/" + path_prefix
    url = f"{host.rstrip('/')}{prefix.rstrip('/')}/websites/{website_id}/stats?{qs}"
    req = Request(url, headers={
        auth_header: api_key,
        "Accept": "application/json",
        "User-Agent": "finanzasbo-dashboard/1.0",
    })
    with urlopen(req, timeout=TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8"))


def _request_with_retry(host: str, website_id: str, api_key: str,
                        auth_header: str, path_prefix: str,
                        start_ms: int, end_ms: int) -> dict | None:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            return _request_stats(host, website_id, api_key, auth_header,
                                  path_prefix, start_ms, end_ms)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as e:
            last_err = e
            if attempt == 0:
                time.sleep(RETRY_BACKOFF_S)
    _emit(f"WARN fetch failed start={start_ms} end={end_ms} err={last_err!r}")
    return None


def _extract_visitors(payload: dict | None) -> int | None:
    """Umami Cloud devuelve {"visitors": N, ...} plano. Algunas versiones
    self-hosted v2+ devuelven {"visitors": {"value": N, "prev": N}, ...}.
    Soportar ambos."""
    if not payload:
        return None
    v = payload.get("visitors")
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def fetch_visits(api_key: str, website_id: str, host: str,
                 tz: str = "America/La_Paz",
                 auth_header: str = DEFAULT_AUTH_HEADER,
                 path_prefix: str = DEFAULT_API_PATH_PREFIX) -> dict:
    """Fetch unique visitors para 'hoy' y 'mes' desde Umami.

    Args:
        api_key: API key de Umami Cloud (o token Bearer self-host).
        website_id: UUID del website en Umami.
        host: base URL del API (Cloud: https://api.umami.is; self-host: tu dominio).
        tz: zona horaria para definir "hoy"/"mes". Solo America/La_Paz soportada.
        auth_header: nombre del header de auth. Default 'x-umami-api-key' (Cloud).

    Returns:
        {"visits_today": int|None, "visits_month": int|None, "fetched_at": iso8601}.
        Campos individuales pueden ser None si falló esa llamada. Nunca levanta.
    """
    if tz != "America/La_Paz":
        _emit(f"WARN tz='{tz}' ignorado, usando America/La_Paz")

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"visits_today": None, "visits_month": None, "fetched_at": fetched_at}

    if not (api_key and website_id and host):
        _emit("WARN missing credentials (api_key/website_id/host); returning Nones")
        return out

    (today_start, today_end), (month_start, month_end) = _period_bounds_ms()

    today_resp = _request_with_retry(host, website_id, api_key, auth_header,
                                     path_prefix, today_start, today_end)
    out["visits_today"] = _extract_visitors(today_resp)

    month_resp = _request_with_retry(host, website_id, api_key, auth_header,
                                     path_prefix, month_start, month_end)
    out["visits_month"] = _extract_visitors(month_resp)

    return out


def main() -> int:
    try:
        from dotenv import load_dotenv
        # .env vive en la raíz del proyecto (parent del directorio scripts/).
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except ImportError:
        pass

    api_key = os.environ.get("UMAMI_API_KEY", "").strip()
    website_id = os.environ.get("UMAMI_WEBSITE_ID", "").strip()
    host = os.environ.get("UMAMI_HOST", "").strip()
    auth_header = os.environ.get("UMAMI_AUTH_HEADER", DEFAULT_AUTH_HEADER).strip()
    path_prefix = os.environ.get("UMAMI_API_PATH_PREFIX", DEFAULT_API_PATH_PREFIX).strip()

    result = fetch_visits(api_key, website_id, host,
                          auth_header=auth_header, path_prefix=path_prefix)
    print(json.dumps(result, indent=2))
    return 0 if (result["visits_today"] is not None
                 and result["visits_month"] is not None) else 1


if __name__ == "__main__":
    sys.exit(main())
