---
dominio: sesiones
actualizado: 2026-08-28
archivos:
  - backend/tmux_service.py
  - backend/main.py
  - frontend/src/App.jsx
  - frontend/src/components/SessionGrid.jsx
  - frontend/src/components/TerminalTile.jsx
  - frontend/src/api.js
depende_de: [espacios/_dominio, biblioteca/_dominio, terminal/_dominio]
---

# Sesiones

Ciclo de vida de las sesiones del servidor de tmux (crear, listar, renombrar,
spawn, matar, enviar comandos) y su representación como ventana ("tile") en el
grid. El servidor solo conoce el catálogo de tmux más dos mapas por nombre de
sesión (espacio y proyecto): **todo lo que se ve o no se ve en el grid es
estado de cliente**.

## Entidades

- `TmuxSession` (`backend/tmux_service.py`) — `windows` (0 si tmux no lo da),
  `attached` (solo pinta el punto verde/gris), `created` epoch **en string** y
  nulable. El parser descarta en silencio una línea sin `name`.
- `SessionInfo` (`GET /api/sessions`, `backend/main.py`) añade dos campos que
  no viven en tmux:
  - `space: str|None` — id de espacio; `None` es «Sin asignar», que es la
    ausencia de entrada, no una fila.
  - `project: str|None` — **id** de proyecto, no objeto. Sale del vínculo
    explícito `session_projects`, y como plan B de casar el nombre sin el
    sufijo ` (N)` contra el título saneado de cada proyecto.

## Invariantes

- Nombre tecleable: `^[A-Za-z0-9_-]{1,64}$`, tras sustituir `/` y `\` por `_`
  (el proxy mTLS decodifica `%2F` y rompería el routing con un 405).
- Las sesiones que nacen de un comando o un proyecto NO pasan por esa regex:
  usan `_tmux_safe_label`, que solo cambia `. : / \ $` y deja espacios y
  paréntesis. Por eso existen nombres («Terminal (2)») que el usuario no podría
  teclear. El `$` se filtra porque tmux lo lee como prefijo de id de sesión y
  esa sesión quedaría inmatable.
- `kill-session` llama a `forget_session` de espacios y biblioteca **aunque la
  sesión no existiera**, para que un nombre reutilizado no herede nada.
- Cerrar la vista no toca el servidor; matar es otra acción distinta.

## Acciones documentadas

- [Crear una sesión](crear-sesion.md)
- [Renombrar una sesión](renombrar-sesion.md)
- [Estado del grid](estado-del-grid.md)

## Trampas

- `/api/detach-session` y `api.detachSession` **están muertos**: nadie los
  llama. `sidebar.detached` es solo el tooltip del punto de estado.
- El sondeo (8 s, se salta con la pestaña oculta o con otra petición en vuelo)
  nunca puede reabrir un tile: `openSessions` es un valor derivado. Antes esto
  era un registro de servidor y abrir una terminal en una pestaña la abría en
  la otra.
- `list_sessions` devuelve `[]` si el servidor de tmux murió y **no lo
  relanza**: con `exit-empty on`, un `start-server` sin sesiones deja cero
  servidores y el siguiente `new-session` lo levanta igual.
- Al crear con comando, si falla el `send-keys` la sesión **ya existe**: el
  error deja una sesión creada y vacía.
- El WebSocket no reconecta: al matar la sesión, la terminal escribe
  «desconectado» y el tile desaparece con el siguiente sondeo.
- Todas las peticiones van con `cache: 'no-store'`; sin eso el navegador
  congelaba el listado.
