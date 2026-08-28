---
dominio: sesiones
accion: renombrar-sesion
actualizado: 2026-08-28
archivos:
  - backend/tmux_service.py
  - backend/main.py
  - frontend/src/App.jsx
  - frontend/src/components/TerminalTile.jsx
  - frontend/src/components/Sidebar.jsx
depende_de: [espacios/_dominio, biblioteca/_dominio]
---

# Renombrar una sesión

Dos entradas para la misma acción: el lápiz del sidebar y el **doble clic sobre
el nombre en la cabecera de la ventana** (Enter guarda, Escape o perder el foco
cancelan; mientras se edita la cabecera deja de ser asa de arrastre). Existe
porque las sesiones lanzadas desde un proyecto se llaman como el proyecto con
un número detrás, y con varias abiertas ese número no identifica nada.

## Flujo

1. `TerminalTile:submitRename` o `Sidebar:submitRename` →
   `App.jsx:handleRenameSession` → `POST /api/rename-session/{name}`.
2. El endpoint valida el nombre nuevo, llama a `tmux rename-session` y arrastra
   los dos mapas del servidor: `space_store.rename_session` y
   `library_store.rename_session`.
3. En cliente, `handleRenameSession` mueve a la clave nueva el estado que
   guarda el nombre viejo: `activeName`, `order` y `hidden`. Luego
   `loadSessions()`.

## Reglas

- Mismo nombre → no se llama a tmux (los stores cortan solos con `old == new`).
- Se aplica la misma validación que al crear: `^[A-Za-z0-9_-]{1,64}$` tras
  sustituir `/` y `\`. Una sesión llamada «Terminal (2)» no se puede renombrar
  a otro nombre con espacios.
- El tile del grid no hay que tocarlo: `openSessions` es derivado de
  `sessions`, así que se recalcula solo con el nombre nuevo.

## Trampas

- `loadSessions` purga de `hidden` los nombres que ya no existen, así que
  mover el nombre en `hidden` tiene que ocurrir **antes** de recargar: si no,
  una ventana que el usuario había cerrado reaparece.
- Renombrar desde tmux directamente (fuera del panel) rompe en silencio el
  vínculo con el espacio y con el proyecto: la clave de los dos mapas es el
  nombre de la sesión.
