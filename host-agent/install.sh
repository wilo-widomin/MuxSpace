#!/usr/bin/env bash
# Instala el agente del host de MuxSpace. Se ejecuta en el ordenador host, con sudo.
#
#   sudo bash install.sh --allow-from <ip-de-la-vm>[,<otra>]  [--bind <ip>] [--port <n>]
#
# --allow-from  obligatorio: solo esa(s) dirección(es) pueden pedir el apagado.
# --bind        dirección donde escuchar. Por defecto, la del host que ve a la VM.
# --port        puerto. Por defecto, uno al azar que se conserva al reinstalar.
#
# Es repetible: no cambia el token si ya existe (para rotarlo, bórralo y repite).
set -euo pipefail

NAME=muxspace-host-agent
LIB=/usr/local/lib/$NAME
CONF=/etc/$NAME
UNIT=/etc/systemd/system/$NAME.service
HERE=$(cd "$(dirname "$0")" && pwd)

allow="" bind="" port=""
while [ $# -gt 0 ]; do
  case "$1" in
    --allow-from) allow="${2:-}"; shift 2 ;;
    --bind) bind="${2:-}"; shift 2 ;;
    --port) port="${2:-}"; shift 2 ;;
    *) echo "Argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo." >&2; exit 1; }
[ -n "$allow" ] || { echo "Falta --allow-from <ip-de-la-vm>." >&2; exit 2; }
command -v python3 >/dev/null || { echo "Hace falta python3." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "Hace falta systemd." >&2; exit 1; }

first_allowed=${allow%%,*}
if [ -z "$bind" ]; then
  bind=$(ip -4 route get "$first_allowed" 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -n1)
  [ -n "$bind" ] || { echo "No sé qué dirección usar: pásala con --bind." >&2; exit 1; }
fi
if [ -z "$port" ] && [ -f "$CONF/agent.env" ]; then
  port=$(sed -n 's/^MUXSPACE_AGENT_PORT=//p' "$CONF/agent.env")
fi
[ -n "$port" ] || port=$(python3 -c 'import random; print(random.randint(20000, 60000))')

install -d -m 755 "$LIB"
install -m 755 "$HERE/host_agent.py" "$LIB/host_agent.py"
install -d -m 700 "$CONF"

new_token=""
if [ ! -s "$CONF/token" ]; then
  new_token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  (umask 077 && printf '%s\n' "$new_token" > "$CONF/token")
fi
chmod 600 "$CONF/token"

(umask 077 && cat > "$CONF/agent.env" <<ENV
MUXSPACE_AGENT_BIND=$bind
MUXSPACE_AGENT_PORT=$port
MUXSPACE_AGENT_TOKEN_FILE=$CONF/token
MUXSPACE_AGENT_ALLOWED_IPS=$allow
ENV
)

install -m 644 "$HERE/$NAME.service" "$UNIT"
systemctl daemon-reload
systemctl enable "$NAME" >/dev/null
systemctl restart "$NAME"
sleep 1
systemctl is-active --quiet "$NAME" || { journalctl -u "$NAME" -n 20 --no-pager; echo "No ha arrancado." >&2; exit 1; }

echo
echo "Agente instalado y en marcha. Para ver quién lo usa:  journalctl -u $NAME -f"
echo
echo "Añade estas dos líneas a backend/.env del panel (en la VM):"
echo
echo "MUXSPACE_HOST_POWEROFF_URL=http://$bind:$port/poweroff"
if [ -n "$new_token" ]; then
  echo "MUXSPACE_HOST_POWEROFF_TOKEN=$new_token"
  echo
  echo "El token solo se muestra ahora. Guárdalo; si lo pierdes, bórralo y repite la instalación."
else
  echo "MUXSPACE_HOST_POWEROFF_TOKEN=<el que ya tenías; no se vuelve a mostrar>"
fi
