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

# Los nombres de sesión llevan espacios y paréntesis con toda normalidad
# («Terminal (2)», los que nacen de un proyecto), y meterlos crudos en la URL
# hace que curl la rechace antes de salir a la red. Se codifica BYTE A BYTE
# con LC_ALL=C: con acentos, recorrer la cadena por caracteres produciría
# secuencias UTF-8 a medias.
urlencode() {
  local LC_ALL=C cadena="$1" salida="" i caracter
  for ((i = 0; i < ${#cadena}; i++)); do
    caracter="${cadena:i:1}"
    case "$caracter" in
      [a-zA-Z0-9.~_-]) salida+="$caracter" ;;
      *)
        printf -v caracter '%%%02X' "'$caracter"
        salida+="$caracter"
        ;;
    esac
  done
  printf '%s' "$salida"
}

# Lo mismo por el otro lado: una etiqueta con comillas o barras invertidas
# rompería el JSON a mano de más abajo.
json_escape() {
  local cadena="$1"
  cadena="${cadena//\\/\\\\}"
  cadena="${cadena//\"/\\\"}"
  printf '%s' "$cadena"
}

if [ ! -r "$TOKEN_FILE" ]; then
  # El secreto lo crea el backend al arrancar; si no está, lo que falta es el
  # backend, no un paso de instalación.
  echo "muxspace-attention: no se puede leer $TOKEN_FILE" >&2
  exit 1
fi
TOKEN="$(cat "$TOKEN_FILE")"

# `--fail` para que un 401 o un 404 salgan como error del script en vez de
# imprimir el cuerpo y devolver 0. Un hook que falla en silencio es peor que
# uno que no existe: se descubre el día que se esperaba el aviso.
curl --fail --silent --show-error \
  -X POST "$URL/api/attention/$(urlencode "$SESSION")" \
  -H "X-Muxspace-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(printf '{"label": "%s"}' "$(json_escape "$LABEL")")" \
  -o /dev/null
