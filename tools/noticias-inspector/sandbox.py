"""Hermetic sandbox for the Noticias Inspector.

The inspector NEVER writes the real DBs. Each run:
  - builds a fresh sandbox `noticias.db` via the REAL ingest_noticias.init_schema
    (so the `tambien_en` column the real p2p_normalized.db still lacks exists),
  - seeds the last SEED_DIAS of `noticias` + `noticias_hidden` rows from the real
    p2p_normalized.db opened READ-ONLY (so inter-day dedupe + rolling budget match),
  - copies the real cache_urls.db into the sandbox (fidelity to prod's ya_vista
    skips); all `marcar` writes go to the copy, never the real cache.

Hermeticity is provable: fingerprint the real DBs before/after — they must be
byte-identical (acceptance #2).
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import insp_config as config  # noqa: E402  (sets sys.path to repo root; named to NOT shadow repo config.py)

import ingest_noticias  # real init_schema  (REGLA DURA: imported, not reimplemented)


def file_fingerprint(path: Path, full_hash: bool = False) -> dict:
    """Cheap fingerprint (size+mtime) + optional full sha256. Used to prove the
    real DBs are untouched across runs."""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "size": 0, "mtime": 0, "sha256": None}
    st = p.stat()
    out = {"exists": True, "size": st.st_size, "mtime": int(st.st_mtime), "sha256": None}
    if full_hash:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out["sha256"] = h.hexdigest()
    return out


def real_db_fingerprints(full_hash: bool = False) -> dict:
    return {
        "p2p_normalized.db": file_fingerprint(config.REAL_DB, full_hash),
        "cache_urls.db": file_fingerprint(config.REAL_CACHE, full_hash),
    }


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _seed_table(real_ro: sqlite3.Connection, sand: sqlite3.Connection, table: str, where: str = "") -> int:
    """Copy `table` rows from the read-only real DB into the sandbox using only the
    column intersection (the real `noticias` table lacks columns the new DDL adds)."""
    try:
        real_cols = _columns(real_ro, table)
    except sqlite3.Error:
        return 0
    if not real_cols:
        return 0
    sand_cols = _columns(sand, table)
    cols = [c for c in real_cols if c in sand_cols]
    if not cols:
        return 0
    collist = ", ".join(cols)
    rows = real_ro.execute(f"SELECT {collist} FROM {table} {where}").fetchall()
    if rows:
        ph = ", ".join("?" for _ in cols)
        sand.executemany(f"INSERT OR IGNORE INTO {table} ({collist}) VALUES ({ph})", rows)
    return len(rows)


def build_sandbox() -> dict:
    """Create a fresh hermetic sandbox. Returns paths + seed counts."""
    config.SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    db_path = config.SANDBOX_DIR / "noticias.db"
    cache_path = config.SANDBOX_DIR / "cache_urls.db"

    for p in (db_path, cache_path):
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(p) + suffix)
            if f.exists():
                f.unlink()

    sand = sqlite3.connect(str(db_path))
    seeded = {"noticias": 0, "noticias_hidden": 0}
    try:
        ingest_noticias.init_schema(sand)  # REAL schema (adds tambien_en etc.)
        if config.REAL_DB.exists():
            ro = sqlite3.connect(f"file:{config.REAL_DB}?mode=ro", uri=True)
            try:
                ro.execute("PRAGMA query_only = ON")
                # Seed ALL noticias rows. The local p2p_normalized.db is a possibly-stale
                # mirror (laptop ingest disabled; real recent rows live on the VPS — out of
                # scope). The noticias table is small (~14/day), so a full copy is cheap and
                # robust to staleness; the pipeline's own date filters (titulos_recientes
                # last DEDUPE_DIAS, budget COUNT WHERE date=today) apply the real windows.
                seeded["noticias"] = _seed_table(ro, sand, "noticias")
                seeded["noticias_hidden"] = _seed_table(ro, sand, "noticias_hidden")
            finally:
                ro.close()
        sand.commit()
    finally:
        sand.close()

    # Cache: re-seed from the real cache each run (fidelity to prod ya_vista skips);
    # all writes land on this copy, never the real cache.
    if config.REAL_CACHE.exists():
        shutil.copy2(config.REAL_CACHE, cache_path)
        cache_seeded = "copied-from-real"
    else:
        cache_seeded = "fresh-empty (real cache absent)"

    return {
        "db_path": db_path,
        "cache_path": cache_path,
        "seeded": seeded,
        "cache": cache_seeded,
    }
