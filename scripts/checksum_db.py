#!/usr/bin/env python3
"""
checksum_db.py — Hash determinístico de p2p_normalized.db.

Para validar bit-identidad entre el output del normalize.py viejo y el nuevo
bajo --full-rebuild. Recorre la tabla `ads` ordenada por PK y emite un sha256
por columna + un sha256 global. Independiente del orden físico de inserción.

Uso:
    python scripts/checksum_db.py p2p_baseline_old.db
    python scripts/checksum_db.py p2p_baseline_old.db p2p_normalized.db   # diff
"""

import hashlib
import sqlite3
import sys
from pathlib import Path


def column_checksums(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ads)").fetchall()]
    if not cols:
        conn.close()
        raise RuntimeError(f"{db_path}: tabla ads vacía o inexistente")

    hashers = {c: hashlib.sha256() for c in cols}
    global_h = hashlib.sha256()
    n = 0
    cur = conn.execute(
        f"SELECT {', '.join(cols)} FROM ads ORDER BY snapshot_ts_utc, side, adv_no"
    )
    for row in cur:
        for col, val in zip(cols, row):
            b = b"\x00NULL\x00" if val is None else str(val).encode("utf-8")
            hashers[col].update(b)
            hashers[col].update(b"\x1f")
            global_h.update(b)
            global_h.update(b"\x1f")
        global_h.update(b"\x1e")
        n += 1
    conn.close()
    return {
        "n_rows": n,
        "global": global_h.hexdigest(),
        "by_col": {c: h.hexdigest() for c, h in hashers.items()},
    }


def main():
    if len(sys.argv) < 2:
        print("uso: checksum_db.py <db1> [<db2>]", file=sys.stderr)
        sys.exit(2)

    paths = [Path(p) for p in sys.argv[1:3]]
    results = []
    for p in paths:
        if not p.exists():
            print(f"ERROR: {p} no existe", file=sys.stderr)
            sys.exit(1)
        r = column_checksums(p)
        results.append(r)
        print(f"\n=== {p} ===")
        print(f"  n_rows:  {r['n_rows']}")
        print(f"  global:  {r['global']}")
        for col, h in r["by_col"].items():
            print(f"    {col:24s} {h}")

    if len(results) == 2:
        print("\n=== DIFF ===")
        a, b = results
        if a["global"] == b["global"]:
            print(f"  IDENTICAL  (n_rows={a['n_rows']}, global={a['global'][:16]}...)")
        else:
            print(f"  DIFFER  n_rows={a['n_rows']} vs {b['n_rows']}")
            for col in a["by_col"]:
                if a["by_col"][col] != b["by_col"][col]:
                    print(f"    DIFF en columna: {col}")


if __name__ == "__main__":
    main()
