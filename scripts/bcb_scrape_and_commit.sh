#!/usr/bin/env bash
# Wrapper para correr bcb_referencial.py y commitear el JSON si cambió.
# Invocado desde el cron del VPS (lun-vie 8:05–11:35 BO).
set -euo pipefail
cd /opt/binance_p2p
.venv/bin/python bcb_referencial.py
if ! git diff --quiet bcb_referencial.json; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_referencial.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape $(date -u +%Y-%m-%dT%H:%MZ)"
  git push origin "$CURRENT_BRANCH"
fi
