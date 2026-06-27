#!/usr/bin/env python3
"""
umami_daily_export.py — Exporta la serie histórica DIARIA de visitantes únicos
desde Umami Cloud a CSV (y .xlsx si openpyxl está disponible).

Una fila por día, en zona America/La_Paz (UTC-4 fijo, Bolivia no observa DST):

    fecha,visitantes_unicos,visitas,pageviews
    2026-05-18,42,55,180
    2026-05-19,37,49,151
    ...

- "Visitante único" = campo `visitors` del endpoint /stats de Umami, consultado
  con los bordes [00:00, 24:00) de cada día en horario de Bolivia. Una llamada
  por día (el rango por defecto son ~40 días → ~40 llamadas, con 1 retry c/u).
- `visitas` = `visits` (sesiones) y `pageviews` = `pageviews` del mismo payload.
- Reusa los helpers de red de scripts.fetch_umami_stats (auth, retry, host).
- El CSV se escribe con BOM UTF-8 (utf-8-sig) para que Excel muestre bien los
  acentos al abrirlo directo.

Uso (en el VPS, con .env que tenga UMAMI_API_KEY / UMAMI_WEBSITE_ID / UMAMI_HOST):

    cd /opt/binance_p2p
    .venv/bin/python -m scripts.umami_daily_export
    .venv/bin/python -m scripts.umami_daily_export --desde 2026-05-18 --hasta 2026-06-27 --out visitas.csv

Defaults:
    --desde  2026-05-18  (día en que se desplegó el tracker de Umami)
    --hasta  hoy (Bolivia)
    --out    umami_visitas_diarias.csv

Credenciales (env vars o .env en la raíz del repo):
    UMAMI_API_KEY      API key de Umami Cloud (Settings → API keys). REQUERIDA.
    UMAMI_WEBSITE_ID   UUID del website. REQUERIDA. (la pública es bad7aa19-…)
    UMAMI_HOST         base del API. Cloud: https://api.umami.is . REQUERIDA.
    UMAMI_AUTH_HEADER  opcional (default x-umami-api-key, header de Cloud).
    UMAMI_API_PATH_PREFIX  opcional (default /v1).
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta

from scripts.fetch_umami_stats import (
    BOLIVIA_TZ,
    DEFAULT_API_PATH_PREFIX,
    DEFAULT_AUTH_HEADER,
    _emit,
    _request_with_retry,
)

TRACKER_LIVE_SINCE = date(2026, 5, 18)  # primer build de gh-pages con el tracker


def _day_bounds_ms(d: date) -> tuple[int, int]:
    """[00:00, 24:00) de `d` en horario de Bolivia, en epoch ms."""
    start = datetime(d.year, d.month, d.day, tzinfo=BOLIVIA_TZ)
    end = start + timedelta(days=1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _extract_int(payload: dict | None, key: str) -> int | None:
    """Umami Cloud devuelve {"visitors": N, ...} plano; algunas self-hosted v2+
    devuelven {"visitors": {"value": N, "prev": N}, ...}. Soportar ambos."""
    if not payload:
        return None
    v = payload.get(key)
    if isinstance(v, dict):
        v = v.get("value")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _daterange(desde: date, hasta: date):
    d = desde
    while d <= hasta:
        yield d
        d += timedelta(days=1)


def fetch_daily(api_key: str, website_id: str, host: str,
                desde: date, hasta: date,
                auth_header: str = DEFAULT_AUTH_HEADER,
                path_prefix: str = DEFAULT_API_PATH_PREFIX) -> list[dict]:
    """Devuelve [{'fecha','visitantes_unicos','visitas','pageviews'}] por día.
    Campos pueden ser None si esa llamada falló (queda visible, no se rellena)."""
    rows: list[dict] = []
    for d in _daterange(desde, hasta):
        start_ms, end_ms = _day_bounds_ms(d)
        payload = _request_with_retry(host, website_id, api_key, auth_header,
                                      path_prefix, start_ms, end_ms)
        rows.append({
            "fecha": d.isoformat(),
            "visitantes_unicos": _extract_int(payload, "visitors"),
            "visitas": _extract_int(payload, "visits"),
            "pageviews": _extract_int(payload, "pageviews"),
        })
        vu = rows[-1]["visitantes_unicos"]
        _emit(f"{d.isoformat()}  visitantes_unicos={vu if vu is not None else '—'}")
    return rows


def write_csv(rows: list[dict], path: str) -> None:
    cols = ["fecha", "visitantes_unicos", "visitas", "pageviews"]
    # utf-8-sig → BOM para que Excel muestre acentos al abrir el CSV directo.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r[c] is None else r[c]) for c in cols})


def write_xlsx(rows: list[dict], path: str) -> bool:
    """Escribe .xlsx si openpyxl está disponible. Devuelve True si lo hizo."""
    try:
        from openpyxl import Workbook
    except ImportError:
        return False
    cols = ["fecha", "visitantes_unicos", "visitas", "pageviews"]
    headers = ["Fecha", "Visitantes únicos", "Visitas", "Pageviews"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Visitas diarias"
    ws.append(headers)
    for r in rows:
        ws.append([r[c] for c in cols])
    wb.save(path)
    return True


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
    except ImportError:
        pass

    today_bo = datetime.now(BOLIVIA_TZ).date()
    p = argparse.ArgumentParser(description="Exporta visitas únicas por día desde Umami Cloud.")
    p.add_argument("--desde", type=_parse_date, default=TRACKER_LIVE_SINCE,
                   help="Fecha inicial YYYY-MM-DD (default: 2026-05-18, alta del tracker).")
    p.add_argument("--hasta", type=_parse_date, default=today_bo,
                   help="Fecha final YYYY-MM-DD inclusive (default: hoy en Bolivia).")
    p.add_argument("--out", default="umami_visitas_diarias.csv",
                   help="Ruta del CSV de salida (default: umami_visitas_diarias.csv).")
    args = p.parse_args()

    if args.desde > args.hasta:
        print(f"--desde ({args.desde}) es posterior a --hasta ({args.hasta}).", file=sys.stderr)
        return 2

    api_key = os.environ.get("UMAMI_API_KEY", "").strip()
    website_id = os.environ.get("UMAMI_WEBSITE_ID", "").strip()
    host = os.environ.get("UMAMI_HOST", "").strip()
    auth_header = os.environ.get("UMAMI_AUTH_HEADER", DEFAULT_AUTH_HEADER).strip() or DEFAULT_AUTH_HEADER
    path_prefix = os.environ.get("UMAMI_API_PATH_PREFIX", DEFAULT_API_PATH_PREFIX).strip() or DEFAULT_API_PATH_PREFIX

    missing = [n for n, v in (("UMAMI_API_KEY", api_key),
                              ("UMAMI_WEBSITE_ID", website_id),
                              ("UMAMI_HOST", host)) if not v]
    if missing:
        print("Faltan credenciales: " + ", ".join(missing) + ".", file=sys.stderr)
        print("Agregalas al .env del VPS (o exportalas en el entorno). La API key se",
              "crea en Umami Cloud → Settings → API keys; UMAMI_HOST=https://api.umami.is .",
              file=sys.stderr)
        return 1

    print(f"Consultando Umami: {args.desde} → {args.hasta} "
          f"({(args.hasta - args.desde).days + 1} días)…", file=sys.stderr)
    rows = fetch_daily(api_key, website_id, host, args.desde, args.hasta,
                       auth_header=auth_header, path_prefix=path_prefix)

    ok = sum(1 for r in rows if r["visitantes_unicos"] is not None)
    if ok == 0:
        print("Ninguna llamada devolvió datos. Revisá la API key / website_id / host.",
              file=sys.stderr)
        return 1

    write_csv(rows, args.out)
    print(f"CSV:  {args.out}  ({len(rows)} filas, {ok} con datos)")

    xlsx_path = os.path.splitext(args.out)[0] + ".xlsx"
    if write_xlsx(rows, xlsx_path):
        print(f"XLSX: {xlsx_path}")
    else:
        print("XLSX: omitido (openpyxl no instalado; el CSV abre igual en Excel). "
              "Para .xlsx nativo: pip install openpyxl", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
