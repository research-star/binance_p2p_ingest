"""
config.py — Constantes compartidas del proyecto Binance P2P USDT/BOB.

Centraliza valores que cruzan varios scripts: tipos de cambio referenciales,
rutas default de entrada/salida, intervalos del loop de ingesta y umbrales
del watchdog. Los scripts importan de aquí en lugar de redefinir.

Las constantes específicas de un solo módulo (ej. parámetros del POST a
Binance, keywords de KYC, fields de restricciones del taker) viven en sus
respectivos archivos.
"""

import os
from pathlib import Path

# ── Tipo de cambio oficial (referencia para prima paralela) ─────────────────
BCB_RATE = 6.96

# ── Rutas default (relativas a la raíz del proyecto / cwd) ──────────────────
SNAPSHOTS_DIR = Path("snapshots")
LOGS_DIR = Path("logs")
NORMALIZED_DB = Path("p2p_normalized.db")
DASHBOARD_HTML = Path("index.html")
BCB_REF_JSON = Path("bcb_referencial.json")
TEMPLATE_HTML = Path(__file__).parent / "template.html"

# Backup opcional de snapshots (env var P2P_BACKUP_DIR). Si no está definida
# o la ruta no existe, normalize.py la ignora silenciosamente.
_backup_env = os.environ.get("P2P_BACKUP_DIR", "").strip()
SNAPSHOTS_BACKUP_DIR = Path(_backup_env) if _backup_env else Path("snapshots_backup_not_configured")

# ── Loop de ingesta ─────────────────────────────────────────────────────────
INGEST_INTERVAL_S = 600  # 10 min

# ── Watchdog ────────────────────────────────────────────────────────────────
WATCHDOG_STALE_MIN = 15
