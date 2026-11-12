#!/usr/bin/env bash
# Quita el agente del host de MuxSpace: servicio, programa y token. Con sudo.
set -euo pipefail

NAME=muxspace-host-agent
[ "$(id -u)" -eq 0 ] || { echo "Ejecuta con sudo." >&2; exit 1; }

systemctl disable --now "$NAME" 2>/dev/null || true
rm -f "/etc/systemd/system/$NAME.service"
rm -rf "/usr/local/lib/$NAME" "/etc/$NAME"
systemctl daemon-reload
echo "Agente desinstalado. Quita también las líneas MUXSPACE_HOST_POWEROFF_* del backend/.env del panel."
