#!/usr/bin/env bash
# Wrapper para correr ingest_bcb_tco.py y commitear el JSON si cambió.
# Invocado desde el cron del VPS (lun-vie 20:05 BO = 00:05 UTC mar-sáb).
# El TCO se publica a las 20:00 BO; corremos 5 min después. El scraper baja una
# ventana móvil (14 días atrás + 5 adelante; el TCO se fecha por su vigencia, que
# va por delante de hoy) — autorreparable: si una corrida cae muy temprano y el
# BCB aún no subió el dato, la del día siguiente lo recupera.
# Primera corrida / backfill del histórico: ejecutar a mano una vez con
#   .venv/bin/python ingest_bcb_tco.py --backfill
#
# Healthcheck (healthchecks.io): pingea $HC_BCB_TCO (start/éxito/fail) si está
# definido en el entorno (env var arriba del crontab y en .env). Si está vacío,
# los pings se omiten sin error (graceful, igual que el resto de scrapers).
set -euo pipefail
cd /opt/binance_p2p

# HC_BCB_TCO = UUID del check (convención del repo, igual que HC_EMBI/HC_NOTICIAS);
# el wrapper arma la URL https://hc-ping.com/<uuid>[/start|/fail].
HC="${HC_BCB_TCO:-}"
hc(){ [ -n "$HC" ] && curl -fsS -m 10 "https://hc-ping.com/${HC}$1" -o /dev/null 2>/dev/null || true; }
trap 'hc /fail' ERR

hc /start
.venv/bin/python ingest_bcb_tco.py
if ! git diff --quiet bcb_tco.json; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_tco.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape TCO $(date -u +%Y-%m-%dT%H:%MZ)"
  git push origin "$CURRENT_BRANCH"
fi
hc   # éxito (URL base)
