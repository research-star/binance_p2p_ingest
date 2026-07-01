#!/usr/bin/env bash
# Wrapper para ingest_bcb_tco.py — pensado para correr CADA 5 MIN desde las 20:00 BO
# y reintentar hasta capturar el TCO del día.
#
# Cron del VPS (user binance):
#   */5 0-3 * * 2-6   cd /opt/binance_p2p && bash scripts/bcb_tco_scrape_and_commit.sh
#   (UTC 00:00–03:55 mar–sáb = 20:00–23:55 BO lun–vie. El TCO se publica a las 20:00
#    BO pero a veces con minutos de atraso, por eso reintentamos cada 5 min.)
#
# Idempotente y AUTO-FRENANTE (clave para correr cada 5 min sin ensuciar el repo):
#   - Si bcb_tco.json YA tiene una fecha de VIGENCIA futura (> hoy BO), ya capturamos
#     el valor de esta noche → no hace nada (los ticks restantes son no-op).
#   - Si no, corre el scraper. Solo commitea/pushea cuando aparece una FECHA NUEVA
#     (no por el simple bump de `fetched_at`), evitando ~48 commits basura por noche.
#   - Si el scraper solo re-trae el valor viejo (BCB aún no publicó), descarta el
#     cambio y reintenta en el próximo tick.
#   - Autorreparable igual que antes: si una noche nunca se logra, la corrida del
#     día hábil siguiente lo recupera (el scraper baja una ventana de 14 días atrás).
#
# Primera corrida / backfill del histórico:
#   .venv/bin/python ingest_bcb_tco.py --backfill
#
# Healthcheck (healthchecks.io): pingea $HC_BCB_TCO en el ÉXITO (captura del valor
# nuevo) y /fail si el scraper rompe. Sin /start por tick (evita falsos "started").
set -uo pipefail
cd /opt/binance_p2p

# HC_BCB_TCO = UUID del check; el wrapper arma https://hc-ping.com/<uuid>[/fail].
HC="${HC_BCB_TCO:-}"
hc(){ [ -n "$HC" ] && curl -fsS -m 10 "https://hc-ping.com/${HC}$1" -o /dev/null 2>/dev/null || true; }

# Fecha de hoy en Bolivia (UTC-4, sin DST). El TCO se fecha por su VIGENCIA (el
# próximo día hábil), así que al capturarlo max(fecha) queda > hoy_bo.
hoy_bo=$(date -u -d '-4 hours' +%F)

max_fecha(){
  [ -f bcb_tco.json ] || { echo ""; return 0; }
  .venv/bin/python -c "import json;d=json.load(open('bcb_tco.json'));print(max((e.get('fecha','') for e in d),default=''))" 2>/dev/null || echo ""
}

# ¿Ya tenemos el valor de esta noche (vigencia futura)? → nada que hacer.
antes=$(max_fecha)
if [ -n "$antes" ] && [[ "$antes" > "$hoy_bo" ]]; then
  exit 0
fi

# Intento de captura. Si el scraper rompe (red/parse), pingea /fail y sale sin
# romper el cron; el próximo tick reintenta.
if ! .venv/bin/python ingest_bcb_tco.py; then
  hc /fail
  exit 0
fi

despues=$(max_fecha)
# Commitear cuando la fecha máxima AVANZA respecto a lo que ya teníamos (no solo
# cuando es > hoy): si una noche falla la captura, el valor reaparece al día
# siguiente como HOY en la portada (fecha == hoy_bo) y también debe guardarse —
# con la comparación vs hoy_bo esa recuperación diurna se descartaba.
if [ -n "$despues" ] && { [ -z "$antes" ] || [[ "$despues" > "$antes" ]]; }; then
  # Capturamos una fecha nueva → commit + push (con reintentos por red).
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_tco.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape TCO $(date -u +%Y-%m-%dT%H:%MZ)"
  for i in 1 2 3 4; do
    git push origin "$CURRENT_BRANCH" && break || sleep $((2**i))
  done
  hc  # éxito (el dashboard lo recoge el cron de publish */12)
else
  # Solo se bumpeó `fetched_at` (mismo valor viejo) → descartar para no commitear
  # cada 5 min. Reintentará en el próximo tick.
  git checkout -- bcb_tco.json 2>/dev/null || true
fi
