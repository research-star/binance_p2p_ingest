#!/usr/bin/env python3
"""
ingest_bcb_tre.py — Scraper de la Tasa de Referencia (TRE) del BCB.

La TRE es la tasa de referencia mensual que publica el BCB (Acta N°026/2018 y
N°040/2023 del Directorio) y que se usa, entre otros, para el reajuste de tasas
variables de créditos. Se publica en cuatro monedas: MN (moneda nacional, la
principal), MVDOL, MN-UFV y ME (moneda extranjera).

Fuente: https://www.bcb.gob.bo/?q=tasas_interes → pestaña "Otras Tasas" →
"Evolución de las Tasas de Referencia (TRE)". Cada gestión (año) publica un
archivo Excel `NUEVA TRE GESTION-<año>[sufijo].xlsx` que se ACTUALIZA cada mes
agregando una fila. El sufijo varía por año (2023_2, 2024_2, 2025_1, 2026 sin
sufijo…), por eso el link NO se hardcodea: se DESCUBRE del listado (href con el
año más alto). El archivo de cada gestión trae además ~3 años de historia.

Estructura del Excel (validada contra NUEVA TRE GESTION-2026.xlsx, 2026-07-01):
  - Filas 1-10: encabezados. Data desde fila ~12.
  - Cols: B=DESDE, C=HASTA (período de cálculo), D=MN, E=MVDOL, F=MN-UFV, G=ME,
    H=VIGENCIA desde. Fechas como seriales Excel (epoch 1899-12-30); B a veces
    es string con nota "(**)1/5/2023". La VIGENCIA (H) es la fecha clave: el mes
    en que la tasa rige (≈ 2 meses después del período de cálculo).
  - Parser stdlib puro (zipfile + regex sobre el XML): sin openpyxl.

Salida: bcb_tre.json — [{vigencia, mn, mvdol, mn_ufv, me, calc_desde,
calc_hasta, source, gestion}], dedup/upsert por `vigencia` (el BCB puede
refinar decimales del último mes).

Uso:
    python3 ingest_bcb_tre.py                      # descubre gestión más alta → guarda
    python3 ingest_bcb_tre.py --dry-run            # imprime sin escribir
    python3 ingest_bcb_tre.py --backfill           # TODAS las gestiones del listado
    python3 ingest_bcb_tre.py --from-file F.xlsx   # parsea un archivo local (offline)
    python3 ingest_bcb_tre.py --url URL            # override del xlsx directo
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from config import BCB_TRE_JSON

URL_LISTING = "https://www.bcb.gob.bo/?q=tasas_interes"
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest)"}
OUTPUT = BCB_TRE_JSON

# Serial de Excel → fecha (epoch 1899-12-30). Rango plausible de seriales de
# fecha para acotar (2000-01-01=36526 … 2060-01-01≈58440).
EXCEL_EPOCH = date(1899, 12, 30)
SERIAL_MIN, SERIAL_MAX = 36526, 58440

# Rango plausible de una tasa TRE en % (acota basura numérica).
TRE_MIN, TRE_MAX = 0.0, 30.0


def fetch_bytes(url: str) -> bytes:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=60) as r:
        return r.read()


def discover_xlsx_urls(listing_html: str) -> dict[int, str]:
    """{año: url_xlsx} de los href `otras_tasas/*TRE*GESTION*<año>*.xlsx` del
    listado. El nombre real varía por gestión (sufijos _0/_1/_2), por eso se
    lee del HTML en vez de adivinar el patrón."""
    out: dict[int, str] = {}
    for m in re.finditer(
            r'href="(https?://[^"]*otras_tasas/[^"]*TRE[^"]*GESTION[^"]*\.xlsx)"',
            listing_html, re.IGNORECASE):
        url = m.group(1)
        y = re.search(r"(\d{4})(?:_\d+)?\.xlsx$", url, re.IGNORECASE)
        if y:
            out[int(y.group(1))] = url
    return out


def _serial_to_iso(v: float) -> str | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if not (SERIAL_MIN <= n <= SERIAL_MAX):
        return None
    return (EXCEL_EPOCH + timedelta(days=int(n))).isoformat()


def _es_short_date_to_iso(s: str) -> str | None:
    """'(**)1/5/2023' / '1/5/2023' → '2023-05-01' (formato d/m/yyyy)."""
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _rate(v: str | None) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 4) if TRE_MIN <= f <= TRE_MAX else None


def parse_tre_xlsx(data: bytes, gestion: int | None = None) -> list[dict]:
    """Parsea el xlsx de la TRE (stdlib: zipfile + regex sobre el XML).

    Una fila es de datos si tiene MN (D) numérica en rango y VIGENCIA (H) con
    serial de fecha plausible — los encabezados y pies quedan afuera solos."""
    z = zipfile.ZipFile(io.BytesIO(data))
    # shared strings (concatena runs de rich text: "(**)" + "1/5/2023")
    ss: list[str] = []
    try:
        sst = z.read("xl/sharedStrings.xml").decode("utf-8", errors="replace")
        for si in re.findall(r"<si>(.*?)</si>", sst, re.S):
            ss.append("".join(re.findall(r"<t[^>]*>([^<]*)</t>", si)))
    except KeyError:
        pass
    sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", errors="replace")

    entries: list[dict] = []
    for _rnum, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>', sheet, re.S):
        cells: dict[str, tuple[str | None, str]] = {}
        for m in re.finditer(
                r'<c r="([A-Z]+)\d+"(?:[^>]*t="(\w+)")?[^>]*>(?:<v>([^<]*)</v>)?',
                body):
            col, typ, val = m.groups()
            if val is None:
                continue
            if typ == "s":
                try:
                    val = ss[int(val)]
                except (ValueError, IndexError):
                    continue
            cells[col] = (typ, val)

        vig = cells.get("H")
        mn = cells.get("D")
        if not vig or not mn:
            continue
        vigencia = _serial_to_iso(vig[1]) if vig[0] != "s" else _es_short_date_to_iso(vig[1])
        mn_v = _rate(mn[1])
        if not vigencia or mn_v is None:
            continue

        def col_rate(c: str) -> float | None:
            t = cells.get(c)
            return _rate(t[1]) if t and t[0] != "s" else None

        def col_date(c: str) -> str | None:
            t = cells.get(c)
            if not t:
                return None
            return _es_short_date_to_iso(t[1]) if t[0] == "s" else _serial_to_iso(t[1])

        entries.append({
            "vigencia": vigencia,
            "mn": mn_v,
            "mvdol": col_rate("E"),
            "mn_ufv": col_rate("F"),
            "me": col_rate("G"),
            "calc_desde": col_date("B"),
            "calc_hasta": col_date("C"),
            "source": "bcb_tre",
            **({"gestion": gestion} if gestion else {}),
        })
    return entries


def save_entries(entries: list[dict], dry_run: bool = False) -> None:
    """Upsert al histórico JSON, dedup por `vigencia`; no pisa con None.
    Mismo contrato que bcb_tco/bcb_referencial."""
    if dry_run:
        print(f"[DRY RUN] {len(entries)} entradas no escritas; últimas 6:")
        for e in sorted(entries, key=lambda x: x["vigencia"])[-6:]:
            print(f"  vig {e['vigencia']}: MN {e['mn']}  ME {e['me']}")
        return
    history = []
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                history = prev
        except Exception as e:  # noqa: BLE001
            print(f"WARNING: no pude leer histórico previo: {e}", file=sys.stderr)
    by_vig = {h.get("vigencia"): h for h in history if h.get("vigencia")}
    added = updated = 0
    for e in entries:
        cur = by_vig.get(e["vigencia"])
        if cur is None:
            by_vig[e["vigencia"]] = dict(e)
            added += 1
        else:
            changed = False
            for k, v in e.items():
                if v is not None and cur.get(k) != v:
                    cur[k] = v
                    changed = True
            updated += int(changed)
    new_hist = sorted(by_vig.values(), key=lambda h: h["vigencia"])
    OUTPUT.write_text(json.dumps(new_hist, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{added} agregadas, {updated} actualizadas ({len(new_hist)} entradas totales): {OUTPUT}")


def main() -> int:
    p = argparse.ArgumentParser(description="Scraper de la Tasa de Referencia (TRE) del BCB")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--from-file", help="Parsear un xlsx local en vez de la red")
    p.add_argument("--url", help="URL directa del xlsx (salta el descubrimiento)")
    p.add_argument("--backfill", action="store_true",
                   help="Bajar TODAS las gestiones del listado (histórico completo)")
    args = p.parse_args()

    if args.from_file:
        data = Path(args.from_file).read_bytes()
        y = re.search(r"(\d{4})", Path(args.from_file).name)
        entries = parse_tre_xlsx(data, gestion=int(y.group(1)) if y else None)
        print(f"Leído {args.from_file}: {len(entries)} filas")
    else:
        if args.url:
            targets = {0: args.url}
        else:
            listing = fetch_bytes(URL_LISTING).decode("utf-8", errors="replace")
            found = discover_xlsx_urls(listing)
            if not found:
                print("ERROR: no encontré ningún xlsx de TRE en el listado. "
                      "¿Cambió la página? Revisá " + URL_LISTING, file=sys.stderr)
                return 1
            years = sorted(found)
            print(f"Listado: gestiones {years[0]}–{years[-1]} ({len(found)} archivos)")
            targets = ({y: found[y] for y in years} if args.backfill
                       else {years[-1]: found[years[-1]]})
        entries = []
        for y, url in sorted(targets.items()):
            print(f"Bajando gestión {y or '?'}: {url}")
            rows = parse_tre_xlsx(fetch_bytes(url), gestion=y or None)
            print(f"  {len(rows)} filas")
            entries.extend(rows)

    if not entries:
        print("ERROR: no parseé ninguna fila de TRE. ¿Cambió el formato del xlsx?",
              file=sys.stderr)
        return 1
    vigs = sorted(e["vigencia"] for e in entries)
    print(f"TRE parseada: {len(entries)} meses (vigencias {vigs[0]} → {vigs[-1]})")
    save_entries(entries, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
