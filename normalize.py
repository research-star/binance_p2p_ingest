#!/usr/bin/env python3
"""
normalize.py — Fase 2 del proyecto Binance P2P USDT/BOB.

Lee snapshots crudos (.json / .json.gz) y produce una base SQLite
con una tabla larga: 1 fila = 1 anuncio en 1 snapshot.

Modos:
    python3 normalize.py                          # incremental (default)
    python3 normalize.py --full-rebuild           # vacía ads + reset watermark + reprocesa todo
    python3 normalize.py --since YYYY-MM-DD       # rango específico (NO toca watermark)
    python3 normalize.py --status                 # muestra watermark y pendientes

Watermark: stem del .json.gz (formato YYYYMMDDTHHMMSSZ_snapshot), comparación
lexicográfica. Equivalente al orden cronológico porque el formato es ISO-like.

Idempotente: re-correr el mismo batch produce el mismo estado de DB.
La transacción cubre todo el batch (inserts + UPDATE watermark) → un crash
a mitad rollbackea el batch entero.
"""

import argparse
import contextlib
import gzip
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from config import SNAPSHOTS_DIR, SNAPSHOTS_BACKUP_DIR, NORMALIZED_DB

# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT = SNAPSHOTS_DIR
DEFAULT_INPUT2 = SNAPSHOTS_BACKUP_DIR
DEFAULT_OUTPUT = NORMALIZED_DB
SCHEMA_VERSION_SUPPORTED = ("v1",)

WATERMARK_KEY = "last_snapshot_stem"

KYC_KEYWORDS = ["kyc", "verificad", "dni", "carnet", "selfie", "video",
                 "documento", "identidad", "cedula", "cédula"]

TAKER_RESTRICTION_FIELDS = [
    "buyerBtcPositionLimit", "buyerKycLimit", "buyerRegDaysLimit",
    "userAllTradeCountMin", "userAllTradeCountMax",
    "userBuyTradeCountMin", "userBuyTradeCountMax",
    "userSellTradeCountMin", "userSellTradeCountMax",
    "userTradeCompleteCountMin", "userTradeCompleteRateMin",
    "userTradeVolumeMin", "userTradeVolumeMax", "userTradeVolumeAsset",
]


def emit(line: str):
    """Log estructurado a stderr, una línea por evento (cron-friendly)."""
    print(line, file=sys.stderr, flush=True)


# ── Helpers crudos ──────────────────────────────────────────────────────────

def load_snapshot(path: Path) -> dict:
    if path.suffix == ".gz" or path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def stem_of(path: Path) -> str:
    """Stem usado como watermark: '20260506T031907Z_snapshot'.

    Mismo criterio de dedup que find_snapshots(): preferir un único nombre
    base por captura, sea .json o .json.gz."""
    name = path.name
    if name.endswith(".json.gz"):
        return name[:-len(".json.gz")]
    if name.endswith(".json"):
        return name[:-len(".json")]
    return name


def find_snapshots(*roots: Path) -> list[Path]:
    """Lista todos los snapshots en uno o más directorios. Deduplica por stem
    (prefiere .json.gz sobre .json, primer directorio sobre segundo)."""
    seen = {}
    for root in roots:
        if not root or not root.is_dir():
            continue
        for pat in ("**/*.json.gz", "**/*.json"):
            for p in sorted(root.glob(pat)):
                s = stem_of(p)
                if s not in seen:
                    seen[s] = p
                elif p.name.endswith(".json.gz") and not seen[s].name.endswith(".json.gz"):
                    seen[s] = p
    return sorted(seen.values(), key=stem_of)


def safe_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_int(val):
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def extract_banks(trade_methods):
    if not trade_methods:
        return []
    return [tm.get("identifier", "") for tm in trade_methods if tm.get("identifier")]


def scan_kyc_keywords(text):
    if not text:
        return []
    text_lower = text.lower()
    return [kw for kw in KYC_KEYWORDS if kw in text_lower]


def build_taker_restrictions(adv):
    out = {}
    for field in TAKER_RESTRICTION_FIELDS:
        val = adv.get(field)
        if val is not None:
            out[field] = val
    return out


