#!/usr/bin/env bash
# Wrapper para correr ingest_bcb_tco.py y commitear el JSON si cambió.
# Invocado desde el cron del VPS (lun-vie 20:10 BO = 00:10 UTC mar-sáb).
# El TCO se publica a las 20:00 BO y es vigente al día siguiente; corremos 10 min
# después para darle margen al BCB a subirlo.
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
