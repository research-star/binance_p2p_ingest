#!/usr/bin/env python3
"""
bcb_referencial.py — Scraper del valor referencial USD/BOB publicado por el BCB.

El BCB publica desde dic-2025 un valor referencial diario basado en operaciones
reales de bancos.

Endpoints:
    /valor_referencial_compra_svg_v2.php  — TABLA HTML con histórico de compra
                                            desde 1-dic-2025. Fila "BANCOS (PROMEDIO
                                            PONDERADO)" = valor referencial diario.
    /valor_referencial_venta_svg.php      — SVG con histórico de venta (106+ filas
                                            cronológicas con cell-text/cell-value).
                                            La fila --highlight es la del día.

Cada corrida:
  1. Baja histórico de compra (tabla v2) → serie completa de compra.
  2. Baja histórico de venta (SVG) → serie completa de venta.
  3. Merge por fecha: cada entrada {fecha, compra, venta, source} en el JSON.

Uso:
    python3 bcb_referencial.py                        # fetch + backfill automático
    python3 bcb_referencial.py --dry-run              # imprimir sin guardar
    python3 bcb_referencial.py --no-backfill          # solo valor de hoy, sin tabla histórica
    python3 bcb_referencial.py --manual \
        --fecha 2026-04-15 --compra 9.35 --venta 9.55 # entrada manual
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL_VENTA = "https://www.bcb.gob.bo/valor_referencial_venta_svg.php"
URL_COMPRA_V2 = "https://www.bcb.gob.bo/valor_referencial_compra_svg_v2.php"
OUTPUT = Path("bcb_referencial.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest)"}

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
MONTH_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def fetch(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8")


def parse_venta_svg_history(svg: str) -> list[dict]:
    """Parsea las 106+ filas históricas del SVG de venta. Formato:
        <text class="cell-text">1 de diciembre de 2025</text>
        <text class="cell-value">9,32</text>
    Variantes --highlight para la fila del día actual.
    """
    pattern = re.compile(
        r'class="cell-text(?:--highlight)?"[^>]*>([^<]+)</[^>]+>\s*'
        r'(?:<[^>]+>\s*)*'  # puede haber otros tags entre medio
        r'<[^>]*class="cell-value(?:--highlight)?"[^>]*>([^<]+)<',
        re.IGNORECASE
    )
    out = []
    for m in pattern.finditer(svg):
        date_str = m.group(1).strip()
        val_str = m.group(2).strip()
        md = re.match(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", date_str, re.IGNORECASE)
        if not md:
            continue
        month = SPANISH_MONTHS.get(md.group(2).lower())
        if not month:
            continue
        fecha = f"{int(md.group(3)):04d}-{month:02d}-{int(md.group(1)):02d}"
        try:
            val = float(val_str.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        out.append({"fecha": fecha, "venta": val})
    return out


def parse_historic_table(html: str, start_year: int = 2025) -> list[dict]:
    """Parsea la tabla histórica de compra. Devuelve [{fecha, compra}, ...].

    Los headers tienen formato 'N-MMM' (ej '1-dic', '23-abr'). La tabla está
    ordenada cronológicamente, así que incrementamos el año cuando el mes
    retrocede (dic → ene).
    """
    headers = re.findall(r'<th class="bcb-num" scope="col">([^<]+)</th>', html)
    if not headers:
        return []

    # Asignar fechas completas a cada header
    dates = []
    year = start_year
    prev_month = 0
    for h in headers:
        m = re.match(r"(\d{1,2})-([a-z]{3})", h.strip().lower())
        if not m:
            dates.append(None)
            continue
        day = int(m.group(1))
        month = MONTH_ABBR.get(m.group(2))
        if not month:
            dates.append(None)
            continue
        if prev_month and month < prev_month:
            year += 1
        prev_month = month
        dates.append(f"{year:04d}-{month:02d}-{day:02d}")

    # Buscar la fila "BANCOS (PROMEDIO PONDERADO)"
    promedio_row = None
    for row in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL):
        if re.search(r'PROMEDIO\s+PONDERADO', row, re.IGNORECASE):
            promedio_row = row
            break
    if not promedio_row:
        return []

    cells = re.findall(r'<t[dh][^>]*>([^<]*)</t[dh]>', promedio_row)
    # Primera celda es la etiqueta "BANCOS (PROMEDIO PONDERADO)", resto son valores
    values = cells[1:]
    if len(values) != len(dates):
        # Desalineación rara — truncar al mínimo
        n = min(len(values), len(dates))
        values, dates = values[:n], dates[:n]

    out = []
    for d, v in zip(dates, values):
        if not d:
            continue
        v = v.strip().replace(".", "").replace(",", ".")  # "1.234,56" → "1234.56"
        try:
            val = float(v)
        except ValueError:
            continue  # celdas "—" o vacías
        out.append({"fecha": d, "compra": val})
    return out


def save_entries(entries: list[dict], dry_run: bool = False) -> None:
    """Agrega/actualiza entradas al histórico JSON. Dedup por fecha.
    Si ya existe la fecha y la nueva tiene campos nuevos (ej agrega venta),
    hace merge. No pisa valores existentes con None."""
    if dry_run:
        print(f"[DRY RUN] {len(entries)} entradas no escritas")
        return

    history = []
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(prev, list):
                history = prev
            elif isinstance(prev, dict) and prev.get("fecha_publicacion"):
                history = [{
                    "fecha": prev["fecha_publicacion"],
                    "compra": prev.get("compra"),
                    "venta": prev.get("venta"),
                }]
        except Exception as e:
            print(f"WARNING: no pude leer histórico previo: {e}", file=sys.stderr)

    by_fecha = {h.get("fecha"): h for h in history if h.get("fecha")}
    added = 0
    updated = 0
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


def main():
    parser = argparse.ArgumentParser(description="Scraper del valor referencial BCB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backfill", action="store_true",
                        help="Saltear la tabla histórica v2, solo traer valor del día")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--fecha")
    parser.add_argument("--compra", type=float)
    parser.add_argument("--venta", type=float)
    parser.add_argument("--source", default="manual")
    args = parser.parse_args()

    if args.manual:
        if not (args.fecha and args.compra is not None and args.venta is not None):
            print("ERROR: --manual requiere --fecha YYYY-MM-DD --compra X.XX --venta X.XX", file=sys.stderr)
            sys.exit(2)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.fecha):
            print(f"ERROR: --fecha debe ser YYYY-MM-DD, recibí: {args.fecha}", file=sys.stderr)
            sys.exit(2)
        entry = {"fecha": args.fecha, "compra": args.compra, "venta": args.venta, "source": args.source}
        print(f"Manual -- {entry['fecha']}: Compra Bs {entry['compra']} | Venta Bs {entry['venta']}")
        save_entries([entry], dry_run=args.dry_run)
        return

    entries = []

    # 1) Histórico completo de compra (v2)
    if not args.no_backfill:
        try:
            html_v2 = fetch(URL_COMPRA_V2)
            hist = parse_historic_table(html_v2)
            for e in hist:
                e["source"] = "bcb_v2_table"
            entries.extend(hist)
            print(f"Histórico compra (v2): {len(hist)} días parseados "
                  f"({hist[0]['fecha']} -> {hist[-1]['fecha']})" if hist else "Historico: vacio")
        except Exception as e:
            print(f"WARNING: no pude bajar histórico v2: {e}", file=sys.stderr)

    # 2) Histórico completo de venta (SVG con 106+ entradas cronológicas)
    try:
        svg_v = fetch(URL_VENTA)
        venta_hist = parse_venta_svg_history(svg_v)
        for e in venta_hist:
            e["source"] = "bcb_venta_svg"
        entries.extend(venta_hist)
        if venta_hist:
            print(f"Histórico venta: {len(venta_hist)} días parseados "
                  f"({venta_hist[0]['fecha']} -> {venta_hist[-1]['fecha']})")
    except Exception as e:
        print(f"WARNING: no pude bajar histórico de venta: {e}", file=sys.stderr)

    # 3) Timestamp de fetch para la entrada del día de hoy (metadata)
    today_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if entries:
        # Encuentra la fecha más reciente y etiqueta fetched_at_utc
        latest_fecha = max(e["fecha"] for e in entries)
        for e in entries:
            if e["fecha"] == latest_fecha:
                e["fetched_at_utc"] = today_iso

    if not entries:
        print("ERROR: sin entradas nuevas para guardar.", file=sys.stderr)
        sys.exit(1)

    save_entries(entries, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
