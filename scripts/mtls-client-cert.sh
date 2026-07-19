#!/usr/bin/env bash
# Genera la CA de mTLS del panel (solo la primera vez) y un certificado de
# cliente por dispositivo, empaquetado como .p12 para instalarlo en el
# navegador o el móvil. Ver docs/mtls.md para el cuadro completo.
#
# Uso:
#   ./scripts/mtls-client-cert.sh <nombre-dispositivo> [dias-validez]
#
#   MTLS_DIR   directorio donde viven la CA y los certificados
#              (default: ~/certs/tmux-panel-mtls — FUERA del repo: contiene
#              claves privadas y no debe versionarse jamás).
#   P12_PASS   contraseña de exportación del .p12; si no se define, se
#              pide por teclado (los importadores de iOS/Android exigen una).
set -euo pipefail

NAME="${1:?Uso: $0 <nombre-dispositivo> [dias-validez]}"
DAYS="${2:-825}"
DIR="${MTLS_DIR:-$HOME/certs/tmux-panel-mtls}"

mkdir -p "$DIR"
chmod 700 "$DIR"
cd "$DIR"

# --- CA propia (una sola vez) ------------------------------------------
if [[ ! -f ca.key ]]; then
    echo ">> Creando la CA en $DIR (10 años)"
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
        -keyout ca.key -out ca.crt -days 3650 -nodes \
        -subj "/CN=tmux-panel mTLS CA" 2>/dev/null
    chmod 600 ca.key
fi

# --- Certificado del dispositivo ----------------------------------------
if [[ -f "$NAME.crt" ]]; then
    echo "ERROR: ya existe $DIR/$NAME.crt (borra o usa otro nombre)" >&2
    exit 1
fi

echo ">> Emitiendo certificado de cliente '$NAME' ($DAYS días)"
openssl req -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
    -keyout "$NAME.key" -out "$NAME.csr" -nodes \
    -subj "/CN=$NAME" 2>/dev/null
chmod 600 "$NAME.key"
openssl x509 -req -in "$NAME.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days "$DAYS" -out "$NAME.crt" 2>/dev/null
rm -f "$NAME.csr"

# --- Paquete .p12 para el dispositivo ------------------------------------
# -legacy: OpenSSL 3 cifra los .p12 con AES/SHA-256 por defecto y los
# importadores de macOS/iOS los rechazan con "MAC verification failed
# (wrong password?)"; el formato legacy (RC2/3DES) lo aceptan todos.
LEGACY_FLAG=""
openssl pkcs12 -export -help 2>&1 | grep -q -- '-legacy' && LEGACY_FLAG="-legacy"
if [[ -n "${P12_PASS:-}" ]]; then
    openssl pkcs12 -export $LEGACY_FLAG -inkey "$NAME.key" -in "$NAME.crt" \
        -certfile ca.crt -name "tmux-panel $NAME" \
        -out "$NAME.p12" -passout "pass:$P12_PASS"
else
    echo ">> Contraseña de exportación del .p12 (se pedirá dos veces):"
    openssl pkcs12 -export $LEGACY_FLAG -inkey "$NAME.key" -in "$NAME.crt" \
        -certfile ca.crt -name "tmux-panel $NAME" \
        -out "$NAME.p12"
fi
chmod 600 "$NAME.p12"

echo
echo "Listo:"
echo "  CA (pública, para el proxy):  $DIR/ca.crt"
echo "  Certificado del dispositivo:  $DIR/$NAME.p12  (instalar en navegador/móvil)"
echo
echo "La clave de la CA ($DIR/ca.key) no sale de esta máquina."
