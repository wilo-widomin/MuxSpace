---
dominio: sesiones
accion: crear-sesion
actualizado: 2026-09-01
archivos:
  - backend/tmux_service.py
  - backend/main.py
  - frontend/src/components/Sidebar.jsx
  - frontend/src/App.jsx
depende_de: [espacios/_dominio, biblioteca/ejecutar-proyecto]
---

# Crear una sesión

Hay cuatro caminos que acaban en una sesión de tmux nueva: el formulario del
sidebar, el botón de terminal de la cabecera de un tile (spawn), lanzar un
comando de la biblioteca y ejecutar un proyecto. Solo el primero deja al
usuario elegir el nombre.

## Flujo

1. Formulario → `App.jsx:handleCreateSession` → `api.createSession` →
   `POST /api/create-session/{name}` → `tmux_service.create_session()`.
2. **Después** `assignToActiveSpace(name)`, luego `loadSessions()` y
   `handleSelect()`. El orden importa: sin la asignación, la sesión nueva cae
   en «Sin asignar» y no aparece en el espacio que estás mirando.
3. Spawn: `TerminalTile` → `SessionGrid` → `App.jsx:handleSpawnTerminal` →
   `POST /api/sessions/{name}/spawn`. El **espacio** lo pone el cliente
   (`assignToActiveSpace`, igual que el formulario); el **proyecto** lo hereda
   el backend de la sesión de origen.

## Reglas

- Con `cwd` y `command`, `create_session` NO usa `new-session -c`: manda
  `send-keys "cd <cwd> && <command>"`. `_quote_path` expande `~` **antes** de
  `shlex.quote`, porque citar `'~/x'` haría `cd` a un directorio llamado `~`.
  El comando va sin escapar: es shell por diseño.
- **El cwd del spawn no viaja desde el cliente**: lo lee el servidor con
  `pane_info` (`pane_current_path`). Si no lo sabe, crea la sesión sin `cd`.
- **El spawn hereda el proyecto de la sesión madre**: el endpoint lo resuelve
  con `_project_of(name)` —vínculo explícito y, si no hay, el plan B por
  título— y escribe `library_store.link_session(new_name, ...)`. Sin ese
  vínculo explícito la hija se quedaría sin los enlaces de la cabecera para
  siempre, porque su nombre (`Terminal (N)`) no casa con ningún título.
- `_next_label_name(base)` cuenta las existentes que casan `base` o `base (n)`
  y usa `count+1`, incrementando si choca; hay un reintento y luego 409.

## Trampas

- El número del sufijo refleja el **recuento**, no el máximo: al cerrar sesiones
  intermedias los números se reciclan.
- Nombre base del spawn: `Terminal`, con espacios y paréntesis en el sufijo —
  legal ahí, ilegal en el formulario.
