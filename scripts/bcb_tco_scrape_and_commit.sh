#!/usr/bin/env bash
# Wrapper para ingest_bcb_tco.py — pensado para correr CADA 5 MIN desde las 20:00 BO
# y reintentar hasta capturar el TCO del día.
#
# Cron del VPS (user binance):
#   */5 0-3 * * 2-6   cd /opt/binance_p2p && bash scripts/bcb_tco_scrape_and_commit.sh
#   (UTC 00:00–03:55 mar–sáb = 20:00–23:55 BO lun–vie. El TCO se publica a las 20:00
#    BO pero a veces con minutos de atraso, por eso reintentamos cada 5 min.)
#
# Idempotente. Commitea por CAMBIO DE VALOR (snapshot {fecha:tco}), no solo por
# fecha nueva — así una REVISIÓN del BCB sobre una fecha ya capturada se guarda en
# vez de descartarse (el BCB publica un TCO preliminar a las 20:00 y a veces lo
# corrige más tarde; con el commit-por-fecha viejo esa revisión se perdía). Dos
# fuentes por corrida:
#   (A) PORTADA (cada tick): HOY/MAÑANA fresco. SIN auto-freno — sigue mirando toda
#       la ventana; el snapshot por valor evita commits basura (solo bump de
#       fetched_at → descarte). Captura revisiones que caen dentro de la misma noche.
#   (B) HISTÓRICO (1×/noche, gate por stamp): el detalle CSV autoritativo del BCB.
#       Lagea ~2 días pero corrige revisiones TARDÍAS que la portada ya no muestra.
#       save_entries reconcilia por vigencia; el snapshot detecta el cambio y commitea.
#   - Autorreparable: si una noche falla, la corrida siguiente recupera (ventana 14d).
#
# Primera corrida / backfill del histórico:
#   .venv/bin/python ingest_bcb_tco.py --backfill
#
# Healthcheck (healthchecks.io): pingea $HC_BCB_TCO en el ÉXITO (commit) y /fail si
# la portada rompe sin que nada se capture. Sin /start por tick (evita falsos "started").
set -uo pipefail
cd /opt/binance_p2p

# HC_BCB_TCO = UUID del check; el wrapper arma https://hc-ping.com/<uuid>[/fail].
HC="${HC_BCB_TCO:-}"
hc(){ [ -n "$HC" ] && curl -fsS -m 10 "https://hc-ping.com/${HC}$1" -o /dev/null 2>/dev/null || true; }

# Fecha de hoy en Bolivia (UTC-4, sin DST) — usada para el stamp diario de (B).
hoy_bo=$(date -u -d '-4 hours' +%F)

# Snapshot canónico {fecha:tco} (IGNORA fetched_at) para detectar cambios de VALOR,
# no solo de fecha. Un cambio aquí = fecha nueva O revisión de una fecha existente.
snapshot(){
  [ -f bcb_tco.json ] || { echo ""; return 0; }
  .venv/bin/python -c "import json;d=json.load(open('bcb_tco.json'));print(';'.join(f\"{e.get('fecha')}={e.get('tco')}\" for e in sorted(d,key=lambda x:x.get('fecha',''))))" 2>/dev/null || echo ""
}

antes=$(snapshot)

# (A) Portada — fuente primaria, cada tick.
portada_ok=1
.venv/bin/python ingest_bcb_tco.py || portada_ok=0

# (B) Histórico autoritativo — 1×/noche (gate por stamp diario, fuera del índice de
# git vía .gitignore). Reconcilia días recientes; captura revisiones tardías. Si el
# fetch falla no crea el stamp → reintenta en el próximo tick.
STAMP=".tco_histsync_${hoy_bo}"
if [ ! -f "$STAMP" ]; then
  rm -f .tco_histsync_*                                   # limpiar stamps de días previos
  .venv/bin/python ingest_bcb_tco.py --via historico && : > "$STAMP" || true
fi

despues=$(snapshot)

if [ "$antes" != "$despues" ]; then
  # Cambió una fecha o un VALOR → commit + push (con reintentos por red).
  CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
  git add bcb_tco.json
  git -c user.name="VPS BCB Scraper" \
      -c user.email="bcb-scraper@finanzasbo.com" \
      commit -m "chore(bcb): scrape TCO $(date -u +%Y-%m-%dT%H:%MZ)"
  for i in 1 2 3 4; do
    git push origin "$CURRENT_BRANCH" && break || sleep $((2**i))
  done
  hc  # éxito (el dashboard lo recoge el cron de publish */12)
elif [ "$portada_ok" -eq 0 ]; then
  # Nada cambió y la portada rompió (red/parse) → señal de falla; próximo tick reintenta.
  git checkout -- bcb_tco.json 2>/dev/null || true
  hc /fail
else
  # Solo se bumpeó `fetched_at` (mismo valor) → descartar para no commitear cada 5 min.
  git checkout -- bcb_tco.json 2>/dev/null || true
fi
