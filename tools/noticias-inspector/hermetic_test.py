"""HERMETICITY TEST (acceptance #2).

Does exactly what a real inspector run does to the productive DBs — build_sandbox() seeds
from p2p_normalized.db opened READ-ONLY and copies cache_urls.db into the sandbox; the real
lane_bolivia then writes only the sandbox — N times, and proves the real
p2p_normalized.db + cache_urls.db are byte-identical afterwards (full sha256).

Run:  FB_DATA_ROOT=<checkout-with-data> python hermetic_test.py
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import insp_config as cfg
import sandbox
import inspector_core as core
import ingest_noticias as ing
import parity_test

N = 3


def run():
    if not cfg.REAL_DB.exists():
        print(f"SKIP hermetic_test: real DB not found at {cfg.REAL_DB} "
              f"(set FB_DATA_ROOT to a checkout that has p2p_normalized.db).")
        return 0

    snap = parity_test.build_snapshot()
    ahora = datetime(2026, 6, 23, 16, 0, 0, tzinfo=timezone.utc)
    fecha_bo = ahora.astimezone(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d")
    args = SimpleNamespace(umbral=ing.UMBRAL_PUNTAJE, top=ing.TOP_N, top_latam=ing.LATAM_TOP_N, dry_run=False)

    print(f"hashing real DBs (before)… p2p={cfg.REAL_DB.stat().st_size/1e6:.0f}MB")
    before = sandbox.real_db_fingerprints(full_hash=True)

    for i in range(N):
        info = sandbox.build_sandbox()
        conn = sqlite3.connect(str(info["db_path"]))
        try:
            with core.harness(info["cache_path"], snapshot=snap):
                previos = ing.titulos_recientes(conn)
                ing.lane_bolivia(conn, args, ahora, fecha_bo, previos)  # REAL lane, writes sandbox only
        finally:
            conn.close()
        print(f"  run {i+1}/{N}: sandbox built + real lane_bolivia executed")

    print("hashing real DBs (after)…")
    after = sandbox.real_db_fingerprints(full_hash=True)

    errors = []
    for k in before:
        b, a = before[k], after[k]
        same = (b["sha256"] == a["sha256"] and b["size"] == a["size"])
        flag = "OK " if same else "CHANGED"
        print(f"  [{flag}] {k}: size {b['size']} sha {str(b['sha256'])[:16]}… -> {str(a['sha256'])[:16]}…")
        if not same:
            errors.append(k)

    if errors:
        print(f"\nFAIL hermetic_test: real DB(s) MUTATED: {errors}")
        return 1
    print(f"\nOK hermetic_test: tras {N} corridas, p2p_normalized.db y cache_urls.db byte-idénticos "
          f"(sha256). Todo lo escrito vivió en sandbox/.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
