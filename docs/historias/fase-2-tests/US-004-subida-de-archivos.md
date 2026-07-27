# US-004 · Subida de archivos: regresiones de S3 y S4

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 5 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero **tests que reproduzcan los dos hallazgos
de la auditoría que ya se corrigieron a mano en `/api/upload`**, para que
nadie los reintroduzca en el siguiente refactor.

S3 (escritura fuera de las raíces vía symlink) llegó a confirmarse **con una
PoC ejecutada contra el backend real**: un symlink colgante en el home hacía
que `Path.exists()` viera un hueco libre y `write_bytes` escribiera en el
destino del enlace. S4 (el cuerpo se bufferizaba entero antes de mirar el
tamaño) tumbaba el proceso con un POST de varios GB.

## Criterios de aceptación

**Regresión de S3** (la importante):

- [ ] Con un **symlink colgante** en la carpeta destino y un `name` que
      coincide con él: la respuesta es **4xx** (409) y el fichero al que
      apunta el enlace **no se crea**. Los dos asertos, no solo el código.
- [ ] Con un symlink **vivo** apuntando a un fichero fuera de las raíces:
      el contenido de ese fichero **no cambia**.
- [ ] Ambos casos montan el symlink bajo `tmp_path`. Nunca en el home real.

**Regresión de S4**:

- [ ] `Content-Length` declarado por encima del tope → **413**, y el archivo
      no se crea.
- [ ] Cuerpo sin `Content-Length` (chunked) que supera el tope → **413**.
- [ ] El mismo caso para `/api/paste-image` con su tope propio (25 MB frente
      a los 100 MB de `/api/upload`).
- [ ] Un cuerpo por debajo del tope sigue funcionando (control: 200).

**Validación de nombres y destino**:

- [ ] `name` inválido → 400: `../x`, `a/b`, `.`, `..`, cadena vacía, y un
      nombre con `\x00`.
- [ ] `dir` fuera de las raíces (`/etc`) → 400.
- [ ] Colisión de nombre → el archivo se guarda como `nombre (2).ext` y la
      respuesta devuelve ese nombre; el original **no se pisa**.
- [ ] Segunda colisión → ` (3)`.

**Historial y permisos**:

- [ ] El historial (`upload_store`) recorta a `KEEP` entradas.
- [ ] Subir dos veces la misma ruta no duplica la entrada del historial.
- [ ] `DELETE /api/uploads` quita la entrada y **no borra el archivo del
      disco**.
- [ ] El archivo subido queda a **0600** y no queda ningún `.tmp` suelto.

## Alcance técnico

- `backend/tests/test_upload.py`.
- Las raíces de subida apuntan a `tmp_path` (conftest de US-001).
- Para el caso "sin `Content-Length`", `TestClient` de httpx admite pasar un
  generador como `content=`, que produce una petición chunked. Si resultara
  imposible con `TestClient`, levanta la app con uvicorn en un puerto libre y
  habla por socket; deja escrito **por qué** en el test.
- El tope real es de 100 MB: **no generes 100 MB de datos**. Baja el tope en
  el test con `monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", ...)` y
  documenta que lo que se prueba es el mecanismo, no la constante.
- Añade un test que fije el valor de las constantes (`_UPLOAD_MAX_BYTES`,
  `_PASTE_MAX_BYTES`, `_PASTE_KEEP`, `upload_store.KEEP`), para que bajarlas
  o subirlas sea un cambio consciente.

## Fuera de alcance

- Cambiar `main.py`. El código ya está corregido (PR #1); esta US solo
  levanta la red. Si un caso falla, **para y avisa**.
- El navegador de carpetas (`/api/dir-browse`, `/api/dir-create`): US-003
  cubre el módulo y aquí solo se usan de apoyo.
- Cobertura del WebSocket o de tmux.

## Dependencias

US-001.

## Rigor

`exhaustivo`. Reproduce un hallazgo confirmado con PoC contra el backend
real.

## Concurrencia

`compartida`. Solo crea `test_upload.py`.

## Notas para el agente

- El criterio "y **no escribe** el fichero destino" es el corazón de esta
  US. Un test que solo compruebe el 409 pasaría igual con el bug puesto si
  alguien cambia el código de error: **comprueba siempre el efecto en el
  filesystem**.
- La PoC original está en `docs/auditoria-2026-07.md`, sección S3, con los
  comandos exactos. Tradúcela a pytest tal cual.
- Objetivo de cobertura para los endpoints de subida: **≥85%**.
