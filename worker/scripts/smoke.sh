#!/usr/bin/env bash
# Smoke del runtime real (workerd/Miniflare) vía `wrangler dev`. Valida que el
# Worker bootea, la ruta pública responde y las rutas auth rechazan sin token.
# El happy-path con JWT mockeado se cubre en la suite de vitest (test/).
set -u
cd "$(dirname "$0")/.." || exit 1
export WRANGLER_SEND_METRICS=false
export CI=1
PORT="${PORT:-8787}"
LOG="$(mktemp)"

./node_modules/.bin/wrangler dev --port "$PORT" >"$LOG" 2>&1 &
WPID=$!

cleanup() { kill "$WPID" 2>/dev/null; pkill -f "workerd" 2>/dev/null; }
trap cleanup EXIT

# Espera readiness sin sleep: curl reintenta hasta que el server acepta conexión.
if ! curl -s --retry 40 --retry-delay 1 --retry-connrefused -o /dev/null \
      "http://127.0.0.1:$PORT/v1/hidden"; then
  echo "WRANGLER DEV NO ARRANCÓ:"; cat "$LOG"; exit 1
fi

echo "=== GET /v1/hidden (público) ==="
curl -s -w "\nstatus=%{http_code} acao=%header{access-control-allow-origin}\n" "http://127.0.0.1:$PORT/v1/hidden"
echo "=== GET /v1/me (sin token) ==="
curl -s -w "\nstatus=%{http_code}\n" "http://127.0.0.1:$PORT/v1/me"
echo "=== POST /v1/hide (sin token, text/plain) ==="
curl -s -w "\nstatus=%{http_code}\n" -X POST -H "Content-Type: text/plain" --data "0123456789abcdef" "http://127.0.0.1:$PORT/v1/hide"
echo "=== GET /v1/nope (404) ==="
curl -s -w "\nstatus=%{http_code}\n" "http://127.0.0.1:$PORT/v1/nope"
echo "=== SMOKE OK ==="
