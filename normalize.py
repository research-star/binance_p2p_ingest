#!/usr/bin/env python3
"""
normalize.py — Fase 2 del proyecto Binance P2P USDT/BOB.

Lee snapshots crudos (.json / .json.gz) y produce una base SQLite
con una tabla larga: 1 fila = 1 anuncio en 1 snapshot.

Uso:
    python3 normalize.py                          # busca en snapshots/ + backup (si hay)
    python3 normalize.py --no-input2              # solo snapshots/ local
    python3 normalize.py --input /ruta/custom      # ruta custom (principal)
    python3 normalize.py --output mi_base.db       # nombre custom de salida
    python3 normalize.py --export-csv              # también escupe CSV

Idempotente: re-correr sobre los mismos archivos da el mismo resultado.
"""

import argparse
import gzip
import json
import os
import sqlite3
import sys
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_INPUT = Path("snapshots")
# Directorio de backup opcional (p. ej. OneDrive, Dropbox, disco externo).
# Configurable vía env var P2P_BACKUP_DIR. Si no existe, se ignora silenciosamente.
DEFAULT_INPUT2 = Path(os.environ.get("P2P_BACKUP_DIR", "")) if os.environ.get("P2P_BACKUP_DIR") else Path("snapshots_backup_not_configured")
DEFAULT_OUTPUT = Path("p2p_normalized.db")
SCHEMA_VERSION_SUPPORTED = ("v1",)

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

# ── Helpers ─────────────────────────────────────────────────────────────────

def load_snapshot(path: Path) -> dict:
    if path.suffix == ".gz" or path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    else:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)


def find_snapshots(*roots: Path) -> list[Path]:
    """Busca snapshots en uno o más directorios. Deduplica por nombre de archivo
    (prefiere .json.gz sobre .json, y el primer directorio sobre el segundo)."""
    seen = {}  # filename_stem -> Path
    for root in roots:
        if not root.is_dir():
            continue
        for pat in ["**/*.json.gz", "**/*.json"]:
            for p in sorted(root.glob(pat)):
                stem = p.name.replace(".json.gz", "").replace(".json", "")
                if stem not in seen:
                    seen[stem] = p
                elif p.name.endswith(".json.gz") and not seen[stem].name.endswith(".json.gz"):
                    seen[stem] = p
    return sorted(seen.values())


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
    restrictions = {}
    for field in TAKER_RESTRICTION_FIELDS:
        val = adv.get(field)
        if val is not None:
            restrictions[field] = val
    return restrictions


def classify_quality_tier(is_merchant, month_order_count, month_finish_rate, surplus_usdt):
    """
    Tier A: merchant con ≥100 órdenes/mes, ≥95% completado, ≥500 USDT surplus
    Tier B: merchant que no llega a A, o user con ≥20 órdenes/mes
    Tier C: todo lo demás
    """
    orders = month_order_count or 0
    finish = month_finish_rate or 0.0
    surplus = surplus_usdt or 0.0

    if is_merchant and orders >= 100 and finish >= 0.95 and surplus >= 500:
        return "A"
    if is_merchant or orders >= 20:
        return "B"
    return "C"


# ── Core: aplanar un snapshot ───────────────────────────────────────────────

def flatten_snapshot(snapshot: dict) -> list[dict]:
    rows = []
    ts = snapshot.get("captured_at_utc", "")
    schema_v = snapshot.get("schema_version", "?")

    if schema_v not in SCHEMA_VERSION_SUPPORTED:
        print(f"  [WARN] Schema {schema_v} no soportado, saltando.", file=sys.stderr)
        return []

    sides = snapshot.get("sides", {})
    for side_name, side_data in sides.items():
        pages = side_data.get("pages", [])
        for page_obj in pages:
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

                row = {
                    "snapshot_ts_utc":      ts,
                    "side":                 side_name,
                    "adv_no":               adv.get("advNo"),
                    "price":                safe_float(adv.get("price")),
                    "surplus_usdt":         surplus,
                    "tradable_quantity":     safe_float(adv.get("tradableQuantity")),
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
                }
                rows.append(row)

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

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ads_ts ON ads(snapshot_ts_utc);",
    "CREATE INDEX IF NOT EXISTS idx_ads_side ON ads(side);",
    "CREATE INDEX IF NOT EXISTS idx_ads_advertiser ON ads(advertiser_id);",
    "CREATE INDEX IF NOT EXISTS idx_ads_price ON ads(side, price);",
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
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(CREATE_TABLE)
    for idx_sql in CREATE_INDEXES:
        conn.execute(idx_sql)
    conn.commit()
    return conn


