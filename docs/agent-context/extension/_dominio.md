---
dominio: extension
actualizado: 2026-10-13
archivos:
  - extension/manifest.json
  - extension/src/background.js
  - extension/src/popup.js
  - extension/src/options.js
  - extension/src/lib/group.js
  - extension/src/lib/login.js
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
nada pregunta por `GET /api/me` (`probeSession`, clasificado por
`sessionState`: `ok`, `login` si da 401, `unreachable` si no se puede ni
inyectar —falta el certificado de cliente y la pestaña enseña la página de
error de Chrome— o el panel falla).

**La pestaña puente nunca se abre en la ventana del usuario.** Si no hay
ninguna pestaña del panel, `panelBridge` abre el panel en una ventana
emergente **minimizada** (`type: 'popup'`). Si la puente fuera una pestaña de
la ventana del usuario, Chrome la traería al frente al pedir el certificado y
taparía la ventana de login.

Si no es `ok`, `loginInWindow` pone delante una ventana emergente (480×720,
centrada sobre la ventana normal con foco). Si la puente es la de la
extensión, es esa misma ventana, que sale de minimizada. Si la puente es una
pestaña del usuario, se abre una nueva. Ahí sale el selector de certificado
de Chrome si hace falta, y después el login del panel. Se sondea `/api/me`
cada 1,5 s hasta 5 minutos. En cuanto hay sesión se sigue por donde se iba:
- **Si la ventana era la puente:** se queda hasta que quien llama termina de
  preguntar y la cierra (`closeBridge`).
- **Si no:** se cierra, y la pestaña del usuario se recarga (`renewBridge`). Pasa igual al abrir un proyecto y al
refrescar la lista (que ocurre al abrir el popup); en el segundo caso, al
volver, se reabre el popup con `chrome.action.openPopup()` para que la lista
aparezca sin otro clic.

Cerrar la ventana o agotar la espera da `AuthError` (`needsLogin: true`) y el
popup enseña «Iniciar sesión en el panel», que reintenta el refresco.

La contraseña se teclea **siempre en el panel**, nunca en el popup. Tampoco va
en un iframe dentro del popup: el popup se cierra al perder el foco, y el
selector de certificado se lo lleva; además el panel prohíbe que lo enmarquen
(`frame-ancestors 'none'`).

La dirección del panel se escribe en las opciones, se normaliza y se guarda en
`chrome.storage.local` (`panelOrigin`); **no hay ninguna por defecto en el
repo**. Ahí viven también la caché `projects` y el mapa `projectGroups`
(`projectId -> groupId`).

## Piezas

- `lib/panel.js` — normalizar el origen, construir la URL con `?space=`.
- `lib/projects.js` — ordenar y filtrar (sin acentos, sin mayúsculas).
- `lib/sessions.js` — qué sesiones adoptar y si hace falta lanzar el proyecto.
- `lib/login.js` — clasificar la respuesta de `/api/me` y centrar la ventana
  de login.
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
- Mientras falta el certificado, `/api/me` ni falla ni contesta. La única
  señal es el silencio, así que `waitForSession` pregunta a la puente
  minimizada cada 200 ms y, si en 1,5 s no hay respuesta, la da por
  `unreachable` y saca la ventana. Con sesión contesta en unos cientos de ms.
  Un 401 saca la ventana enseguida y sin recargar.
- `probeSession` inyecta con `injectImmediately` y un tope de 3 s. Mientras
  se espera el certificado la página nunca llega a `document_idle`, y una
  inyección normal se quedaba colgada: la ventana nunca salía de minimizada.
- En macOS, el selector de certificado que nace con la ventana minimizada no
  se pinta al restaurarla (solo al cambiar de escritorio o algo parecido).
  Por eso `showBridgeWindow` **recarga la pestaña** (solo si fue
  `unreachable`) después de sacarla: la petición vuelve a empezar con la
  ventana visible. La ventana de login que se abre aparte
  (`openLoginWindow`) nace ya visible. Chrome recuerda el certificado elegido
  hasta que se cierra.
- Con el panel caído también se abre la ventana de login (no se distingue de
  «falta el certificado»): enseña el error de Chrome, que al menos explica
  qué pasa.
- La ventana de login es una sola (`loginOnce`): abrir un proyecto mientras se
  refresca espera a la misma ventana. Las pestañas de ventanas emergentes no
  cuentan como puente del usuario (`windowType: 'normal'`).
- Una pestaña de una ventana emergente no se puede agrupar ni mover a una
  ventana normal. Por eso abrir un proyecto cierra la puente y abre todas las
  pestañas del grupo nuevas, con `windowId` explícito (la del grupo, o la
  ventana normal con foco). Sin él, la ventana «actual» del service worker
  podría ser la emergente.
- Sondear el login mantiene vivo el service worker mientras dura la espera.
  Si se agota, la ventana **no se cierra** (`keepWindow`): el usuario podría
  estar tecleando.
- `chrome.action.openPopup()` necesita Chrome 127+; si falla, se ignora y
  basta con volver a abrir el popup.
- Los tests (vitest, con `bun run test`) solo cubren `lib/`: todo lo que llama a
  Chrome se prueba a mano cargando la extensión descomprimida.
