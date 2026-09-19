---
dominio: extension
actualizado: 2026-09-18
archivos:
  - extension/manifest.json
  - extension/src/background.js
  - extension/src/popup.js
  - extension/src/options.js
  - extension/src/lib/group.js
  - extension/src/lib/panel.js
  - extension/src/lib/projects.js
  - extension/src/lib/sessions.js
  - extension/src/lib/storage.js
depende_de: [biblioteca/_dominio, espacios/_dominio, sesiones/_dominio]
---

# Extensión de Chrome

Convierte cada proyecto del panel en un **grupo de pestañas de Chrome**: el
panel abierto en el espacio de ese proyecto y detrás sus enlaces guardados.
Además deja el espacio con sus terminales dentro (adopta las sesiones que
quedaron en otro espacio y lanza el proyecto si no tiene ninguna viva), sin
duplicar grupos ni sesiones al reabrir.

Paquete aparte: su propio `package.json`, su lockfile y su job de CI.

## Cómo habla con el backend

**Nunca hace `fetch` por su cuenta.** El panel está tras certificado de cliente
y cookie de sesión, que pertenecen a la pestaña; así que la extensión inyecta
código en una pestaña del panel (`chrome.scripting.executeScript` con
`world: 'MAIN'`) y es esa pestaña la que llama a la API con sus credenciales.
Endpoints que usa: `GET /api/me`, `GET /api/projects`, `GET /api/sessions`,
`PUT /api/sessions/{name}/space` y `POST /api/projects/{id}/run`.

**Sin sesión en el panel, la extensión no hace nada**, así que antes de pedir
nada pregunta por `GET /api/me`. Si contesta 401, hay dos comportamientos y
los separa `promptLogin`:

- **Abrir un proyecto** (el usuario ha pulsado): trae la pestaña del panel al
  frente —sin sesión pinta su pantalla de login—, sondea `/api/me` cada 1,5 s
  hasta 5 minutos y, en cuanto hay sesión, **continúa la apertura sola**.
- **Refrescar la lista** (pasa solo al abrir el popup): no roba el foco.
  Devuelve `needsLogin: true` y el popup enseña el botón «Iniciar sesión en el
  panel», que dispara lo mismo a petición del usuario.

La contraseña se teclea **siempre en la pestaña del panel**, nunca en el
popup: la cookie y el certificado de cliente son de esa pestaña.

La dirección del panel se escribe en las opciones, se normaliza y se guarda en
`chrome.storage.local` (`panelOrigin`); **no hay ninguna por defecto en el
repo**. Ahí viven también la caché `projects` y el mapa `projectGroups`
(`projectId -> groupId`).

## Piezas

- `lib/panel.js` — normalizar el origen, construir la URL con `?space=`.
- `lib/projects.js` — ordenar y filtrar (sin acentos, sin mayúsculas).
- `lib/sessions.js` — qué sesiones adoptar y si hace falta lanzar el proyecto.
- `lib/group.js` — color estable por id, URLs previstas y reconciliación con lo
  que ya hay abierto.
- `background.js` es el único que toca las APIs de Chrome; `popup.js` y
  `options.js` no tienen lógica propia.

## Acciones documentadas

- [Abrir un proyecto](abrir-proyecto.md)

## Trampas

- Los permisos de host son **opcionales** y se piden en runtime al guardar el
  origen: si se deniegan, nada funciona y el error dice «no se pudo hablar con
  el panel». Cambiar el origen no revoca el anterior ni invalida la caché.
- Se lee `sessionStorage['muxspace:active-space']` **dentro** de la pestaña del
  panel, porque el panel borra `?space=` de la URL en cuanto lo obedece; sin
  eso habría que recargar la pestaña del usuario en cada apertura.
- El service worker de MV3 se duerme: el anti-doble-clic solo protege dentro de
  una misma vida del worker, y una apertura a medias deja pestañas creadas sin
  agrupar.
- `waitForLoad` no tiene timeout: una pestaña que nunca termina de cargar deja
  la promesa colgada y el botón bloqueado.
- Sondear el login mantiene vivo el service worker mientras dura la espera,
  pero si la pestaña del panel se cierra en medio, la apertura muere con
  «no se pudo hablar con el panel».
- La pestaña que ya está enseñando el login no se cierra aunque la abriera la
  extensión (`keepTab`): cerrarla mientras se teclea la contraseña sería peor
  que dejar una de más.
- Los tests (vitest, con `bun run test`) solo cubren `lib/`: todo lo que llama a
  Chrome se prueba a mano cargando la extensión descomprimida.
