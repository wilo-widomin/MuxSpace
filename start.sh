#!/usr/bin/env bash
# Arranque en producción del MuxSpace.
#
# Levanta el backend FastAPI (que además sirve el frontend ya compilado
# en frontend/dist) en el host/puerto configurados en backend/.env.
#
# Acceso: por defecto en 127.0.0.1:8000 (solo local). Si quieres exponerlo
# al exterior o servirlo por HTTPS, pon un reverse proxy (Caddy/Nginx)
# delante; eso es opcional y ajeno a este script.
#
# Requisitos que verifica/prepara:
#   - tmux, python3 (y venv) en el PATH.
#   - node/npm, solo si hace falta compilar el frontend.
#   - venv del backend con las dependencias instaladas.
#   - build del frontend (frontend/dist); si falta, lo compila con npm.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Lee HOST y PORT de backend/.env (lectura dirigida: no se "sourcea" el
# archivo entero para no corromper valores JSON como DIR_SUGGESTION_ROOTS).
# Defaults aptos para acceso estrictamente local.
_env_val() {  # $1 = clave ; devuelve el valor tal cual en .env
  [ -f backend/.env ] || return 0
  grep -E "^[[:space:]]*$1=" backend/.env 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' || true
}
HOST="$(_env_val MUXSPACE_HOST)"; HOST="${HOST:-127.0.0.1}"
PORT="$(_env_val MUXSPACE_PORT)"; PORT="${PORT:-8000}"
# Proxies de confianza para X-Forwarded-For: de ahí sale la IP real del
# cliente con la que trabajan el rate limit del login y los baneos de IP.
# Ver MUXSPACE_TRUSTED_PROXIES en backend/.env.example.
PROXIES="$(_env_val MUXSPACE_TRUSTED_PROXIES)"; PROXIES="${PROXIES:-127.0.0.1}"

# --- Requisitos del sistema ---
need() {
  command -v "$1" >/dev/null 2>&1 || { echo "❌ Falta dependencia: $1 (instálala con tu gestor de paquetes)" >&2; exit 1; }
}
need tmux
need python3
[ -f frontend/dist/index.html ] || need npm   # npm solo hace falta si hay que compilar

# --- Backend: entorno virtual ---
if [ ! -d backend/venv ]; then
  echo "Creando entorno virtual del backend…"
  python3 -m venv backend/venv
  backend/venv/bin/pip install --upgrade pip >/dev/null
  backend/venv/bin/pip install -r backend/requirements.txt
fi

# --- Frontend: build de producción ---
if [ ! -f frontend/dist/index.html ]; then
  echo "No existe el build del frontend; compilando…"
  if [ ! -d frontend/node_modules ]; then
    (cd frontend && npm install)
  fi
  (cd frontend && npm run build)
fi

echo "Arrancando MuxSpace en http://${HOST}:${PORT} …"
exec backend/venv/bin/python -m uvicorn main:app \
  --app-dir backend \
  --host "$HOST" \
  --port "$PORT" \
  --proxy-headers \
  --forwarded-allow-ips "$PROXIES"