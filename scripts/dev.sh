#!/usr/bin/env bash
# Arranca backend (FastAPI) y frontend (Vite) en modo desarrollo.
# Ctrl-C detiene ambos.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --- Backend ---
if [ ! -d backend/venv ]; then
  echo "Creando entorno virtual del backend…"
  python3 -m venv backend/venv
  backend/venv/bin/pip install --upgrade pip >/dev/null
  backend/venv/bin/pip install -r backend/requirements.txt
fi

# --- Frontend ---
if [ ! -d frontend/node_modules ]; then
  echo "Instalando dependencias del frontend…"
  (cd frontend && npm install)
fi

cleanup() {
  printf '\nDeteniendo procesos…\n'
  kill "${BACK_PID:-}" "${FRONT_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Arrancando backend en http://localhost:8000 …"
(cd backend && ./venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000) &
BACK_PID=$!

echo "Arrancando frontend en http://localhost:5173 …"
(cd frontend && npm run dev) &
FRONT_PID=$!

wait
