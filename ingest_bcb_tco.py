#!/usr/bin/env python3
"""
ingest_bcb_tco.py — Scraper del Tipo de Cambio Oficial (TCO) del BCB.

Desde la RD N° 88/2026 (26-jun-2026, deja sin efecto el Reglamento de 2013) el
BCB publica un **Tipo de Cambio Oficial (TCO)** que reemplaza al tipo de cambio
fijo (6,86 compra / 6,96 venta). Definición (Anexo II de la RD 88/2026):

  - El TCO es el **promedio ponderado de las operaciones de COMPRA de USD** de
    los Bancos Múltiples, Bancos PyME y el Banco Público con sus clientes, entre
    00:00 y 17:00 de cada día hábil, ponderado por el monto en USD de cada
    operación. Excluye operaciones entre entidades financieras.
  - Se publica cada día hábil a las **20:00** y es **vigente al día siguiente**.
  - Redondeado a 2 decimales. Sáb/dom/feriados = TCO del último día hábil.
  - El valor referencial de venta = TCO + 0,10 Bs.

Fuente (reporte histórico detallado, de ahí sale la serie completa):
    https://www.bcb.gob.bo/tco_reporte_detalle_historico.php

──────────────────────────────────────────────────────────────────────────────
NOTA DE DESARROLLO (2026-06-27): la página del BCB NO es alcanzable desde el
entorno de desarrollo (firewall). El parser está escrito de forma DEFENSIVA y se
afina corriéndolo en el VPS, que sí alcanza BCB. Bucle de iteración:

    # En el VPS (alcanza BCB): bajar y volcar el crudo para inspección
    python3 ingest_bcb_tco.py --debug          # escribe bcb_tco_raw.html

    # Parsear un archivo local (CSV o HTML) SIN red, para validar el parser
    python3 ingest_bcb_tco.py --from-file bcb_tco_raw.html --dry-run

Si el parser no encuentra filas, sale con código ≠0 y un mensaje claro; con
--debug deja el crudo en disco para ajustar las heurísticas en un follow-up.
──────────────────────────────────────────────────────────────────────────────

Uso:
    python3 ingest_bcb_tco.py                       # fetch + parse + guarda histórico
    python3 ingest_bcb_tco.py --dry-run             # imprime sin escribir
    python3 ingest_bcb_tco.py --from-file ARCHIVO   # parsea un archivo local (offline)
    python3 ingest_bcb_tco.py --debug               # vuelca el crudo a bcb_tco_raw.html
    python3 ingest_bcb_tco.py --url OTRA_URL        # override del endpoint
    python3 ingest_bcb_tco.py --manual --fecha 2026-06-26 --tco 9.76
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from config import BCB_TCO_JSON

URL_TCO = "https://www.bcb.gob.bo/tco_reporte_detalle_historico.php"
OUTPUT = BCB_TCO_JSON
RAW_DUMP = Path("bcb_tco_raw.html")
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest)"}

# Rango plausible de un TCO BOB/USD. Acota candidatos numéricos para no confundir
# años (2026), montos o IDs con la cotización. El TCO arrancó ~6.9 y flota; un
# techo holgado (30) tolera deslizamientos futuros sin capturar basura.
TCO_MIN, TCO_MAX = 4.0, 30.0

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


# ── Fetch ────────────────────────────────────────────────────────────────────

def fetch(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        raw = r.read()
    # El BCB sirve UTF-8; tolerar latin-1 por las dudas.
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ── Parsers de fecha / número ────────────────────────────────────────────────

def parse_fecha(s: str) -> str | None:
    """Devuelve 'YYYY-MM-DD' o None. Tolera los formatos que suele usar el BCB:
        2026-06-26 · 26/06/2026 · 26-06-2026 · 26 de junio de 2026 · 26-jun-2026
    """
    if not s:
        return None
    s = s.strip()

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        y, mo, d = map(int, m.groups())
        if 2020 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\b", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", s, re.IGNORECASE)
    if m:
        mo = SPANISH_MONTHS.get(m.group(2).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"

    m = re.search(r"\b(\d{1,2})[-\s]([a-z]{3})[-\s.]*(\d{4})\b", s, re.IGNORECASE)
    if m:
        mo = MONTH_ABBR.get(m.group(2).lower())
        if mo:
            return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(1)):02d}"

    return None


def parse_rate(s: str) -> float | None:
    """Devuelve el TCO como float si el token PARECE una cotización (tiene
    decimales y cae en el rango plausible), o None. Exigir el separador decimal
    evita capturar días/años/enteros sueltos."""
    if not s:
        return None
    m = re.search(r"\d{1,2}[.,]\d{1,4}", s.strip())
    if not m:
        return None
    token = m.group(0)
    try:
        # "1.234,56" → 1234.56 ; "9,76" → 9.76 ; "9.76" → 9.76
        if "," in token:
            val = float(token.replace(".", "").replace(",", "."))
        else:
            val = float(token)
    except ValueError:
        return None
    return val if TCO_MIN <= val <= TCO_MAX else None


# ── Parsers de contenido ─────────────────────────────────────────────────────

def _strip_tags(cell: str) -> str:
    return re.sub(r"<[^>]+>", " ", cell).strip()


def parse_csv(text: str) -> list[dict]:
    """Parsea un CSV (o pseudo-CSV) de fecha + TCO. Detecta el delimitador y, por
    cada fila, toma la primera celda que parsea como fecha y la primera que parsea
    como cotización plausible."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        delim = ";" if line.count(";") >= line.count(",") and ";" in line else ","
        cells = [c.strip().strip('"') for c in line.split(delim)]
        fecha = next((f for f in (parse_fecha(c) for c in cells) if f), None)
        if not fecha:
            continue
        tco = next((r for r in (parse_rate(c) for c in cells) if r is not None), None)
        if tco is None:
            continue
        out.append({"fecha": fecha, "tco": tco})
    return out


