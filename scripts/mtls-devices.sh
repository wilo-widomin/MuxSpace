#!/usr/bin/env bash
# Lista los dispositivos que pueden entrar al panel: un certificado de cliente
# por aparato. Ver docs/mtls.md.
#
# El nombre del certificado ES el dispositivo (se elige al emitirlo). Para
# ponerle una descripción más humana, crea un archivo `notas.txt` en el mismo
# directorio con líneas `nombre: descripción`.
#
# Lo que este script NO puede decir: cuándo se usó cada certificado por última
# vez. El mTLS se verifica en el Caddy del host y al panel solo le llega HTTP
# plano, así que esa información está en el log del host, no aquí.
set -euo pipefail

DIR="${MTLS_DIR:-$HOME/certs/muxspace-mtls}"
NOTES="$DIR/notas.txt"

[[ -d $DIR ]] || { echo "No hay ningún certificado todavía ($DIR no existe)."; exit 0; }
cd "$DIR"

shopt -s nullglob
CERTS=(*.crt)
DEVICES=()
for c in "${CERTS[@]}"; do
    [[ $c == ca.crt ]] && continue
    DEVICES+=("${c%.crt}")
done

if [[ ${#DEVICES[@]} -eq 0 ]]; then
    echo "No hay ningún dispositivo dado de alta."
    exit 0
fi

# Fecha de caducidad de la CA: cuando expira, dejan de valer todos a la vez.
if [[ -f ca.crt ]]; then
    CA_END=$(openssl x509 -in ca.crt -noout -enddate | cut -d= -f2)
    printf 'CA del panel: caduca el %s\n\n' "$(date -d "$CA_END" +%d/%m/%Y)"
fi

printf '%-18s  %-10s  %-10s  %-8s  %s\n' DISPOSITIVO EMITIDO CADUCA ESTADO NOTA
printf '%-18s  %-10s  %-10s  %-8s  %s\n' ------------------ ---------- ---------- -------- ----
for name in "${DEVICES[@]}"; do
    start=$(openssl x509 -in "$name.crt" -noout -startdate | cut -d= -f2)
    end=$(openssl x509 -in "$name.crt" -noout -enddate | cut -d= -f2)
    left=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))

    if   (( left < 0 ));  then status="CADUCADO"
    elif (( left < 30 )); then status="${left}d"
    else                       status="ok"
    fi

    # Un certificado de versión 1 no lo ofrece nunca el almacén de Android:
    # merece aviso porque el síntoma en el móvil no apunta al certificado.
    version=$(openssl x509 -in "$name.crt" -noout -text | awk '/Version:/{print $2; exit}')
    [[ $version != 3 ]] && status="v1-viejo"

    note=""
    [[ -f $NOTES ]] && note=$(grep -m1 "^$name:" "$NOTES" 2>/dev/null | cut -d: -f2- | sed 's/^ *//' || true)
    [[ -f $name.p12 ]] || note="${note:+$note }(sin .p12: reemítelo para instalarlo en un aparato)"

    printf '%-18s  %-10s  %-10s  %-8s  %s\n' \
        "$name" "$(date -d "$start" +%d/%m/%Y)" "$(date -d "$end" +%d/%m/%Y)" "$status" "$note"
done
