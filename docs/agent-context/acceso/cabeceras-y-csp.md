---
dominio: acceso
accion: cabeceras-y-csp
actualizado: 2026-08-28
archivos:
  - backend/main.py
  - docs/mtls.md
  - scripts/mtls-client-cert.sh
  - scripts/mtls-devices.sh
---

# Cabeceras, CSP y mTLS

## Los cuatro middlewares

En orden de declaración (el último declarado envuelve por fuera):

1. `_no_cache_api` — `Cache-Control: no-store` en todo `/api/`. Sin esto, la
   caché heurística del navegador congela los listados.
2. `_csrf_origin_guard` — 403 a los métodos que no son GET/HEAD/OPTIONS con un
   `Origin` fuera de `CORS_ORIGINS`. Sin `Origin` (curl) pasa.
3. `_reject_banned_ips` — 403.
4. `_security_headers` — **declarado el último a propósito**, para que sus
   cabeceras salgan también en los 403 de los dos anteriores.

## Qué se rompe al tocar la CSP

`default-src 'self'; frame-ancestors 'none'; img-src 'self' data:; style-src
'self' 'unsafe-inline'; base-uri 'none'; form-action 'none'`, más
`X-Frame-Options: DENY`, `nosniff` y `Referrer-Policy: no-referrer`.

- Quitar `style-src 'unsafe-inline'` **rompe xterm.js**, que inyecta estilos.
- `default-src 'self'` es lo que autoriza el `ws://` del mismo origen:
  restringirlo sin un `connect-src` explícito mata el terminal.
- `img-src data:` sostiene las miniaturas de las capturas pegadas.
- Quitar `frame-ancestors 'none'` reabre el clickjacking, que en este panel
  equivale a ejecución remota: dentro de un iframe todo es same-origin y el
  guard de Origin no lo ve.

## mTLS

- Se verifica **donde termina TLS**: el proxy. El backend no ve certificados y
  no mapea certificado a usuario; para él todo es HTTP tras el proxy.
- Responsabilidad del proxy: exigir certificado de cliente de la CA propia y
  pasar la IP real (que uvicorn solo honra si el proxy está en
  `--forwarded-allow-ips`).
- Cada dispositivo necesita **dos** certificados: el de la CA que firma el del
  dominio (para que el navegador confíe) y el `.p12` de cliente (para que el
  proxy deje pasar). Se emiten con `scripts/mtls-client-cert.sh` y se
  inventarían con `scripts/mtls-devices.sh`.
- Los certificados de cliente tienen que ser X.509 v3 con `clientAuth`: Android
  ignora los v1. No hay CRL: revocar es regenerar la CA y reemitir.
- Apagar el login apoyándose en mTLS exige antes cerrar los caminos que saltan
  el proxy (escuchar solo en local y restringir por IP en el proxy).