def parse_html(text: str) -> list[dict]:
    """Extrae pares (fecha, TCO) de las tablas HTML. Cubre dos orientaciones:
      (a) fila = (fecha, valor)  — el caso típico de un 'detalle histórico'.
      (b) headers = fechas + una fila de valores (tabla transpuesta estilo BCB).
    Devuelve candidatos deduplicados por fecha (gana el último visto)."""
    by_fecha: dict[str, float] = {}

    for table in re.findall(r"<table[^>]*>(.*?)</table>", text, re.DOTALL | re.IGNORECASE):
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL | re.IGNORECASE)
        parsed_rows = []
        for row in rows:
            cells = [_strip_tags(c) for c in
                     re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)]
            parsed_rows.append(cells)

        # (a) fila = (fecha, valor)
        for cells in parsed_rows:
            fecha = next((f for f in (parse_fecha(c) for c in cells) if f), None)
            if not fecha:
                continue
            tco = next((r for r in (parse_rate(c) for c in cells) if r is not None), None)
            if tco is not None:
                by_fecha[fecha] = tco

        # (b) transpuesta: una fila de fechas + fila etiquetada TCO/promedio/oficial
        header_dates = [parse_fecha(c) for c in (parsed_rows[0] if parsed_rows else [])]
        if any(header_dates):
            label_re = re.compile(r"PROMEDIO\s+PONDERADO|TIPO\s+DE\s+CAMBIO|\bTCO\b|OFICIAL",
                                  re.IGNORECASE)
            for cells in parsed_rows[1:]:
                if cells and label_re.search(cells[0]):
                    # Alinear por la DERECHA: las columnas de datos son las finales,
                    # tolera que el header tenga (o no) una celda esquina inicial.
                    n = min(len(header_dates), len(cells))
                    for d, raw in zip(header_dates[-n:], cells[-n:]):
                        if not d:
                            continue
                        r = parse_rate(raw)
                        if r is not None:
                            by_fecha.setdefault(d, r)
                    break

    return [{"fecha": f, "tco": v} for f, v in by_fecha.items()]


def parse_content(text: str) -> list[dict]:
    """Despacha a parser HTML o CSV según el contenido."""
    looks_html = bool(re.search(r"<\s*(table|html|td|tr|body)\b", text, re.IGNORECASE))
    entries = parse_html(text) if looks_html else parse_csv(text)
    # Fallback cruzado: si una vía no rindió nada, probar la otra.
    if not entries:
        entries = parse_csv(text) if looks_html else parse_html(text)
    return entries


