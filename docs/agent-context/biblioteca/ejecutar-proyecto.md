---
dominio: biblioteca
accion: ejecutar-proyecto
actualizado: 2026-08-28
archivos:
  - backend/main.py
  - backend/tmux_service.py
  - backend/library_store.py
  - frontend/src/App.jsx
depende_de: [sesiones/crear-sesion, espacios/_dominio]
---

# Ejecutar un proyecto

`POST /api/projects/{id}/run` crea una sesión de tmux nueva, la sitúa en el
directorio del proyecto, lanza sus comandos, la mete en el espacio del proyecto
y la vincula a él para que la cabecera muestre sus enlaces.

## Flujo

1. `_tmux_safe_label(title)` + `_next_label_name` → nombre de la sesión.
2. `create_session(name, command=commands[0], cwd=proj.cwd)` — el shell nuevo
   ejecuta literalmente `cd <cwd citado> && <primer comando>`.
3. El resto de comandos, uno a uno con `send-keys`.
4. `space_store.assign` (los errores se ignoran: la sesión ya existe) y
   `library_store.link_session(name, project_id)`.
5. Se audita como `run-project`, con cwd y comandos.

## Reglas

- El nombre es el título saneado; si ya hay sesiones con ese nombre, se numera
  `título (2)`, `(3)`… Hay un reintento ante carrera y luego 409.
- «Abrir en pestaña nueva» (`handleRunProjectInNewTab`) busca el espacio **por
  título** (trim, sin distinguir mayúsculas), lo crea si falta y solo lanza
  sesión si el espacio está vacío; luego abre `?space=<id>`. Por eso pulsar dos
  veces no acumula `proyecto (2)`, `(3)`.

## Trampas

- Los comandos van al **mismo shell y en orden**, pero solo el primero está
  encadenado con `&&` al `cd`; los siguientes se teclean **sin esperar** a que
  el anterior termine. Si el primero es interactivo (`claude`, `nvim`), los
  demás se escriben dentro de ese programa, no en el shell.
- Si el `cd` falla, el primer comando no llega a ejecutarse (por el `&&`), pero
  los siguientes sí se teclean.
- El vínculo sesión→proyecto tiene un plan B: casar el nombre sin el sufijo
  ` (N)` contra el título saneado. Se rompe al renombrar la sesión o el
  proyecto, y solo existe para las sesiones anteriores al vínculo explícito.
