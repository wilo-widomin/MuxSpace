---
dominio: i18n
accion: anadir-una-clave
actualizado: 2026-08-28
archivos:
  - frontend/src/i18n/locales/es.json
  - scripts/check-i18n.js
  - backend/errors.py
---

# Añadir una clave

1. Escríbela en `es.json`, en su zona (`tile.`, `form.`, `err.`…).
2. Tradúcela en los **otros cinco** catálogos, con los mismos placeholders.
3. Úsala con `t('clave')` — comillas simples.
4. `cd frontend && bun run check-i18n`.

Para un error nuevo del backend: `http_error(400, "err.lo_que_sea", param=x)`
y la clave en los seis catálogos. El verificador no revisa los códigos que
emite el backend, así que ese hueco no lo caza nadie: si falta, el usuario ve
el código crudo.

## Qué hace fallar la CI

- Una clave de `es.json` que falte en algún idioma.
- Una clave **huérfana** (que ya no está en `es.json`) en algún idioma.
- Placeholders `{x}` que no coincidan exactamente con los del español.
- Una entrada plural en un idioma y string en otro, o sin la forma `other`.
- Una llamada `t('clave')` en el código con una clave que no existe, incluida
  la comprobación del prefijo en las claves construidas.

## Qué solo avisa

- Formas plurales distintas de `other` que falten para ese idioma (caen a
  `other`).
- Claves del catálogo sin uso detectado en el código. Las `err.*` están
  excluidas de ese aviso porque las emite el backend.