# ── Persistencia ─────────────────────────────────────────────────────────────

def save_entries(entries: list[dict], dry_run: bool = False) -> None:
    """Agrega/actualiza al histórico JSON. Dedup por fecha; no pisa con None.
    Mismo contrato que bcb_referencial.save_entries."""
    if dry_run:
        print(f"[DRY RUN] {len(entries)} entradas no escritas")
        for e in sorted(entries, key=lambda x: x["fecha"])[-8:]:
            print(f"  {e['fecha']}: TCO {e['tco']}")
        return

    history = []
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                history = prev
        except Exception as e:
            print(f"WARNING: no pude leer histórico previo: {e}", file=sys.stderr)

    by_fecha = {h.get("fecha"): h for h in history if h.get("fecha")}
    added = updated = 0
    for e in entries:
        if not e.get("fecha"):
            continue
        if e["fecha"] in by_fecha:
            cur = by_fecha[e["fecha"]]
            changed = False
            for k, v in e.items():
                if v is None:
                    continue
                if cur.get(k) != v:
                    cur[k] = v
                    changed = True
            if changed:
                updated += 1
        else:
            by_fecha[e["fecha"]] = dict(e)
            added += 1

    new_hist = sorted(by_fecha.values(), key=lambda h: h.get("fecha") or "")
    OUTPUT.write_text(json.dumps(new_hist, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{added} agregadas, {updated} actualizadas ({len(new_hist)} entradas totales): {OUTPUT}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scraper del Tipo de Cambio Oficial (TCO) del BCB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-file", help="Parsear un archivo local (CSV o HTML) en vez de la red")
    parser.add_argument("--debug", action="store_true",
                        help=f"Volcar el contenido crudo a {RAW_DUMP} para inspección")
    parser.add_argument("--url", default=URL_TCO, help="Override del endpoint del BCB")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--fecha")
    parser.add_argument("--tco", type=float)
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()

    # Entrada manual (backfill puntual / corrección)
    if args.manual:
        if not (args.fecha and args.tco is not None):
            print("ERROR: --manual requiere --fecha YYYY-MM-DD --tco X.XX", file=sys.stderr)
            sys.exit(2)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.fecha):
            print(f"ERROR: --fecha debe ser YYYY-MM-DD, recibí: {args.fecha}", file=sys.stderr)
            sys.exit(2)
        entry = {"fecha": args.fecha, "tco": args.tco, "source": args.source}
        print(f"Manual -- {entry['fecha']}: TCO Bs {entry['tco']}")
        save_entries([entry], dry_run=args.dry_run)
        return

    # Obtener contenido (red o archivo local)
    if args.from_file:
        content = Path(args.from_file).read_text(encoding="utf-8", errors="replace")
        print(f"Leído de archivo local: {args.from_file} ({len(content)} chars)")
    else:
        try:
            content = fetch(args.url)
        except Exception as e:
            print(f"ERROR: no pude bajar {args.url}: {e}", file=sys.stderr)
            sys.exit(1)
        if args.debug:
            RAW_DUMP.write_text(content, encoding="utf-8")
            print(f"[DEBUG] crudo volcado a {RAW_DUMP} ({len(content)} chars)")

    entries = parse_content(content)
    for e in entries:
        e["source"] = "bcb_tco"

    if not entries:
        print("ERROR: no parseé ninguna entrada de TCO. Revisá el formato de la "
              "fuente; corré con --debug para volcar el crudo y ajustar el parser.",
              file=sys.stderr)
        if not args.debug and not args.from_file:
            RAW_DUMP.write_text(content, encoding="utf-8")
            print(f"(crudo guardado en {RAW_DUMP} para inspección)", file=sys.stderr)
        sys.exit(1)

    # Sello de fetch en la fecha más reciente (metadata)
    latest_fecha = max(e["fecha"] for e in entries)
    today_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for e in entries:
        if e["fecha"] == latest_fecha:
            e["fetched_at_utc"] = today_iso

    fechas = sorted(e["fecha"] for e in entries)
    print(f"TCO parseado: {len(entries)} días ({fechas[0]} → {fechas[-1]})")
    save_entries(entries, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
