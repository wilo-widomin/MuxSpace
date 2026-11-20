---
dominio: extension
actualizado: 2026-11-20
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

**El service worker nunca hace `fetch` por su cuenta** (la página del popup solo
en el atajo de abajo). El panel está tras certificado de cliente
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

**Atajo previo desde el popup** (`projectsByShortcut` en `popup.js`): antes de
pedir nada al service worker, la página del popup hace `fetch` a `/api/me` y
`/api/projects` con `credentials: 'include'`, si el permiso de host ya está
concedido y con tope de 3 s. Solo con 200 y datos válidos pinta la
lista y no se abre ninguna ventana. Con 401, red, TLS, tiempo agotado o
cualquier otra cosa se sigue por el flujo de siempre. **No está comprobado**
que ese `fetch` lleve cookie (`SameSite=Lax`) ni certificado de cliente: por
eso es un atajo que no puede empeorar nada.

**La pestaña puente nunca se abre en la ventana del usuario.** Si no hay
ninguna pestaña del panel, `panelBridge` abre el panel en una ventana
emergente **minimizada** (`type: 'popup'`), solo para el sondeo (con sesión no
parpadea nada). Si la puente fuera una pestaña de la ventana del usuario,
Chrome la traería al frente al pedir el certificado y taparía la ventana de
login.

**Una puente minimizada nunca se restaura.** Si no es `ok`, `loginInWindow`
decide con `loginWindowPlan` (`lib/login.js`): puente de la extensión →
`replace` (se cierra y se abre otra ventana ya visible, 480×720, centrada
sobre la ventana normal y con foco, que pasa a ser la puente); pestaña del
usuario → `open` (ventana nueva aparte, y al entrar se cierra y se recarga la
pestaña, `renewBridge`). Ahí sale el selector de certificado
de Chrome si hace falta, y después el login del panel. Se sondea `/api/me`
cada 1,5 s hasta 5 minutos. En cuanto hay sesión se sigue por donde se iba:
- **Si la ventana es ahora la puente** (`replace`): se queda hasta que quien
  llama termina de preguntar y la cierra (`closeBridge`).
- **Si no** (`open`): se cierra, y la pestaña del usuario se recarga
  (`renewBridge`). Pasa igual al abrir un proyecto y al
refrescar la lista (que ocurre al abrir el popup); en el segundo caso, al
volver, se reabre el popup con `chrome.action.openPopup()` para que la lista
aparezca sin otro clic.

**Un solo login en curso** (`loginOnce`, que guarda también el `windowId` de
su ventana). Si ya hay uno —la ventana puede estar tapada por otra— quien llega
después (`loginAction` → `join`) **no crea puente auxiliar** (quedaría
minimizada y huérfana en el dock): pone delante esa ventana
(`focusLoginWindow`, con `loginFocusUpdates`: `state: 'normal'` aparte si
estuviera minimizada, y `focused` + `drawAttention`) y espera a ese login. Al
terminar, abre su propia puente (`panelBridge`, y `renewBridge` si es una
pestaña del usuario); la ventana-puente del login es de quien lo lanzó y la
cierra él. Si la puente propia ya existía cuando otro login se adelantó, se
cierra antes de unirse. El estado se limpia al acabar el login, también por
error o cierre.

**El popup se cierra en cuanto sale la ventana de login.** El service worker
manda `chrome.runtime.sendMessage({type: 'loginStarted'})` (`notifyLoginStarted`)
al abrir la ventana (`loginOnce`) y al ponerla delante (`focusLoginWindow`),
antes de esperar al resultado; el popup lo escucha (`isLoginStarted`) y hace
`window.close()`. Sin popup, `sendMessage` rechaza con «Receiving end does not
exist» y se ignora (`isNoReceiverError`). Vale igual al abrir un proyecto: el
popup se queda en «Abriendo…» sin nada que hacer mientras se entra, y la
apertura sigue sola en el service worker. Que el popup cerrado deje sin
destinatario a `sendResponse` no rompe nada: el worker responde a un puerto
cerrado y Chrome lo descarta. Al entrar, `refreshProjects` reabre el popup
(`openPopup`); abrir un proyecto no, porque termina enfocando el grupo.

Cerrar la ventana o agotar la espera da `AuthError` (`needsLogin: true`) y el
popup enseña «Iniciar sesión en el panel», que reintenta el refresco.

