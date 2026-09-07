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
`X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`,
`Permissions-Policy: camera=(), microphone=(), geolocation=()` y
`Strict-Transport-Security: max-age=31536000`.

**HSTS solo sale por https**, y la condición no es cosmética: emitida en
`http://localhost:8000` dejaría el localhost del usuario exigiendo TLS durante
un año a todos sus proyectos, y eso no se arregla borrando la línea que la
puso. El esquema sale de `X-Forwarded-Proto`, que uvicorn honra porque
`start.sh` arranca con `--proxy-headers`: si el proxy dejara de enviarlo, la
cabecera no saldría nunca. Va sin `includeSubDomains` ni `preload` a
propósito — el panel vive en un dominio y ninguna de las dos se deshace rápido.
Lo cubre `backend/tests/test_cabeceras.py`, con el caso negativo incluido.

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
