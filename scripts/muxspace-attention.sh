#!/usr/bin/env bash
# Marca la sesión de tmux actual como "reclama atención" en el panel.
#
# Pensado para engancharlo a un hook de Claude Code (Notification o Stop),
# pero vale para cualquier cosa que corra dentro de una sesión: un build
# largo, un despliegue, un script que termina.
#
#   scripts/muxspace-attention.sh "espera tu respuesta"
#   scripts/muxspace-attention.sh --quiet "espera tu respuesta"
#
# Con `--quiet` el script se calla y devuelve 0 cuando el aviso simplemente
# NO APLICA: no hay tmux alrededor, o el panel no está levantado. Es el modo
# para un hook instalado globalmente, que se ejecuta en cada proyecto y en
# cada terminal, también donde MuxSpace no pinta nada; sin él, el usuario
# vería un error rojo por cada sesión abierta fuera del panel.
#
# Lo que `--quiet` NO se traga es un fallo de verdad —un 401, un 500—: eso
# significa que el aviso se ha configurado mal y hay que enterarse.
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

QUIET=0
if [ "${1:-}" = "--quiet" ]; then
  QUIET=1
  shift
fi
LABEL="${1:-}"

# "No aplica": el sitio donde corre esto no tiene panel al que avisar. En modo
# hook se sale en silencio; a mano se dice por qué, que es lo que uno quiere
# saber cuando lo ejecuta y no pasa nada.
no_aplica() {
  [ "$QUIET" -eq 1 ] || echo "muxspace-attention: $1" >&2
  exit 0
}

if [ -z "${TMUX:-}" ]; then
  no_aplica "no se está ejecutando dentro de tmux"
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
  # El secreto lo crea el backend al arrancar; que no esté significa que el
  # panel no ha arrancado nunca, no que falte un paso de instalación.
  no_aplica "no se puede leer $TOKEN_FILE"
fi
TOKEN="$(cat "$TOKEN_FILE")"

# `--fail` para que un 401 o un 404 salgan como error del script en vez de
# imprimir el cuerpo y devolver 0. Un hook que falla en silencio es peor que
# uno que no existe: se descubre el día que se esperaba el aviso.
#
# `--max-time` porque esto corre DENTRO del hook, o sea delante del usuario:
# un backend que acepta la conexión y no contesta dejaría a Claude Code
# esperando. Dos segundos es de sobra contra un servidor de la propia
# máquina.
set +e
SALIDA="$(
  curl --fail --silent --show-error --max-time 2 \
    -X POST "$URL/api/attention/$(urlencode "$SESSION")" \
    -H "X-Muxspace-Token: $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$(printf '{"label": "%s"}' "$(json_escape "$LABEL")")" \
    -o /dev/null 2>&1
)"
CODIGO=$?
set -e

if [ "$CODIGO" -ne 0 ]; then
  # 7 (no se pudo conectar) y 28 (se agotó el tiempo) son "el panel no está
  # levantado", no un error de configuración: los demás sí.
  case "$CODIGO" in
    7 | 28) no_aplica "el panel no responde en $URL" ;;
    *)
      echo "muxspace-attention: ${SALIDA:-curl salió con $CODIGO}" >&2
      exit "$CODIGO"
      ;;
  esac
fi