La contraseña se teclea **siempre en el panel**, nunca en el popup. Tampoco va
en un iframe dentro del popup: el popup se cierra al perder el foco, y el
selector de certificado se lo lleva; además el panel prohíbe que lo enmarquen
(`frame-ancestors 'none'`).

La dirección del panel se escribe en las opciones, se normaliza y se guarda en
`chrome.storage.local` (`panelOrigin`); **no hay ninguna por defecto en el
repo**. Ahí vive también el mapa `projectGroups`
(`projectId -> groupId`). **La lista de proyectos no se guarda**: no hay caché.

**El popup no pinta ninguna lista hasta confirmar la sesión.** Al abrir solo
enseña «Preguntando al panel…» (`refrescar` en `popup.js`); la lista sale
únicamente del atajo o de `refreshProjects` con sesión confirmada
(`listView` en `lib/projects.js`). Panel caído, sin permiso de host, sin
certificado o `needsLogin` dan un aviso (con «Iniciar sesión en el panel» si
hace falta), nunca una lista vieja. Antes se pintaba la copia guardada al
instante; se quitó porque sin sesión se veía la lista un momento. Si había una
clave `projects` de versiones anteriores, queda inerte en `chrome.storage.local`.

## Piezas

- `lib/panel.js` — normalizar el origen, construir la URL con `?space=`.
- `lib/projects.js` — ordenar y filtrar (sin acentos, sin mayúsculas) y decidir
  qué enseña el popup tras preguntar al panel (`listView`: lista o aviso).
- `lib/sessions.js` — qué sesiones adoptar y si hace falta lanzar el proyecto.
- `lib/login.js` — clasificar la respuesta de `/api/me`, decidir si la puente
  se sustituye por una ventana visible, si se empieza un login o se une al que
  hay en curso, y cómo poner delante su ventana; centrar la ventana de login.
- `lib/group.js` — color estable por id, URLs previstas y reconciliación con lo
  que ya hay abierto.
- `background.js` es el único que toca las APIs de Chrome; `popup.js` y
  `options.js` no tienen lógica propia, salvo el atajo del popup.

## Acciones documentadas

- [Abrir un proyecto](abrir-proyecto.md)

## Trampas

- Los permisos de host son **opcionales** y se piden en runtime al guardar el
  origen: si se deniegan, nada funciona y el error dice «no se pudo hablar con
  el panel». Cambiar el origen no revoca el anterior ni borra el mapa de grupos.
- Se lee `sessionStorage['muxspace:active-space']` **dentro** de la pestaña del
  panel, porque el panel borra `?space=` de la URL en cuanto lo obedece; sin
  eso habría que recargar la pestaña del usuario en cada apertura.
- El service worker de MV3 se duerme: el anti-doble-clic solo protege dentro de
  una misma vida del worker, y una apertura a medias deja pestañas creadas sin
  agrupar.
- Mientras falta el certificado, `/api/me` ni falla ni contesta. La única
  señal es el silencio, así que `waitForSession` pregunta a la puente
  minimizada cada 200 ms y, si en 1,5 s no hay respuesta, la da por
  `unreachable` y la sustituye por una ventana visible. Con sesión contesta en unos cientos de ms.
  Un 401 saca la ventana enseguida.
- `probeSession` inyecta con `injectImmediately` y un tope de 3 s. Mientras
  se espera el certificado la página nunca llega a `document_idle`, y una
  inyección normal se quedaba colgada: la ventana de login nunca salía.
- En macOS, el selector de certificado que nace con la ventana minimizada no
  se pinta al restaurarla (deducido, no reproducido). Por eso no se
  restaura: se sustituye la puente por una ventana nueva y visible
  (`openLoginWindow`). Chrome recuerda el certificado elegido hasta que se
  cierra.
- Con el panel caído también se abre la ventana de login (no se distingue de
  «falta el certificado»): enseña el error de Chrome, que al menos explica
  qué pasa.
- La ventana de login es una sola (`loginOnce`): abrir un proyecto o pulsar de
  nuevo la extensión mientras hay un login espera a la misma ventana y la pone
  delante. Sin esto, la puente auxiliar nueva quedaba minimizada y huérfana
  (diagnosticado leyendo el código en macOS, no reproducido). Las pestañas de ventanas emergentes no
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
