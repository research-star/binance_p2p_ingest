#!/usr/bin/env python3
"""
bcb_referencial.py — Scraper del valor referencial USD/BOB publicado por el BCB.

El BCB publica desde dic-2025 un valor referencial diario basado en operaciones
reales de bancos. La página sirve los valores como SVG dinámicos:
    /valor_referencial_compra_svg.php
    /valor_referencial_venta_svg.php

Extraemos valor y fecha con regex. Guardamos en bcb_referencial.json como array
de {fecha, compra, venta, fetched_at_utc}. Cada corrida acumula el dato del día
si la fecha no está ya. Así se arma la serie histórica automáticamente.

Uso:
    python3 bcb_referencial.py                        # fetch del valor actual y guardar
    python3 bcb_referencial.py --dry-run              # imprimir sin guardar
    python3 bcb_referencial.py --manual \
        --fecha 2026-04-15 --compra 9.35 --venta 9.55 # agregar entrada manual

Nota sobre histórico: los SVGs del BCB NO aceptan parámetro de fecha
(probado: ?fecha, ?date, ?d, ?f, ?hist, ?historico — todos devuelven el día
actual). El único endpoint es el valor vigente. Para completar días pasados
hay que usar --manual con datos de noticias/prensa.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL_COMPRA = "https://www.bcb.gob.bo/valor_referencial_compra_svg.php"
URL_VENTA = "https://www.bcb.gob.bo/valor_referencial_venta_svg.php"
OUTPUT = Path("bcb_referencial.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (binance_p2p_ingest)"}

SPANISH_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def fetch(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")


def parse_svg(svg: str) -> dict:
    """Extrae (valor, fecha) del SVG. Valor en formato 'Bs 9,39/$us'."""
    m_val = re.search(r"Bs\s+(\d+),(\d+)/\$us", svg)
    m_date = re.search(r"FECHA DE PUBLICACI[ÓO]N:\s*(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", svg, re.IGNORECASE)
    out = {}
    if m_val:
        out["value"] = float(f"{m_val.group(1)}.{m_val.group(2)}")
    if m_date:
        day = int(m_date.group(1))
        month = SPANISH_MONTHS.get(m_date.group(2).lower())
        year = int(m_date.group(3))
        if month:
            out["date"] = f"{year:04d}-{month:02d}-{day:02d}"
    return out


def save_entry(entry: dict, dry_run: bool = False):
    """Agrega entry al histórico JSON. Dedup por fecha. Migra formato viejo."""
    if dry_run:
        print("[DRY RUN] no se escribió archivo")
        return
    history = []
    migrated = False
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
                    "fetched_at_utc": prev.get("fetched_at_utc"),
                }]
                migrated = True
        except Exception as e:
            print(f"WARNING: no pude leer histórico previo: {e}", file=sys.stderr)

    fechas = {h.get("fecha") for h in history}
    added = entry["fecha"] not in fechas
    if added:
        history.append(entry)

    if added or migrated:
        history.sort(key=lambda h: h.get("fecha") or "")
        OUTPUT.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
        msg = "Migrado + " if migrated else ""
        msg += f"{'agregada' if added else 'sin entrada nueva'} ({len(history)} entradas)"
        print(f"{msg}: {OUTPUT}")
    else:
        print(f"Fecha {entry['fecha']} ya está en el histórico. Sin cambios ({len(history)} entradas).")


def main():
    parser = argparse.ArgumentParser(description="Scraper del valor referencial BCB")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--manual", action="store_true",
                        help="Agregar entrada manual (requiere --fecha --compra --venta)")
    parser.add_argument("--fecha", help="YYYY-MM-DD (solo con --manual)")
    parser.add_argument("--compra", type=float, help="Valor compra (solo con --manual)")
    parser.add_argument("--venta", type=float, help="Valor venta (solo con --manual)")
    parser.add_argument("--source", default="manual",
                        help="Etiqueta de fuente (solo con --manual, default: 'manual')")
    args = parser.parse_args()

    if args.manual:
        if not (args.fecha and args.compra is not None and args.venta is not None):
            print("ERROR: --manual requiere --fecha YYYY-MM-DD --compra X.XX --venta X.XX", file=sys.stderr)
            sys.exit(2)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.fecha):
            print(f"ERROR: --fecha debe ser YYYY-MM-DD, recibí: {args.fecha}", file=sys.stderr)
            sys.exit(2)
        entry = {
            "fecha": args.fecha,
            "compra": args.compra,
            "venta": args.venta,
            "source": args.source,
        }
        print(f"Manual — {entry['fecha']}: Compra Bs {entry['compra']} · Venta Bs {entry['venta']}")
        save_entry(entry, dry_run=args.dry_run)
        return

    try:
        svg_c = fetch(URL_COMPRA)
        svg_v = fetch(URL_VENTA)
    except Exception as e:
        print(f"ERROR al bajar SVGs: {e}", file=sys.stderr)
        sys.exit(1)

    compra = parse_svg(svg_c)
    venta = parse_svg(svg_v)

    if "value" not in compra or "value" not in venta:
        print("ERROR: no se pudo parsear el valor. Formato del SVG cambió?", file=sys.stderr)
        print(f"  compra: {compra}  venta: {venta}", file=sys.stderr)
        sys.exit(2)

    entry = {
        "fecha": compra.get("date") or venta.get("date"),
        "compra": compra.get("value"),
        "venta": venta.get("value"),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    print(f"BCB Referencial — publicado {entry['fecha']}")
    print(f"  Compra: Bs {entry['compra']}")
    print(f"  Venta:  Bs {entry['venta']}")

    entry["source"] = "scraped"
    save_entry(entry, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
