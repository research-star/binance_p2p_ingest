#!/usr/bin/env python3
"""
backfill_og_images.py — One-shot: pobla noticias.image_url NULL con el og:image
real de cada nota (carril Bolivia, FASE 2a).

image_url nace NULL y el scraper solo la puebla en notas NUEVAS, así que una DB
ya poblada (snapshot local o prod recién migrada) muestra 100% placeholder hasta
que el feed rote ~30 días. Este one-shot la rellena ahora, reusando el MISMO
fetch + parseo del pipeline.

Reuso, NO reimplementación: llama a scraper.scrape_cuerpo (mismo cliente
curl_cffi/impersonate + fallback chain), que internamente parsea con _og_image.
Descarta el cuerpo y se queda con la URL del og:image.

Idempotente:
  - SELECT solo trae filas con image_url IS NULL.
  - UPDATE lleva `AND image_url IS NULL` (no pisa valores ya poblados).
  Re-correr solo completa lo que falta; nunca sobrescribe.

Alcance: ventana del feed (~30d, igual que dashboard.py) · carril BO (no latam) ·
image_url NULL. El Deber y portales sin og:image → quedan NULL (esperado, no error).

Uso:
    # Local (validación de Diego):
    python scripts/backfill_og_images.py --db p2p_normalized.db
    # Preview sin escribir:
    python scripts/backfill_og_images.py --db p2p_normalized.db --dry-run
    # Prod (VPS-write, SOLO con gate de Diego post-merge de #73):
    python scripts/backfill_og_images.py --db /opt/binance_p2p/p2p_normalized.db

Self-migrate: si la columna image_url no existe aún (DB sin 0004 aplicada), la
agrega (ALTER idempotente) antes de backfillear. Así corre en local sin 0004.
"""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from noticias_ingest.scraper import scrape_cuerpo, FUENTES  # noqa: E402

log = logging.getLogger("backfill_og")


def ensure_column(conn: sqlite3.Connection) -> None:
    """Self-migrate idempotente de image_url (mismo patrón que dashboard.py).
    SQLite no tiene ADD COLUMN IF NOT EXISTS → re-aplicar tira duplicate column,
    inocuo."""
    try:
        conn.execute("ALTER TABLE noticias ADD COLUMN image_url TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # la columna ya existe


def backfill(db_path: Path, window_days: int, dry_run: bool) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    ensure_column(conn)

    # Ventana del feed: igual que el SELECT de dashboard.py (date('now','-4h','-29d')).
    offset = f"-{window_days - 1} days"
    rows = conn.execute(
        "SELECT id, url, portal FROM noticias "
        "WHERE image_url IS NULL AND category != 'latam' "
        "  AND date >= date('now', '-4 hours', ?) "
        "ORDER BY date DESC",
        (offset,),
    ).fetchall()

    total = len(rows)
    log.info("Notas con image_url NULL en ventana %dd (carril BO): %d", window_days, total)
    if dry_run:
        log.info(">> DRY-RUN: no se escribe nada, solo se reporta.")

    metodo_by_portal = {f["portal"]: f.get("metodo", "requests") for f in FUENTES}
    pobladas = 0
    errores = 0
    null_por_portal: dict[str, int] = {}

    for i, r in enumerate(rows, 1):
        portal = r["portal"]
        metodo = metodo_by_portal.get(portal, "requests")
        try:
            _cuerpo, img = scrape_cuerpo(r["url"], metodo=metodo)
        except Exception as e:  # noqa: BLE001 — un fallo no debe abortar el lote
            errores += 1
            log.warning("[ERR %d/%d] %s %s :: %s", i, total, portal, r["url"][:60], e)
            continue
        if img:
            if not dry_run:
                conn.execute(
                    "UPDATE noticias SET image_url = ? WHERE id = ? AND image_url IS NULL",
                    (img, r["id"]),
                )
            pobladas += 1
            log.info("[OK   %d/%d] %-18s -> %s", i, total, portal, img[:70])
        else:
            null_por_portal[portal] = null_por_portal.get(portal, 0) + 1
            log.info("[NULL %d/%d] %-18s (sin og:image / bloqueado)", i, total, portal)

    if not dry_run:
        conn.commit()
    conn.close()

    null_total = sum(null_por_portal.values())
    log.info("=" * 56)
    log.info(
        "RESUMEN%s: total=%d  pobladas=%d  NULL=%d  errores=%d",
        " (DRY-RUN)" if dry_run else "", total, pobladas, null_total, errores,
    )
    for portal, n in sorted(null_por_portal.items(), key=lambda x: -x[1]):
        log.info("   NULL por bloqueo/sin-og:  %-20s %d", portal, n)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill one-shot de noticias.image_url (og:image real). Idempotente."
    )
    ap.add_argument("--db", type=Path, required=True, help="Path a la DB SQLite")
    ap.add_argument("--window-days", type=int, default=30,
                    help="Ventana del feed en días (default 30 = ventana del dashboard)")
    ap.add_argument("--dry-run", action="store_true",
                    help="No escribe; solo reporta qué poblaría")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not args.db.exists():
        log.error("No existe la DB: %s", args.db)
        sys.exit(1)
    backfill(args.db, args.window_days, args.dry_run)


if __name__ == "__main__":
    main()
