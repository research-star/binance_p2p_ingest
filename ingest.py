#!/usr/bin/env python3
"""
Binance P2P USDT/BOB — Fase 1: Ingesta cruda

Captura snapshots completos del libro P2P (BUY + SELL) cada vez que se ejecuta.
Guarda JSON crudo gzipeado, sin transformar nada. Pensado para que Fase 2 y 3
puedan reconstruir cualquier analisis desde los datos originales.

Uso:
  python ingest.py                         # una captura y salir
  python ingest.py --loop                  # loop cada 10 min dentro del proceso
  python ingest.py --loop --interval 300   # loop con intervalo custom (segundos)
  python ingest.py --dry-run               # prueba sin escribir a disco

Para cron (Linux/Mac):
  */10 * * * * cd /ruta/al/proyecto && /usr/bin/python3 ingest.py

Para Windows Task Scheduler:
  Crear tarea que ejecute `python.exe ingest.py` cada 10 min en el directorio
  del proyecto.
"""

import argparse
import gzip
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from config import SNAPSHOTS_DIR, LOGS_DIR, INGEST_INTERVAL_S

# ---------- Config ----------
ENDPOINT = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSET = "USDT"
FIAT = "BOB"
ROWS_PER_PAGE = 20
MAX_PAGES = 50          # safety cap por lado, Bolivia deberia estar muy por debajo
REQUEST_TIMEOUT_S = 15
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = [1, 3, 9]
PAGE_DELAY_S = 0.4      # pausa entre paginas del mismo lado
SIDE_DELAY_S = 1.0      # pausa entre BUY y SELL
SCHEMA_VERSION = "v1"

OUTPUT_ROOT = SNAPSHOTS_DIR
LOG_FILE = LOGS_DIR / "ingest.log"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Origin": "https://p2p.binance.com",
    "Referer": "https://p2p.binance.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
}

# Parametros del POST que se mandan a Binance.
# Deliberadamente NO filtramos nada en origen: queremos TODO el libro.
# Los filtros (KYC, merchant, banco, etc.) se aplican en Fase 2 sobre la data cruda.
BASE_PARAMS = {
    "asset": ASSET,
    "fiat": FIAT,
    "merchantCheck": False,
    "proMerchantAds": False,
    "shieldMerchantAds": False,
    "publisherType": None,
    "payTypes": [],
    "countries": [],
    "additionalKycVerifyFilter": 0,
    "classifies": ["mass", "profession", "fiat_trade"],
    "filterType": "all",
    "periods": [],
    "transAmount": "",
}


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def fetch_page(side: str, page: int) -> dict:
    """
    Intenta traer una pagina con reintentos y backoff.
    Devuelve siempre un dict con metadata. Si todo falla, el dict lleva 'error'
    y 'response' = None, pero NUNCA lanza excepcion: queremos registrar huecos,
    no perderlos en silencio.
    """
    payload = {**BASE_PARAMS, "tradeType": side, "page": page, "rows": ROWS_PER_PAGE}
    last_error = None
    latency_ms = None

    for attempt in range(RETRY_ATTEMPTS):
        t0 = time.time()
        try:
            r = requests.post(
                ENDPOINT,
                json=payload,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT_S,
            )
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return {
                    "page": page,
                    "http_status": 200,
                    "latency_ms": latency_ms,
                    "attempt": attempt + 1,
                    "response": r.json(),
                    "error": None,
                }
            last_error = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            last_error = f"{type(e).__name__}: {e}"

        if attempt < RETRY_ATTEMPTS - 1:
            time.sleep(RETRY_BACKOFF_S[attempt])

    return {
        "page": page,
        "http_status": None,
        "latency_ms": latency_ms,
        "attempt": RETRY_ATTEMPTS,
        "response": None,
        "error": last_error,
    }


