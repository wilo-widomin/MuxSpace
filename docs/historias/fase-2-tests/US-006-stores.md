# US-006 · Stores: CRUD, JSON corrupto y escritura atómica

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-2-tests | S1 |

## Historia

Como usuario del panel, quiero **no perder mi biblioteca de comandos ni mis
espacios** por un JSON a medio escribir o un archivo corrupto, así que quiero
tests que fijen las dos propiedades que lo garantizan: leer tolera la basura,
escribir es atómico.

Los cuatro stores comparten hoy `datafiles.write_private` (tmp + replace +
0600). Antes no: `upload_store` y `space_store` reescribían en sitio. Estos
tests son los que impiden volver atrás.

## Criterios de aceptación

**`library_store`**:

- [ ] CRUD completo de comandos: crear, listar, obtener por id, actualizar,
      borrar. Borrar un id inexistente → `False`, no excepción.
- [ ] CRUD completo de proyectos, igual.
- [ ] Comando sin texto → `LibraryError("err.command_empty")`.
- [ ] Comando sin etiqueta → se genera una por defecto a partir del comando,
      recortada a 60 caracteres con `…`.
- [ ] Proyecto sin comandos → `LibraryError("err.project_needs_command")`.
- [ ] Proyecto sin título → `LibraryError("err.project_title_required")`.
- [ ] JSON **corrupto** → biblioteca vacía, sin excepción.
- [ ] JSON que no es un objeto (una lista, un número) → biblioteca vacía.
- [ ] Entradas malformadas dentro de un JSON válido (sin `command`, sin
      `title`, no-dict) → se descartan **esas**, las buenas se conservan.

**`space_store`**:

- [ ] Crear, renombrar y borrar espacios; borrar uno inexistente →
      `SpaceError("err.space_not_found")`.
- [ ] Título vacío → `err.space_title_empty`; título de más de 60 →
      `err.space_title_too_long` con el parámetro `max`.
- [ ] Borrar un espacio devuelve sus sesiones a "sin asignar" y **no toca**
      las demás asignaciones.
- [ ] `assign` a un espacio inexistente → error; `assign` a `None` o a
      `"unassigned"` quita la asignación.
- [ ] `rename_session` arrastra la asignación al nombre nuevo.
- [ ] `forget_session` la elimina.
- [ ] JSON corrupto → estructura vacía, sin excepción.

**`upload_store`**:

- [ ] `add` mete al frente y recorta a `KEEP`.
- [ ] `add` de una ruta ya registrada la sustituye, no la duplica.
- [ ] `remove` quita la entrada y devuelve el historial resultante.
- [ ] JSON corrupto → historial vacío.

**Atomicidad y permisos (los tres stores)**:

- [ ] Tras cualquier escritura no queda ningún `.tmp` en el directorio.
- [ ] Los ficheros quedan a **0600** y el directorio a **0700**.
- [ ] Si la escritura del temporal falla a mitad (simúlalo haciendo que
      `os.fdopen(...).write` lance), **el archivo anterior queda intacto** y
      no se queda un `.tmp` huérfano. Es la propiedad que da el tmp + replace.

## Alcance técnico

- `backend/tests/test_stores.py`. Un archivo con tres bloques, o tres
  archivos: a tu criterio, pero que se lea qué store cubre cada test.
- Los `_STORE_PATH` apuntan a `tmp_path` (conftest de US-001).
- Prueba el **contrato público** de cada módulo (`add_command`,
  `create_space`, `list_recent`…), no `_load` ni `_persist`. La excepción es
  el test de atomicidad, que necesita provocar el fallo a bajo nivel.

## Fuera de alcance

- Los endpoints HTTP que envuelven a los stores.
- La concurrencia entre procesos (los locks son de proceso a propósito; ver
  US-023).
- Cambiar los stores. Si un caso falla, **para y avisa**.

## Dependencias

US-001.

## Rigor

`estándar`.

## Concurrencia

`compartida`.

## Notas para el agente

- La regla que unifica casi todos estos casos: **leer nunca lanza, escribir
  nunca deja el archivo a medias**. Si un test tuyo no comprueba una de las
  dos, pregúntate qué aporta.
- `library.json` son los comandos que el panel ejecuta. Un test que los
  corrompa en `backend/data/` sería el peor bug de toda la fase: comprueba
  que el conftest te está aislando antes de escribir el primer test.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-27 16:41:15 UTC
- Fin:    2026-07-27 16:57:35 UTC
- Tiempo transcurrido: 00:16:20 (HH:mm:ss)
- PR:     #10
- Estado: in-review