# ── Sanity checks ──────────────────────────────────────────────────────────

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
        ORDER BY snapshot_ts_utc, side
    """).fetchall()
    print(f"  Snapshots × side: {len(rows)}")
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

    with_rest = conn.execute(
        "SELECT COUNT(*) FROM ads WHERE has_taker_restriction=1"
    ).fetchone()[0]
    print(f"  Con restricción estructurada al taker: {with_rest}")

    with_kyc = conn.execute(
        "SELECT COUNT(*) FROM ads WHERE kyc_keywords_found IS NOT NULL"
    ).fetchone()[0]
    print(f"  Con keywords KYC en texto libre: {with_kyc}")

    null_price = conn.execute("SELECT COUNT(*) FROM ads WHERE price IS NULL").fetchone()[0]
    null_surplus = conn.execute("SELECT COUNT(*) FROM ads WHERE surplus_usdt IS NULL").fetchone()[0]
    if null_price or null_surplus:
        print(f"  [WARN] Nulls inesperados: price={null_price}, surplus={null_surplus}")
    else:
        print("  Sin nulls en price/surplus [OK]")


# ── CSV export ──────────────────────────────────────────────────────────────

def export_csv(conn: sqlite3.Connection, csv_path: Path):
    import csv
    cursor = conn.execute("SELECT * FROM ads ORDER BY snapshot_ts_utc, side, price")
    cols = [desc[0] for desc in cursor.description]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        writer.writerows(cursor)
    print(f"\n  CSV exportado: {csv_path} ({csv_path.stat().st_size / 1024:.1f} KB)")


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Normaliza snapshots P2P a SQLite")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help=f"Directorio principal con snapshots (default: {DEFAULT_INPUT})")
    parser.add_argument("--input2", type=Path, default=DEFAULT_INPUT2,
                        help=f"Segundo directorio de snapshots (default: $P2P_BACKUP_DIR si está definido)")
    parser.add_argument("--no-input2", action="store_true",
                        help="No usar segundo directorio")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help=f"Archivo SQLite de salida (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--export-csv", action="store_true",
                        help="También exportar a CSV")
    args = parser.parse_args()

    if args.input.is_file():
        snapshot_files = [args.input]
    else:
        dirs = [args.input]
        if not args.no_input2:
            dirs.append(args.input2)
        snapshot_files = find_snapshots(*dirs)

    if not snapshot_files:
        print(f"No se encontraron snapshots", file=sys.stderr)
        sys.exit(1)

    sources = [str(args.input)]
    if not args.no_input2 and args.input2.is_dir():
        sources.append(str(args.input2))
    print(f"Fuentes: {' + '.join(sources)}")
    print(f"Encontrados {len(snapshot_files)} snapshot(s) unicos")

    # Borrar DB anterior para idempotencia
    if args.output.exists():
        args.output.unlink()
        print("  (DB anterior borrada para idempotencia)")

    conn = init_db(args.output)
    total_rows = 0

    for snap_path in snapshot_files:
        print(f"  Procesando: {snap_path.name} ...", end=" ")
        try:
            snapshot = load_snapshot(snap_path)
            rows = flatten_snapshot(snapshot)
            if rows:
                conn.executemany(INSERT_ROW, rows)
                conn.commit()
            print(f"{len(rows)} filas")
            total_rows += len(rows)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)

    print(f"\n[OK] {total_rows} filas escritas en {args.output}")
    run_sanity_checks(conn)

    if args.export_csv:
        csv_path = args.output.with_suffix(".csv")
        export_csv(conn, csv_path)

    conn.close()


if __name__ == "__main__":
    main()
