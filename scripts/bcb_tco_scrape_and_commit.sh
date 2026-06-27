#!/usr/bin/env bash
# Wrapper para correr ingest_bcb_tco.py y commitear el JSON si cambió.
# Invocado desde el cron del VPS (lun-vie 20:05 BO = 00:05 UTC mar-sáb).
# El TCO se publica a las 20:00 BO; corremos 5 min después. El scraper baja una
# ventana móvil de 7 días (autorreparable: si una corrida cae muy temprano y el
# BCB aún no subió el dato, la del día siguiente lo recupera).
# Primera corrida / backfill del histórico: ejecutar a mano una vez con
#   .venv/bin/python ingest_bcb_tco.py --backfill
set -euo pipefail
cd /opt/binance_p2p
.venv/bin/python ingest_bcb_tco.py
if ! git diff --quiet bcb_tco.json; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_tco.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape TCO $(date -u +%Y-%m-%dT%H:%MZ)"
  git push origin "$CURRENT_BRANCH"
fi
