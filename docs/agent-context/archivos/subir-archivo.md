---
dominio: archivos
accion: subir-archivo
actualizado: 2026-08-28
archivos:
  - backend/main.py
  - backend/upload_store.py
  - backend/dir_suggestions.py
  - frontend/src/components/sidebar/UploadFiles.jsx
  - frontend/src/api.js
depende_de: [acceso/_dominio]
---

# Subir un archivo

`POST /api/upload?dir=&name=` con los **bytes crudos en el cuerpo** (no
multipart). Deja el archivo en una carpeta real del host y devuelve su ruta
absoluta para pegarla en una terminal.

## Flujo

1. `UploadFiles.jsx` (input o arrastrar y soltar, un archivo) → `api.uploadFile`.
2. `resolve_within_roots(dir)` → `_unique_target(name)` → `os.open` con
   `O_EXCL | O_NOFOLLOW` y modo 0600. **El destino se abre ANTES de leer el
   cuerpo**, así que un 409 por nombre ocupado llega sin haber subido nada.
3. `_stream_to_fd` vuelca el cuerpo al descriptor **según llega**, cortando por
   `Content-Length` y luego por lo leído. `await request.body()` no vale:
   bufferiza entero antes de poder mirarlo. Cualquier fallo en el camino borra
   el fichero a medias, que con el nombre bueno sería peor que nada.
4. `upload_store.add()` (historial de 5) y `audit.record("upload", ...)`.
5. El frontend copia `quotePath(path)` al portapapeles.

## Reglas

- Nombre: `^[^/\\\x00]+$`, y ni `.` ni `..`.
- La carpeta destino tiene que estar dentro de las raíces permitidas
  (`MUXSPACE_DIR_SUGGESTION_ROOTS`, por defecto el home del usuario que corre
  el backend).
- `ELOOP` al abrir se traduce a 409 «ya existe»: no se sigue el enlace.

## Trampas

- La subida **no** retiene el cuerpo en memoria (SEC-006), pero
  `paste-image` (25 MB) y la campanilla (2 MB) siguen con `_read_capped`, que
  sí lo acumula entero: sus consumidores reciben los bytes en la mano.
- En el historial, `dir` es el string tal cual lo mandó el frontend (abreviado
  con `~`) mientras que `path` es absoluto y resuelto: no coinciden en forma.
- Una carpeta válida pero donde el proceso no puede escribir da un 500 con
  `err.upload_failed` genérico, no un mensaje útil.
- Borrar una entrada del historial no borra el archivo; el archivo no se borra
  nunca desde el panel.
