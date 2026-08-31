#!/usr/bin/env bash
# Marca la sesión de tmux actual como "reclama atención" en el panel.
#
# Pensado para engancharlo a un hook de Claude Code (Notification o Stop),
# pero vale para cualquier cosa que corra dentro de una sesión: un build
# largo, un despliegue, un script que termina.
#
#   scripts/muxspace-attention.sh "espera tu respuesta"
#
# La sesión NO se pasa como argumento: se pregunta a tmux. Quien ejecuta esto
# corre dentro del pane, así que la sesión correcta es siempre la suya, y
# escribirla a mano en la configuración de un hook sería una copia que se
# queda vieja en cuanto se renombra la terminal.
#
# Habla con el backend por su puerto local, no por el dominio del panel: el
# panel está detrás de mTLS y este script no tiene (ni debe tener) un
# certificado de dispositivo.
set -euo pipefail

URL="${MUXSPACE_URL:-http://127.0.0.1:8000}"
TOKEN_FILE="${MUXSPACE_TOKEN_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend/data/attention_token}"
LABEL="${1:-}"

if [ -z "${TMUX:-}" ]; then
  echo "muxspace-attention: no se está ejecutando dentro de tmux" >&2
  exit 1
fi

SESSION="$(tmux display-message -p '#S')"

if [ ! -r "$TOKEN_FILE" ]; then
  # El secreto lo genera el backend la primera vez que alguien marca o
  # arranca el panel; si no está, lo que falta es el backend.
  echo "muxspace-attention: no se puede leer $TOKEN_FILE" >&2
  exit 1
fi
TOKEN="$(cat "$TOKEN_FILE")"

# `--fail` para que un 401 o un 404 salgan como error del script en vez de
# imprimir el cuerpo y devolver 0. Un hook que falla en silencio es peor que
# uno que no existe: se descubre el día que se esperaba el aviso.
curl --fail --silent --show-error \
  -X POST "$URL/api/attention/$SESSION" \
  -H "X-Muxspace-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"label": "%s"}' "${LABEL//\"/\\\"}")" \
  -o /dev/null
