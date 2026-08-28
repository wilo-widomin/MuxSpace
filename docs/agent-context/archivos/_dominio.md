---
dominio: archivos
actualizado: 2026-08-28
archivos:
  - backend/upload_store.py
  - backend/datafiles.py
  - backend/dir_suggestions.py
  - backend/main.py
  - frontend/src/components/sidebar/UploadFiles.jsx
  - frontend/src/components/sidebar/PasteForClaude.jsx
  - frontend/src/components/sidebar/DirBrowserModal.jsx
  - frontend/src/lib/paths.js
depende_de: [acceso/_dominio, espacios/_dominio]
---

# Archivos

Mete bytes en la máquina del panel desde el navegador por dos vías: **pegar
imágenes** (destino fijo, para pasárselas a Claude) y **subir archivos** a una
carpeta real elegida con un navegador de carpetas. Todo lo que llega a disco
devuelve una ruta absoluta que el frontend copia al portapapeles **ya escapada
para pegar en un shell**.

## Dónde acaba cada cosa

- Imágenes pegadas → `backend/data/pastes/paste-NNN.<ext>`, con el índice
  secuencial y la extensión derivada del tipo MIME. Retención **por conteo**:
  se conservan las 5 últimas.
- Archivos subidos → la carpeta que eligió el usuario, con el nombre original;
  en colisión se añade ` (2)`, ` (3)`… antes de la extensión. **No se borran
  nunca.** Lo único con caducidad es el historial
  (`backend/data/upload_history.json`, últimas 5 entradas).
- El destino elegido se recuerda en `localStorage` **por espacio**, con `~/tmp`
  por defecto.

## Reglas de seguridad

- **Puerta única**: `dir_suggestions.resolve_within_roots()` expande, resuelve
  (siguiendo symlinks y `..`) y exige que el resultado caiga dentro de las
  raíces configuradas y sea un directorio. La usan navegar, crear carpeta y
  subir; ninguna escritura toca disco sin pasar por ahí.
- Nombres: el archivo subido no admite `/`, `\`, nulos, `.` ni `..`; la carpeta
  nueva tampoco admite empezar por punto, y se crea sin padres.
- El destino se abre con `O_EXCL | O_NOFOLLOW`, porque comprobar la existencia
  sigue enlaces y ve un **symlink colgante como hueco libre** — escribiría
  fuera de las raíces.
- Topes: 25 MB una imagen pegada, 100 MB una subida, cortando primero por
  `Content-Length` y luego mientras se lee el cuerpo. Solo el pegado valida el
  tipo (lista blanca); la subida acepta cualquiera.
- Los listados filtran hijo a hijo, porque un symlink dentro de la raíz puede
  apuntar fuera.
- **El frontend no valida nada**: ni tamaño, ni tipo, ni nombre.

## Acciones documentadas

- [Subir un archivo](subir-archivo.md)

## Trampas

- `frontend/src/lib/paths.js` (`quotePath`) usa **comillas dobles** a propósito,
  para que el shell siga expandiendo `~`; el backend resuelve el mismo problema
  al revés (`shlex.quote` con `~` ya expandido). Son dos implementaciones del
  mismo cuidado, y las dos tienen que seguir existiendo.
- El índice de `paste-NNN` se calcula sin lock y sin `O_EXCL`: dos pegados a la
  vez pueden pisarse.
- La retención de capturas ordena por el número del nombre, no por fecha.
- Se sube **un archivo por vez**, sin multiselección ni barra de progreso.
- Una carpeta sin permisos se lista como vacía en vez de dar error.
