---
dominio: espacios
actualizado: 2026-08-28
archivos:
  - backend/space_store.py
  - backend/main.py
  - frontend/src/spaces.js
  - frontend/src/components/sidebar/SpacesBar.jsx
depende_de: [sesiones/_dominio, biblioteca/_dominio]
---

# Espacios

Agrupa sesiones de tmux en carpetas con nombre (un cliente, un proyecto): cada
sesión pertenece como mucho a una, y la pestaña filtra sidebar y grid por el
espacio activo. Los espacios y la pertenencia son estado de servidor; qué
espacio mira cada pestaña, no.

## Entidades

- `Space` (`backend/space_store.py`) — `id` (`sp_` + hex aleatorio), `title` (máx. 60,
  no vacío, **sin unicidad**) y `order` (se fija al crear; no hay endpoint para
  reordenar).
- Persistencia: `backend/data/spaces.json`, con la forma
  `{"spaces": [...], "assignments": {nombre_sesion: space_id}}`. Se reescribe
  entero en cada cambio.
- **La clave de `assignments` es el nombre de la sesión**, no un id estable.
- «Sin asignar» (`UNASSIGNED = "unassigned"`, en backend y frontend) es la
  ausencia de entrada: no ocupa fila.
- La lectura nunca lanza: archivo ausente, corrupto o que no es un dict →
  espacios vacíos.

## Invariantes

- «Sin asignar» no se puede renombrar ni borrar: el frontend deshabilita los
  botones y el backend no encuentra el id.
- Borrar un espacio **nunca mata sesiones**: se purgan sus asignaciones y sus
  sesiones caen a «Sin asignar»; la pestaña que lo estuviera mirando salta ahí.
- Renombrar una sesión arrastra su asignación; matarla la olvida, para que otra
  sesión con el mismo nombre no herede el espacio.
- Asignar a un id inexistente da 400 `err.space_not_found`; el endpoint
  comprueba antes que la sesión exista en tmux.

## Trampas

- El espacio activo de la pestaña vive en **sessionStorage**
  (`muxspace:active-space`), no en localStorage ni en el servidor: es lo que
  permite tener dos pestañas mirando cosas distintas. Ver
  [estado del grid](../sesiones/estado-del-grid.md).
- Los títulos no son únicos, pero abrir un proyecto en pestaña nueva y la
  migración de arranque casan **por título**: dos espacios homónimos hacen que
  deje de ser determinista cuál se usa.
- «Todas» ya no existe en el selector: el valor `all` solo sobrevive para
  degradar sessionStorage viejo a «Sin asignar». En el dashboard el equivalente
  es el filtro vacío, que no es el mismo valor.
- Crear una sesión estando en «Sin asignar» no asigna nada, y eso es correcto
  por definición, no un olvido.
- Un espacio borrado desde otra pestaña deja a esta filtrando por un id
  fantasma: el grid se queda vacío y no hay saneo.
