---
dominio: biblioteca
actualizado: 2026-08-28
archivos:
  - backend/library_store.py
  - backend/main.py
  - frontend/src/components/Sidebar.jsx
  - frontend/src/components/sidebar/CommandSelect.jsx
  - frontend/src/api.js
depende_de: [sesiones/_dominio, espacios/_dominio]
---

# Biblioteca

Piezas reutilizables para lanzar terminales: **comandos** de una línea y
**proyectos** (título + directorio + secuencia de comandos + enlaces +
espacio). Además guarda el mapa `sesión -> proyecto`, que es lo que permite
pintar los enlaces del proyecto en la cabecera de su ventana.

## Entidades

Todo vive en un único JSON, `backend/data/library.json`, con la forma
`{commands, projects, session_projects}`. (`backend/data/commands.json` es
residuo: no lo lee nadie.)

- `Command` — `id`, `label`, `command`. Sin `label` se usa el propio comando
  truncado a 60 caracteres.
- `Project` — `title` obligatorio, `cwd` (`None` si vacío), `commands` (al menos
  uno; los vacíos se descartan), `links` (máx. 12), `space` (id de espacio, que
  **el store no valida**).
- `Link` — `url` obligatoria; sin `title` se usa el `netloc`, truncado a 40.
- Los ids son `secrets.token_hex(4)`. No hay unicidad de título ni de etiqueta.
- Sin caché: cada operación relee y reescribe el archivo entero bajo un lock de
  proceso. De ahí el requisito de un solo worker.

## Invariantes

- URLs solo `http`/`https`. Sin `://` se prefija `https://`, pero si ya hay un
  `esquema:` se rechaza: así `javascript:alert(1)` no se convierte en URL
  válida.
- Solo el **cwd** se entrecomilla (`shlex.quote`, con `~` expandido antes). Los
  comandos se pasan tal cual: son shell por diseño.
- Al crear un proyecto sin espacio, el backend crea uno con el título del
  proyecto y **lo revierte** si el alta falla.

## Acciones documentadas

- [Ejecutar un proyecto](ejecutar-proyecto.md)

## Trampas

- El proyecto guarda **las líneas de comando**, no ids: borrar un comando de la
  biblioteca no afecta a ningún proyecto.
- Borrar un proyecto purga sus entradas de `session_projects` (las terminales
  vivas pierden las badges) pero **no** mata sesiones ni borra el espacio que
  se creó con él, que queda huérfano.
- Los enlaces no se copian a la sesión: el frontend resuelve
  `session.project -> projects[].links` en cada render, así que editarlos se
  refleja al instante en las ventanas abiertas.
- Un `space` que apunta a un espacio borrado sigue en disco; la API lo devuelve
  como `null`.
- Las filas de enlace a medio escribir se filtran en el cliente; sin eso el
  backend rechazaría el proyecto entero.
