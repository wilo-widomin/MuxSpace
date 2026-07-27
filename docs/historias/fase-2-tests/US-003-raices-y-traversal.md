# US-003 · Raíces y traversal en `dir_suggestions`

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P1 | 3 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero **tests que fijen dónde se puede escribir
y dónde no**, porque `dir_suggestions` es el módulo que decide eso para el
navegador de carpetas, la subida de archivos y la creación de subcarpetas.

El control está bien hecho hoy —`resolve_within_roots` resuelve los enlaces
**antes** de comprobar la contención, que es el orden correcto—, y
precisamente por eso hay que clavarlo: es el tipo de detalle que se pierde en
el siguiente refactor.

## Criterios de aceptación

Cada caso, un test con nombre que se lea solo:

- [ ] `../` explícito en la ruta → rechazado (no se sale de la raíz).
- [ ] **Symlink de directorio que apunta fuera de las raíces** → rechazado.
      Este es el caso que justifica resolver los enlaces antes de comparar.
- [ ] Ruta absoluta fuera de raíz (`/etc`, `/`) → rechazada.
- [ ] `~` de **otro** usuario (`~root`, `~nobody`) → rechazado; `~` a secas
      se expande al home del usuario que corre el backend.
- [ ] Raíz configurada que **no existe** → no revienta; el módulo la ignora
      y sigue con las demás.
- [ ] `resolve_within_roots("")` → devuelve la **primera raíz** configurada.
- [ ] `create_dir` con `..` en el nombre → rechazado.
- [ ] `create_dir` con un nombre válido → crea la carpeta **dentro** de la
      raíz y devuelve su ruta abreviada.
- [ ] `browse` de una carpeta inexistente → `None` (que el endpoint traduce
      a 404), no una excepción.
- [ ] `browse` en la raíz → `parent` es `None` (no se puede subir más).
- [ ] `suggest` con un prefijo devuelve solo subdirectorios inmediatos que
      casan, y **nunca** algo de fuera de las raíces.
- [ ] Todos los casos usan raíces bajo `tmp_path`. Ningún test toca el home
      real ni `backend/data/`.

## Alcance técnico

- `backend/tests/test_dir_roots.py`.
- Las raíces se fijan con `MUXSPACE_DIR_SUGGESTION_ROOTS` apuntando a
  `tmp_path` (ver el conftest de US-001).
- Monta el escenario con el propio filesystem temporal: una raíz
  `tmp_path/raiz`, un `tmp_path/fuera` como destino de los symlinks, y
  enlaces de directorio creados con `Path.symlink_to(..., target_is_directory=True)`.
- Comprueba el **contrato observable** del módulo (`suggest`,
  `resolve_within_roots`, `browse`, `create_dir`), no sus funciones privadas.

## Fuera de alcance

- Los endpoints HTTP que lo usan (`/api/dir-browse`, `/api/dir-create`,
  `/api/upload`): sus tests están en US-004.
- Cambiar `dir_suggestions.py`. Si un caso falla, **para y avisa**: es un
  hallazgo, no un arreglo que se cuela en el PR de un test.

## Dependencias

US-001.

## Rigor

`exhaustivo`. Decide dónde puede escribir un panel que ya da shell.

## Concurrencia

`compartida`. Solo crea `test_dir_roots.py`.

## Notas para el agente

- El símbolo a proteger es el **orden**: resolver enlaces y *después*
  comprobar contención. Si algún test tuyo pasaría igual con el orden
  invertido, no está probando lo que crees.
- Para el caso de `~otro-usuario`, usa un usuario que exista seguro en
  cualquier Linux (`root`) y no dependas de que exista su home.
- Objetivo de cobertura para este módulo: **≥85%**.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-27 15:11:17 UTC
- Fin:    2026-07-27 15:27:25 UTC
- Tiempo transcurrido: 00:16:08 (HH:mm:ss)
- PR:     #5
- Estado: in-review
