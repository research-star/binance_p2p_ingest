#!/usr/bin/env bash
# Wrapper para ingest_bcb_tre.py — la TRE es MENSUAL, pero el día exacto en que
# el BCB actualiza el xlsx varía, así que el cron corre UNA VEZ AL DÍA y este
# wrapper decide (idempotente, auto-frenante):
#
# Cron del VPS (user binance):
#   15 12 * * *   cd /opt/binance_p2p && bash scripts/bcb_tre_scrape_and_commit.sh
#   (12:15 UTC = 08:15 BO diario.)
#
#   - Si bcb_tre.json YA tiene la vigencia del mes en curso → no hace nada (el
#     resto del mes los ticks son no-op, sin tocar la red del BCB).
#   - Si no, corre el scraper (descubre el xlsx de la gestión más alta en el
#     listado — el nombre cambia por año, no se hardcodea) y commitea SOLO si
#     la vigencia máxima avanzó. Si el BCB aún no publicó el mes, descarta y
#     reintenta mañana.
#
# Primera corrida / histórico completo (gestiones 2018+):
#   .venv/bin/python ingest_bcb_tre.py --backfill
#
# Healthcheck (healthchecks.io): pingea $HC_BCB_TRE en el éxito y /fail si el
# scraper rompe. Vacío → se omite (graceful, convención del repo).
set -uo pipefail
cd /opt/binance_p2p

HC="${HC_BCB_TRE:-}"
hc(){ [ -n "$HC" ] && curl -fsS -m 10 "https://hc-ping.com/${HC}$1" -o /dev/null 2>/dev/null || true; }

# Primer día del mes en curso (Bolivia, UTC-4): la vigencia que esperamos tener.
mes_bo=$(date -u -d '-4 hours' +%Y-%m-01)

max_vig(){
  [ -f bcb_tre.json ] || { echo ""; return 0; }
  .venv/bin/python -c "import json;d=json.load(open('bcb_tre.json'));print(max((e.get('vigencia','') for e in d),default=''))" 2>/dev/null || echo ""
}

antes=$(max_vig)
# ¿Ya tenemos la vigencia de este mes (o posterior)? → nada que hacer.
if [ -n "$antes" ] && [[ ! "$antes" < "$mes_bo" ]]; then
  exit 0
fi

if ! .venv/bin/python ingest_bcb_tre.py; then
  hc /fail
  exit 0
fi

despues=$(max_vig)
# Commitear solo si la vigencia máxima AVANZÓ (no por refinamientos de decimales
# sueltos — esos entran igual la próxima vez que avance el mes).
if [ -n "$despues" ] && { [ -z "$antes" ] || [[ "$despues" > "$antes" ]]; }; then
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_tre.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape TRE $(date -u +%Y-%m-%dT%H:%MZ)"
  for i in 1 2 3 4; do
    git push origin "$CURRENT_BRANCH" && break || sleep $((2**i))
  done
  hc
else
  git checkout -- bcb_tre.json 2>/dev/null || true
fi
