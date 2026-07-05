#!/usr/bin/env bash
# Wrapper para correr ingest_asfi.py y commitear los JSON de data si cambiaron.
# Invocado desde el cron del VPS. Idempotente: si no hay reporte nuevo (feriado,
# ASFI aún no publicó), el ingest no toca archivos y acá no se commitea nada.
# El PDF baja vía proxy residencial con exit Bolivia (PROXY_URL del .env +
# sufijo __cr.bo — appweb2.asfi.gob.bo geo-bloquea IPs no bolivianas).
set -euo pipefail
cd /opt/binance_p2p
.venv/bin/python ingest_asfi.py
if ! git diff --quiet -- static/asfi_index.json 'static/asfi_2*.json' 2>/dev/null \
   || [ -n "$(git ls-files --others --exclude-standard -- 'static/asfi_2*.json')" ]; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add static/asfi_index.json
  git add static/asfi_2*.json
  git -c user.name="VPS ASFI Scraper" \
      -c user.email="asfi-scraper@finanzasbo.com" \
      commit -m "chore(asfi): reporte $(date -u +%Y-%m-%dT%H:%MZ)"
  git push origin "$CURRENT_BRANCH"
fi
# Health check opcional (mismo patrón HC_* de los wrappers BCB)
if [ -n "${HC_ASFI:-}" ]; then
  curl -fsS -m 10 --retry 3 "$HC_ASFI" > /dev/null || true
fi
