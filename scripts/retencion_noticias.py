#!/usr/bin/env python3
"""
retencion_noticias.py — Retención diaria de la tabla `noticias` (WS2 de top-50).

Dos etapas idempotentes sobre p2p_normalized.db, bajo un lock de un solo escritor:

  1. BACKUP TEMPRANO (20d): archiva a un JSONL append-only las notas que cruzan 20
     días de antigüedad (nota COMPLETA, todas las columnas), incrementalmente vía un
     marcador de estado (última fecha archivada). Da una copia 10 días ANTES del
     borrado (ventana de recuperación).

  2. BORRADO (30d): borra las notas con `date` de 30 días o más. SEGURIDAD POR
     CONSTRUCCIÓN: antes del DELETE archiva al MISMO JSONL exactamente las filas que
     va a borrar (en la misma corrida), así NUNCA se borra algo que no quedó en el
     archivo — sin depender del marcador como proxy. Orden: append+fsync del JSONL →
     DELETE+commit; un crash entremedio deja archivo con duplicado benigno + fila aún
     en la DB (se re-poda la próxima corrida), jamás al revés. A 30d ya salieron de la
     ventana de dedupe (7d) → sin yo-yo.

El JSONL es append-only y puede contener una nota MÁS DE UNA VEZ (a los 20d y otra
vez a los 30d, o por un re-archivo tras crash/solapamiento). **Todo consumidor del
archivo DEBE dedupear por `id` (last-write-wins).**

Es un DELETE por RANGO de fecha sobre datos de PRODUCCIÓN (distinto de la evicción
por-id de lane_bolivia). Aplica a AMBOS carriles (retención por edad). Separado de
ingest_noticias a propósito (una responsabilidad, un cron). NO toca la ingesta.

Uso:
    python scripts/retencion_noticias.py                 # corrida normal
    python scripts/retencion_noticias.py --dry-run       # sin escribir (preview)
    python scripts/retencion_noticias.py --db test.db    # DB alternativa (dev/test)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import fcntl  # POSIX (VPS Linux): lock de un solo escritor, auto-liberado al morir el proceso
except ImportError:
    fcntl = None  # Windows/dev: sin lock (los tests son single-writer; el cron real corre en Linux)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import NORMALIZED_DB
from noticias_ingest.scraper import DATA_DIR  # gitignored (noticias_ingest/data/)

BACKUP_DIAS = 20
BORRADO_DIAS = 30
BOLIVIA_TZ = timezone(timedelta(hours=-4))  # UTC-4 fijo (sin DST), igual que el resto del pipeline
_RE_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ARCHIVE_DEFAULT = DATA_DIR / "noticias_archive.jsonl"
STATE_DEFAULT = DATA_DIR / "noticias_archive.state"
LOCK_DEFAULT = DATA_DIR / "noticias_retencion.lock"


def _fecha_bo(ahora_utc: datetime, dias_atras: int) -> str:
    """Fecha (YYYY-MM-DD, hora Bolivia UTC-4) de hace `dias_atras` días."""
    return (ahora_utc.astimezone(BOLIVIA_TZ) - timedelta(days=dias_atras)).strftime("%Y-%m-%d")


def leer_marcador(state_path: Path) -> str:
    """Última fecha archivada por el backup incremental. Devuelve '' (fail-safe) si el
    archivo no existe, es ilegible, o su contenido NO es una fecha ISO válida — así un
    .state corrupto/basura no puede envenenar el rango (con '' el backup re-archiva todo
    `date <= umbral_20`; el borrado NO depende del marcador, ver borrar())."""
    try:
        s = state_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        # UnicodeDecodeError NO es subclase de OSError: un .state con bytes UTF-8 inválidos
        # (corrupción de disco / escritura parcial) crasheaba el cron sin este catch.
        return ""
    if not _RE_FECHA.match(s):
        if s:
            print(f"[retencion] WARN marcador ilegible/no-fecha ({s!r}) → se ignora (re-archiva todo)",
                  file=sys.stderr)
        return ""
    return s


def guardar_marcador(state_path: Path, fecha: str) -> None:
    """Escribe el marcador atómicamente (temp con fsync + os.replace en el mismo dir)."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(fecha)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state_path)  # atómico en el mismo filesystem