def classify_quality_tier(is_merchant, month_order_count, month_finish_rate, surplus_usdt):
    """Tier A: merchant ≥100 órdenes/mes, ≥95% completado, ≥500 USDT.
       Tier B: merchant que no llega a A, o user con ≥20 órdenes/mes.
       Tier C: el resto."""
    orders = month_order_count or 0
    finish = month_finish_rate or 0.0
    surplus = surplus_usdt or 0.0

    if is_merchant and orders >= 100 and finish >= 0.95 and surplus >= 500:
        return "A"
    if is_merchant or orders >= 20:
        return "B"
    return "C"


# ── Aplanar un snapshot ────────────────────────────────────────────────────

def flatten_snapshot(snapshot: dict) -> list[dict]:
    rows = []
    ts = snapshot.get("captured_at_utc", "")
    schema_v = snapshot.get("schema_version", "?")

    if schema_v not in SCHEMA_VERSION_SUPPORTED:
        emit(f"[normalize] WARN schema={schema_v} no soportado, saltando")
        return []

    sides = snapshot.get("sides", {})
    for side_name, side_data in sides.items():
        for page_obj in side_data.get("pages", []):
            if page_obj.get("error") is not None:
                continue
            response = page_obj.get("response")
            if not response:
                continue
            ads = response.get("data", [])
            if not ads:
                continue

            for ad_wrapper in ads:
                adv = ad_wrapper.get("adv", {})
                advertiser = ad_wrapper.get("advertiser", {})

                banks = extract_banks(adv.get("tradeMethods", []))
                remarks = adv.get("remarks")
                auto_reply = adv.get("autoReplyMsg")
                kyc_kws = sorted(set(
                    scan_kyc_keywords(remarks) + scan_kyc_keywords(auto_reply)
                ))
                taker_rest = build_taker_restrictions(adv)

                is_merch = 1 if advertiser.get("userType") == "merchant" else 0
                m_orders = safe_int(advertiser.get("monthOrderCount"))
                m_finish = safe_float(advertiser.get("monthFinishRate"))
                surplus = safe_float(adv.get("surplusAmount"))
                tier = classify_quality_tier(is_merch, m_orders, m_finish, surplus)

                rows.append({
                    "snapshot_ts_utc":      ts,
                    "side":                 side_name,
                    "adv_no":               adv.get("advNo"),
                    "price":                safe_float(adv.get("price")),
                    "surplus_usdt":         surplus,
                    "tradable_quantity":    safe_float(adv.get("tradableQuantity")),
                    "min_trans_bob":        safe_float(adv.get("minSingleTransAmount")),
                    "max_trans_bob":        safe_float(adv.get("maxSingleTransAmount")),
                    "dyn_max_trans_bob":    safe_float(adv.get("dynamicMaxSingleTransAmount")),
                    "min_trans_usdt":       safe_float(adv.get("minSingleTransQuantity")),
                    "max_trans_usdt":       safe_float(adv.get("maxSingleTransQuantity")),
                    "commission_rate":      safe_float(adv.get("commissionRate")),
                    "banks":                json.dumps(banks),
                    "n_banks":              len(banks),
                    "advertiser_id":        advertiser.get("userNo"),
                    "advertiser_nick":      advertiser.get("nickName"),
                    "is_merchant":          is_merch,
                    "merchant_identity":    advertiser.get("userIdentity"),
                    "user_grade":           safe_int(advertiser.get("userGrade")),
                    "month_order_count":    m_orders,
                    "month_finish_rate":    m_finish,
                    "positive_rate":        safe_float(advertiser.get("positiveRate")),
                    "pro_merchant":         1 if advertiser.get("proMerchant") else 0,
                    "quality_tier":         tier,
                    "has_taker_restriction": 1 if taker_rest else 0,
                    "taker_restrictions":   json.dumps(taker_rest) if taker_rest else None,
                    "remarks_raw":          remarks,
                    "auto_reply_raw":       auto_reply,
                    "kyc_keywords_found":   json.dumps(kyc_kws) if kyc_kws else None,
                })
    return rows