def fetch_side(side: str) -> dict:
    """
    Pagina un lado completo (BUY o SELL) hasta agotar resultados o fallar.
    Criterios de parada:
      - pagina con menos de ROWS_PER_PAGE resultados  -> ultima pagina
      - pagina con error                               -> cortar y registrar
      - success=False                                  -> cortar y registrar
      - MAX_PAGES alcanzado                            -> cortar con warning
    """
    pages = []
    total_declared = None
    stop_reason = None

    for page in range(1, MAX_PAGES + 1):
        result = fetch_page(side, page)
        pages.append(result)

        if result["error"]:
            logging.warning(f"{side} page {page} fallo: {result['error']}")
            stop_reason = "error"
            break

        response = result["response"]
        if not response.get("success", False):
            logging.warning(f"{side} page {page} devolvio success=false")
            stop_reason = "success_false"
            break

        if total_declared is None:
            total_declared = response.get("total")

        ads = response.get("data") or []
        logging.info(
            f"{side} page {page}: {len(ads)} anuncios "
            f"(latency {result['latency_ms']}ms, total declarado={total_declared})"
        )

        if len(ads) < ROWS_PER_PAGE:
            stop_reason = "last_page"
            break

        time.sleep(PAGE_DELAY_S)
    else:
        logging.warning(f"{side} alcanzo MAX_PAGES={MAX_PAGES}, hay mas data sin capturar")
        stop_reason = "max_pages_reached"

    return {
        "request_params_template": {
            **BASE_PARAMS,
            "tradeType": side,
            "rows": ROWS_PER_PAGE,
        },
        "pages": pages,
        "total_declared_by_api": total_declared,
        "stop_reason": stop_reason,
    }


def capture_snapshot(dry_run: bool = False) -> Path | None:
    """Captura un snapshot completo (BUY + SELL) y lo escribe a disco."""
    captured_at = datetime.now(timezone.utc)
    stamp = captured_at.strftime("%Y%m%dT%H%M%SZ")
    logging.info(f"=== Snapshot {stamp} START ===")

    t_start = time.time()
    buy = fetch_side("BUY")
    time.sleep(SIDE_DELAY_S)
    sell = fetch_side("SELL")
    duration_s = round(time.time() - t_start, 2)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "captured_at_utc": captured_at.isoformat().replace("+00:00", "Z"),
        "capture_duration_s": duration_s,
        "endpoint": ENDPOINT,
        "asset": ASSET,
        "fiat": FIAT,
        "sides": {"BUY": buy, "SELL": sell},
    }

    if dry_run:
        buy_ads = sum(len((p["response"] or {}).get("data") or []) for p in buy["pages"])
        sell_ads = sum(len((p["response"] or {}).get("data") or []) for p in sell["pages"])
        logging.info(
            f"[DRY RUN] snapshot listo, NO escrito. "
            f"BUY={buy_ads} ads, SELL={sell_ads} ads, duracion={duration_s}s"
        )
        return None

    day_dir = OUTPUT_ROOT / captured_at.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / f"{stamp}_snapshot.json.gz"

    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)

    size_kb = out_path.stat().st_size / 1024
    logging.info(f"=== Snapshot {stamp} OK -> {out_path} ({size_kb:.1f} KB, {duration_s}s) ===")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Ingesta Fase 1 Binance P2P USDT/BOB")
    parser.add_argument("--loop", action="store_true", help="Correr en loop dentro del proceso")
    parser.add_argument(
        "--interval",
        type=int,
        default=INGEST_INTERVAL_S,
        help=f"Segundos entre snapshots en modo loop (default {INGEST_INTERVAL_S} = 10 min)",
    )
    parser.add_argument("--dry-run", action="store_true", help="No escribir a disco")
    args = parser.parse_args()

    setup_logging()
    logging.info(f"Python {sys.version.split()[0]}, ingest.py schema {SCHEMA_VERSION}")

    if not args.loop:
        capture_snapshot(dry_run=args.dry_run)
        return

    logging.info(f"Modo loop activo, interval={args.interval}s. Ctrl+C para detener.")
    try:
        while True:
            try:
                capture_snapshot(dry_run=args.dry_run)
            except Exception as e:
                logging.exception(f"Snapshot fallo con excepcion no capturada: {e}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logging.info("Loop detenido por el usuario. Chau.")


if __name__ == "__main__":
    main()