def _append_jsonl(archive_path: Path, cols: list, filas: list) -> None:
    """Append (una nota-dict por línea) + fsync. No-op si `filas` está vacío."""
    if not filas:
        return
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with archive_path.open("a", encoding="utf-8") as f:
        for row in filas:
            f.write(json.dumps(dict(zip(cols, row)), ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


@contextmanager
def _lock(lock_path: Path):
    """Lock de un solo escritor (POSIX flock, no bloqueante). Cede False si ya hay una
    corrida en curso (cron solapado + run manual) → el caller sale no-op, evitando
    duplicación/entrelazado del JSONL. En plataformas sin fcntl (dev) cede True sin lock."""
    if fcntl is None:
        yield True
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True
    finally:
        f.close()  # libera el flock (y ante crash lo libera el SO)


def _chequeo_fechas(conn: sqlite3.Connection) -> None:
    """Health-signal: notas con date NULL o no-ISO nunca las poda la retención (NULL da
    falso en date<=? ; un date no zero-padded ordena mal). No aborta: sólo alerta."""
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM noticias "
            "WHERE date IS NULL OR date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
        ).fetchone()[0]
        if n:
            print(f"[retencion] WARN {n} nota(s) con date NULL/no-ISO: la retención no las poda "
                  f"(revisar la ingesta)", file=sys.stderr)
    except sqlite3.Error:
        pass


def backup(conn: sqlite3.Connection, ahora_utc: datetime, *,
           archive_path: Path, state_path: Path, dry_run: bool) -> dict:
    """Archiva a JSONL las notas en (marcador .. umbral_20]. Idempotente vía marcador."""
    umbral_20 = _fecha_bo(ahora_utc, BACKUP_DIAS)
    marcador = leer_marcador(state_path)
    cur = conn.execute(
        "SELECT * FROM noticias WHERE date > ? AND date <= ? ORDER BY date, id",
        (marcador, umbral_20))
    cols = [d[0] for d in cur.description]
    filas = cur.fetchall()
    if dry_run:
        return {"archivadas": len(filas), "umbral_20": umbral_20,
                "marcador_previo": marcador, "marcador_nuevo": marcador}
    _append_jsonl(archive_path, cols, filas)
    guardar_marcador(state_path, umbral_20)  # avanza aunque filas=[] (mantiene el marcador al día)
    return {"archivadas": len(filas), "umbral_20": umbral_20,
            "marcador_previo": marcador, "marcador_nuevo": umbral_20}


def borrar(conn: sqlite3.Connection, ahora_utc: datetime, *,
           archive_path: Path, dry_run: bool) -> dict:
    """Borra las notas de 30 días o más, ARCHIVÁNDOLAS antes (garantía por construcción de
    que nada se borra sin quedar en el JSONL — no depende del marcador). Corre bajo el lock."""
    umbral_30 = _fecha_bo(ahora_utc, BORRADO_DIAS)
    cur = conn.execute("SELECT * FROM noticias WHERE date <= ? ORDER BY date, id", (umbral_30,))
    cols = [d[0] for d in cur.description]
    filas = cur.fetchall()
    if dry_run:
        return {"borradas": len(filas), "umbral_30": umbral_30}
    if not filas:
        return {"borradas": 0, "umbral_30": umbral_30}
    # Orden crítico: archivar (append+fsync) ANTES de borrar. Un crash entremedio deja la
    # fila archivada + aún en la DB (se re-poda) — jamás borrada sin archivar. El DELETE usa
    # el mismo predicado que el SELECT: ningún writer inserta date<=umbral_30 (ingest escribe
    # la fecha de HOY; Latam gatea pubDate<=24h; la retención está bajo lock) → set estable.
    _append_jsonl(archive_path, cols, filas)
    cur = conn.execute("DELETE FROM noticias WHERE date <= ?", (umbral_30,))
    conn.commit()
    return {"borradas": cur.rowcount, "umbral_30": umbral_30}


def correr(db_path: Path, *, archive_path: Path, state_path: Path, lock_path: Path,
           dry_run: bool, ahora_utc: datetime | None = None) -> dict:
    if ahora_utc is None:
        ahora_utc = datetime.now(timezone.utc)
    with _lock(lock_path) as got:
        if not got:
            print("[retencion] otra corrida en curso (lock) → salgo no-op", file=sys.stderr)
            return {"skipped": "lock", "dry_run": dry_run}
        conn = sqlite3.connect(str(db_path))
        try:
            _chequeo_fechas(conn)
            rb = backup(conn, ahora_utc, archive_path=archive_path, state_path=state_path, dry_run=dry_run)
            rd = borrar(conn, ahora_utc, archive_path=archive_path, dry_run=dry_run)
        finally:
            conn.close()
    return {"backup": rb, "borrado": rd, "dry_run": dry_run}


def main() -> int:
    ap = argparse.ArgumentParser(description="Retención de la tabla noticias (backup 20d + borrado 30d).")
    ap.add_argument("--db", type=Path, default=NORMALIZED_DB)
    ap.add_argument("--archive", type=Path, default=ARCHIVE_DEFAULT)
    ap.add_argument("--state", type=Path, default=STATE_DEFAULT)
    ap.add_argument("--lock", type=Path, default=LOCK_DEFAULT)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    res = correr(args.db, archive_path=args.archive, state_path=args.state, lock_path=args.lock,
                 dry_run=args.dry_run)
    if res.get("skipped"):
        return 0
    rb, rd = res["backup"], res["borrado"]
    print(f"[retencion] mode={'dry-run' if args.dry_run else 'ok'} "
          f"backup archivadas={rb['archivadas']} umbral_20={rb['umbral_20']} "
          f"marcador={rb.get('marcador_nuevo')} | "
          f"borrado borradas={rd['borradas']} umbral_30={rd['umbral_30']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
