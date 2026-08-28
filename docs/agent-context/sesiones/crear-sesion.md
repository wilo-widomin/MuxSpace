---
dominio: sesiones
accion: crear-sesion
actualizado: 2026-08-28
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
   `POST /api/sessions/{name}/spawn`.

## Reglas

- Con `cwd` y `command`, `create_session` NO usa `new-session -c`: manda
  `send-keys "cd <cwd> && <command>"`. `_quote_path` expande `~` **antes** de
  `shlex.quote`, porque citar `'~/x'` haría `cd` a un directorio llamado `~`.
  El comando va sin escapar: es shell por diseño.
- **El cwd del spawn no viaja desde el cliente**: lo lee el servidor con
  `pane_info` (`pane_current_path`). Si no lo sabe, crea la sesión sin `cd`.
- `_next_label_name(base)` cuenta las existentes que casan `base` o `base (n)`
  y usa `count+1`, incrementando si choca; hay un reintento y luego 409.

## Trampas

- El número del sufijo refleja el **recuento**, no el máximo: al cerrar sesiones
  intermedias los números se reciclan.
- Nombre base del spawn: `Terminal`, con espacios y paréntesis en el sufijo —
  legal ahí, ilegal en el formulario.
