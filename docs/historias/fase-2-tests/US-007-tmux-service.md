# US-007 · `tmux_service` contra un tmux real

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 3 | fase-2-tests | S1 |

## Historia

Como responsable del panel, quiero **tests de `tmux_service` contra tmux de
verdad**, porque es la frontera con el sistema y un mock solo probaría que
sé escribir mocks.

Lo que hay que fijar aquí es `_quote_path`: expande `~` **antes** de
`shlex.quote`, y el comentario del código explica por qué. Es exactamente el
detalle que se pierde en el siguiente refactor, y perderlo significa que un
`cd` a una ruta con espacios deja de funcionar — o peor.

## Criterios de aceptación

**Ciclo de vida de sesiones** (con tmux real):

- [ ] Crear una sesión → `True`, y `session_exists` la ve.
- [ ] Crear una sesión con el **mismo nombre** → `False` (no lanza).
- [ ] Renombrar una sesión: el nombre viejo deja de existir, el nuevo existe.
- [ ] Matar una sesión → `True`; matar una inexistente → `False`, no
      excepción.
- [ ] `list_sessions` devuelve la sesión creada con sus campos (`name`,
      `windows`, `attached`, `created`).
- [ ] Crear una sesión con `cwd` la deja posicionada en esa carpeta.
- [ ] Crear una sesión con `command` ejecuta el comando en su shell.

**`_quote_path`** (sin tmux, es función pura):

- [ ] Ruta limpia → sin comillas.
- [ ] Ruta con **espacios** → entrecomillada.
- [ ] Ruta con `$(...)`, backticks, `;`, `&&`, `|` → entrecomillada de forma
      que el shell **no la interprete**.
- [ ] `~` se expande al home **antes** de entrecomillar: el resultado no
      contiene un `~` entre comillas (que el shell ya no expandiría).
- [ ] `~/carpeta con espacios` → expandido **y** entrecomillado.
- [ ] Ruta vacía o `None` → comportamiento definido y probado.

**Aislamiento de los tests**:

- [ ] Todas las sesiones de prueba llevan un **prefijo propio**
      (`muxspace-test-<algo único>`) que no puede chocar con las sesiones
      reales del usuario.
- [ ] El teardown mata **solo** las sesiones con ese prefijo, pase lo que
      pase (fixture con `yield` + limpieza, no un `kill` al final del test).
- [ ] Si `tmux` no está disponible, los tests que lo necesitan se marcan
      `skip` con un motivo legible; los de `_quote_path` siguen corriendo.
- [ ] Los tests usan un **socket de tmux propio** (`tmux -L <nombre>`) si el
      código lo permite; si no, documenta en el test por qué se corre contra
      el servidor por defecto y por qué el prefijo es suficiente.

## Alcance técnico

- `backend/tests/test_tmux_service.py`.
- El binario sale de `config.TMUX_BINARY`.
- En CI hará falta `apt-get install -y tmux` (lo añade US-009; aquí basta
  con que el `skip` funcione si no está).
- **El usuario tiene sesiones de tmux reales abiertas en esta máquina.** El
  prefijo y el teardown selectivo no son una formalidad: un `tmux
  kill-server` en un test le cierra el trabajo. Ni se te ocurra.

## Fuera de alcance

- `pty_bridge` y el WebSocket del terminal (se tocan en US-021 y US-025).
- Los endpoints HTTP de sesiones.
- Cambiar `tmux_service.py`. Si un caso falla, **para y avisa**.

## Dependencias

US-001.

## Rigor

`estándar`.

## Concurrencia

`exclusiva`. Crea y mata sesiones de tmux reales: no puede correr a la vez
que otra US que también las toque.

## Notas para el agente

- La propiedad de fondo es que **tmux se invoca siempre por `argv`, nunca
  por shell**: la inyección de comandos vía nombre de sesión no existe como
  categoría en este proyecto. Un test con un nombre de sesión tipo
  `$(touch /tmp/pwned)` que compruebe que ese fichero **no** aparece es
  buena inversión.
- `_quote_path` es privada, pero es el núcleo del riesgo: pruébala directa.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-27 16:58:05 UTC
- Fin:    2026-07-27 17:21:23 UTC
- Tiempo transcurrido: 00:23:18 (HH:mm:ss)
- PR:     #11
- Estado: in-review