# ── SQLite ──────────────────────────────────────────────────────────────────

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS ads (
    snapshot_ts_utc       TEXT    NOT NULL,
    side                  TEXT    NOT NULL,
    adv_no                TEXT    NOT NULL,
    price                 REAL,
    surplus_usdt          REAL,
    tradable_quantity     REAL,
    min_trans_bob         REAL,
    max_trans_bob         REAL,
    dyn_max_trans_bob     REAL,
    min_trans_usdt        REAL,
    max_trans_usdt        REAL,
    commission_rate       REAL,
    banks                 TEXT,
    n_banks               INTEGER,
    advertiser_id         TEXT,
    advertiser_nick       TEXT,
    is_merchant           INTEGER,
    merchant_identity     TEXT,
    user_grade            INTEGER,
    month_order_count     INTEGER,
    month_finish_rate     REAL,
    positive_rate         REAL,
    pro_merchant          INTEGER,
    quality_tier          TEXT,
    has_taker_restriction INTEGER,
    taker_restrictions    TEXT,
    remarks_raw           TEXT,
    auto_reply_raw        TEXT,
    kyc_keywords_found    TEXT,
    PRIMARY KEY (snapshot_ts_utc, side, adv_no)
);
"""

CREATE_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS normalize_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ads_ts ON ads(snapshot_ts_utc);",
    "CREATE INDEX IF NOT EXISTS idx_ads_side ON ads(side);",
    "CREATE INDEX IF NOT EXISTS idx_ads_advertiser ON ads(advertiser_id);",
    "CREATE INDEX IF NOT EXISTS idx_ads_price ON ads(side, price);",
    # Covering index para la query del "merchant_flow" en dashboard.py que hoy
    # hace SCAN ads. Convierte SCAN ads → SCAN COVERING INDEX.
    "CREATE INDEX IF NOT EXISTS idx_ads_flow ON ads(snapshot_ts_utc, side, advertiser_id);",
]

INSERT_ROW = """
INSERT OR REPLACE INTO ads (
    snapshot_ts_utc, side, adv_no, price, surplus_usdt, tradable_quantity,
    min_trans_bob, max_trans_bob, dyn_max_trans_bob,
    min_trans_usdt, max_trans_usdt, commission_rate,
    banks, n_banks, advertiser_id, advertiser_nick,
    is_merchant, merchant_identity, user_grade,
    month_order_count, month_finish_rate, positive_rate, pro_merchant,
    quality_tier,
    has_taker_restriction, taker_restrictions,
    remarks_raw, auto_reply_raw, kyc_keywords_found
) VALUES (
    :snapshot_ts_utc, :side, :adv_no, :price, :surplus_usdt, :tradable_quantity,
    :min_trans_bob, :max_trans_bob, :dyn_max_trans_bob,
    :min_trans_usdt, :max_trans_usdt, :commission_rate,
    :banks, :n_banks, :advertiser_id, :advertiser_nick,
    :is_merchant, :merchant_identity, :user_grade,
    :month_order_count, :month_finish_rate, :positive_rate, :pro_merchant,
    :quality_tier,
    :has_taker_restriction, :taker_restrictions,
    :remarks_raw, :auto_reply_raw, :kyc_keywords_found
);
"""


def init_db(db_path: Path) -> sqlite3.Connection:
    # isolation_level=None → manejamos BEGIN/COMMIT/ROLLBACK explícitos
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA cache_size=-65536;")  # 64 MB
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute(CREATE_TABLE)
    conn.execute(CREATE_STATE_TABLE)
    for idx_sql in CREATE_INDEXES:
        conn.execute(idx_sql)
    return conn


def read_watermark(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT value FROM normalize_state WHERE key=?", (WATERMARK_KEY,)
    ).fetchone()
    return row[0] if row else None


def write_watermark(conn: sqlite3.Connection, value: str):
    conn.execute(
        "INSERT OR REPLACE INTO normalize_state (key, value, updated_at) VALUES (?, ?, ?)",
        (WATERMARK_KEY, value, datetime.now(timezone.utc).isoformat()),
    )


# ── Lockfile (cron-safe) ───────────────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@contextlib.contextmanager
def pid_lock(lock_path: Path):
    """Lock cooperativo via O_CREAT|O_EXCL + PID file. Stale locks (PID muerto)
    se limpian automáticamente. Si hay otra instancia viva, yield None."""
    acquired = False
    fd = None
    for attempt in range(2):
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            fd = None
            acquired = True
            break
        except FileExistsError:
            try:
                old_pid = int(lock_path.read_text().strip())
            except (ValueError, OSError):
                old_pid = -1
            if old_pid > 0 and _pid_alive(old_pid):
                break
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
            continue
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


# ── Pipeline core ──────────────────────────────────────────────────────────

def process_files(conn: sqlite3.Connection, files: list[Path], *,
                  advance_watermark: bool, mode_label: str) -> dict:
    """Procesa archivos en una única transacción. Si advance_watermark, escribe
    el max(stem) procesado en normalize_state. Devuelve métricas."""
    t0 = time.time()
    inserted = 0
    failed = 0
    new_watermark = max((stem_of(f) for f in files), default=None) if files else None
    old_watermark = read_watermark(conn)

    conn.execute("BEGIN IMMEDIATE")
    try:
        for fp in files:
            try:
                snap = load_snapshot(fp)
                rows = flatten_snapshot(snap)
                if rows:
                    conn.executemany(INSERT_ROW, rows)
                    inserted += len(rows)
            except Exception as e:
                emit(f"[normalize] WARN file={fp.name} error={type(e).__name__}: {e}")
                failed += 1
        if advance_watermark and new_watermark:
            write_watermark(conn, new_watermark)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    duration = time.time() - t0
    return {
        "mode": mode_label,
        "files_total": len(files),
        "files_failed": failed,
        "records_inserted": inserted,
        "watermark_start": old_watermark,
        "watermark_end": new_watermark if advance_watermark else old_watermark,
        "duration_s": round(duration, 2),
    }


def emit_run_log(metrics: dict, suffix: str = ""):
    parts = [
        f"mode={metrics['mode']}",
        f"watermark_start={metrics['watermark_start']}",
        f"watermark_end={metrics['watermark_end']}",
        f"files_processed={metrics['files_total']}",
        f"files_failed={metrics['files_failed']}",
        f"records_inserted={metrics['records_inserted']}",
        f"duration_s={metrics['duration_s']}",
    ]
    line = "[normalize] " + " ".join(parts)
    if suffix:
        line += " " + suffix
    emit(line)


# ── Comandos ───────────────────────────────────────────────────────────────

def cmd_status(conn: sqlite3.Connection, all_files: list[Path]) -> int:
    wm = read_watermark(conn)
    pending = [f for f in all_files if stem_of(f) > (wm or "")]
    n_rows = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
    n_ts = conn.execute("SELECT COUNT(DISTINCT snapshot_ts_utc) FROM ads").fetchone()[0]
    print(f"watermark        : {wm or '(vacío)'}")
    print(f"snapshots en disco: {len(all_files)}")
    print(f"snapshots pendientes: {len(pending)}")
    if pending[:3]:
        print(f"primeros pendientes: {[stem_of(p) for p in pending[:3]]}")
    print(f"filas en ads     : {n_rows}")
    print(f"distinct ts en ads: {n_ts}")
    return 0


def cmd_full_rebuild(conn: sqlite3.Connection, all_files: list[Path]) -> int:
    emit("[normalize] full-rebuild: vaciando ads y reseteando watermark")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM ads")
        conn.execute("DELETE FROM normalize_state WHERE key=?", (WATERMARK_KEY,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    metrics = process_files(conn, all_files,
                            advance_watermark=True, mode_label="full-rebuild")
    emit_run_log(metrics)
    return 0


def cmd_incremental(conn: sqlite3.Connection, all_files: list[Path]) -> int:
    wm = read_watermark(conn)
    if wm is None:
        emit("[normalize] ERROR watermark vacío. Corré primero: "
             "python normalize.py --full-rebuild")
        return 2

    pending = [f for f in all_files if stem_of(f) > wm]
    if not pending:
        emit(f"[normalize] mode=incremental watermark={wm} files_processed=0 "
             f"records_inserted=0 duration_s=0.0 (no work)")
        return 0

    metrics = process_files(conn, pending,
                            advance_watermark=True, mode_label="incremental")
    emit_run_log(metrics)
    return 0


def cmd_since(conn: sqlite3.Connection, all_files: list[Path], since: str) -> int:
    try:
        datetime.strptime(since, "%Y-%m-%d")
    except ValueError:
        emit(f"[normalize] ERROR --since requiere formato YYYY-MM-DD, recibido: {since}")
        return 2
    prefix = since.replace("-", "")  # YYYYMMDD; lex compara contra YYYYMMDDTHHMMSSZ_*
    target = [f for f in all_files if stem_of(f) >= prefix]
    if not target:
        emit(f"[normalize] mode=since since={since} files_processed=0 (no match)")
        return 0
    metrics = process_files(conn, target,
                            advance_watermark=False, mode_label="since")
    emit_run_log(metrics, suffix=f"since={since}")
    return 0


# ── Sanity checks (sólo cuando se piden) ───────────────────────────────────

def run_sanity_checks(conn: sqlite3.Connection):
    print("\n--- Sanity checks ---")
    total = conn.execute("SELECT COUNT(*) FROM ads").fetchone()[0]
    print(f"  Total filas: {total}")
    rows = conn.execute("""
        SELECT snapshot_ts_utc, side, COUNT(*),
               ROUND(MIN(price),2), ROUND(MAX(price),2),
               ROUND(SUM(surplus_usdt),0)
        FROM ads
        GROUP BY snapshot_ts_utc, side
        ORDER BY snapshot_ts_utc DESC, side
        LIMIT 6
    """).fetchall()
    print(f"  Últimos snapshots × side (top 6):")
    for ts, side, cnt, pmin, pmax, depth in rows:
        print(f"    {ts} | {side:4s} | {cnt:4d} ads | "
              f"price [{pmin} – {pmax}] | depth {depth:,.0f} USDT")

    m = conn.execute("SELECT is_merchant, COUNT(*) FROM ads GROUP BY is_merchant").fetchall()
    m_dict = {row[0]: row[1] for row in m}
    print(f"  Merchants: {m_dict.get(1,0)}  |  Users: {m_dict.get(0,0)}")
    tiers = conn.execute("""
        SELECT side, quality_tier, COUNT(*) FROM ads
        GROUP BY side, quality_tier ORDER BY side, quality_tier
    """).fetchall()
    print("  Quality tier por side:")
    for side, tier, cnt in tiers:
        print(f"    {side:4s} | Tier {tier}: {cnt}")
    null_price = conn.execute("SELECT COUNT(*) FROM ads WHERE price IS NULL").fetchone()[0]
    null_surplus = conn.execute("SELECT COUNT(*) FROM ads WHERE surplus_usdt IS NULL").fetchone()[0]
    if null_price or null_surplus:
        print(f"  [WARN] Nulls inesperados: price={null_price}, surplus={null_surplus}")
    else:
        print("  Sin nulls en price/surplus [OK]")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Normaliza snapshots P2P a SQLite (incremental por default)")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"Directorio principal con snapshots (default: {DEFAULT_INPUT})")
    parser.add_argument("--input2", type=Path, default=DEFAULT_INPUT2,
                        help="Segundo directorio (default: $P2P_BACKUP_DIR si existe)")
    parser.add_argument("--no-input2", action="store_true",
                        help="No usar segundo directorio")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Archivo SQLite de salida (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Vacía ads, resetea watermark y reprocesa todo")
    parser.add_argument("--since", type=str, default=None,
                        help="Procesa archivos con stem >= YYYY-MM-DD (NO toca watermark)")
    parser.add_argument("--status", action="store_true",
                        help="Muestra watermark y pendientes; no procesa nada")
    parser.add_argument("--sanity-checks", action="store_true",
                        help="Imprime sanity checks tras procesar")
    args = parser.parse_args()

    # Resolver fuentes
    if args.input.is_file():
        all_files = [args.input]
    else:
        dirs = [args.input]
        if not args.no_input2:
            dirs.append(args.input2)
        all_files = find_snapshots(*dirs)

    if not all_files:
        emit("[normalize] ERROR no se encontraron snapshots")
        return 1

    lock_path = args.output.with_name(args.output.name + ".lock")
    with pid_lock(lock_path) as acquired:
        if not acquired:
            emit(f"[normalize] otra instancia activa (lock={lock_path.name}), saliendo limpio")
            return 0

        conn = init_db(args.output)
        try:
            if args.status:
                rc = cmd_status(conn, all_files)
            elif args.full_rebuild:
                rc = cmd_full_rebuild(conn, all_files)
            elif args.since:
                rc = cmd_since(conn, all_files, args.since)
            else:
                rc = cmd_incremental(conn, all_files)

            if args.sanity_checks and rc == 0 and not args.status:
                run_sanity_checks(conn)
        finally:
            conn.close()
        return rc


if __name__ == "__main__":
    sys.exit(main())
