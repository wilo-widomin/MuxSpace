---
dominio: acceso
accion: token-de-scripts
actualizado: 2026-11-05
archivos:
  - backend/script_token.py
  - backend/script_policy.py
  - backend/config.py
  - backend/main.py
  - backend/library_store.py
  - backend/space_store.py
  - backend/.env.example
  - backend/tests/test_auth_contract.py
  - backend/tests/test_script_token.py
depende_de: [acceso/_dominio, biblioteca/ejecutar-proyecto, espacios/_dominio]
---

# Token de scripts

Un proceso de la misma máquina puede crear un proyecto de la biblioteca,
lanzarlo, matar su sesión y borrarlo sin cookie y sin la contraseña del
sistema. Lo necesita el receptor de entrevistas, que corre programado.

No es una shell: solo deja guardar y lanzar un comando de la lista blanca, y
solo toca lo que creó él.

## Puesta en marcha

En `backend/.env`:

    MUXSPACE_SCRIPT_COMMAND_PREFIX="CLAUDIFY_PROJECT=mvp-lab-skills claude"
    # Opcional; este es el valor por defecto.
    MUXSPACE_SCRIPT_CWD_ROOT=~/proyectos/mvp-lab-proyectos

`config.py` lee el entorno al arrancar: cambiar estas dos variables pide
reiniciar `proj-tmux`. Sin prefijo, crear con token da siempre 403.

El token se genera a mano, desde la raíz del repositorio:

    backend/venv/bin/python backend/script_token.py generate

Lo imprime una sola vez por la salida estándar y no se guarda en ningún sitio:
en `backend/data/script_token_hashes.json` (0600) solo queda su huella SHA-256.
El arranque no genera nada, y sin haberlo generado el token no abre nada.

Se usa en la cabecera `X-Muxspace-Script-Token`, contra `127.0.0.1`:

    curl -s -H "X-Muxspace-Script-Token: $MUXSPACE_SCRIPT_TOKEN" http://127.0.0.1:8000/api/projects

## Rotar

    backend/venv/bin/python backend/script_token.py generate         # nuevo; el anterior sigue valiendo
    backend/venv/bin/python backend/script_token.py retire-previous  # retira el anterior
    backend/venv/bin/python backend/script_token.py status           # qué huellas hay activas

Hay dos activos como mucho: un tercero expulsa al más antiguo, y el comando lo
avisa. **El panel no necesita reiniciarse**: relee el archivo cuando cambia.
Para dejarlo todo cerrado basta con borrar ese archivo.

## Qué abre

Solo estas rutas, enumeradas por método en `RUTAS_CON_TOKEN_DE_SCRIPTS` de
`test_auth_contract.py`:

- `GET` y `POST /api/projects`
- `POST /api/projects/{id}/run`
- `DELETE /api/projects/{id}`
- `POST /api/kill-session/{name}`

`PUT /api/projects/{id}` sigue siendo solo del panel. No se listan sesiones ni
espacios: el token no ve lo que no creó.

## Reglas

Fuera de la máquina el token no autentica ni se compara, y la petición sigue
como una sin token. Cuenta como la máquina lo que llega de loopback tras el
procesado de `uvicorn --proxy-headers` y sin ninguna cabecera de proxy
(`X-Forwarded-For`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Real-IP`,
`Forwarded`), por si un proxy local no reescribiera la IP.

Al crear:

- Un solo comando, que debe ser `<prefijo>`, seguido solo de
  `--permission-mode auto`, `-n <texto>` y un mensaje entre comillas de más de
  una palabra, cada uno como mucho una vez. El prefijo debe ir seguido de
  espacio o de fin. Una palabra suelta sería un subcomando de `claude`.
- Tras el prefijo se rechaza todo carácter de `_FORBIDDEN`, también entre
  comillas dobles; el porqué de cada uno está en `script_policy.py`. Se
  aceptan solo comillas dobles.
- `cwd` es obligatorio y debe quedar estrictamente dentro de la raíz, después
  de seguir enlaces y `..`. Fuera es 403 aunque no exista; dentro, si no existe
  es 400 (`err.script_cwd_missing`): es un error de quien llama, no un permiso.
  Se guarda ya resuelta.
- `links` y `space` del cuerpo se ignoran. El título se reduce con
  `_slug_session_name` a 64 caracteres, porque con él se apunta luego a la
  sesión desde una ruta.
- El proyecto queda con `script_owned: true` y va al espacio **Entrevistas**,
  que el servidor busca por título y crea si falta. El cuerpo no puede fijar
  esa marca.

Al usarlo:

- Listar devuelve solo los suyos. Lanzar o borrar otro da 403; uno que no existe,
  404.
- Matar exige que la sesión esté vinculada en `session_projects` a un proyecto
  suyo. **El orden importa:** borrar el proyecto se lleva el vínculo, así que
  primero se mata la sesión y después se borra el proyecto.
- Lanzar **vuelve a comprobar el comando y la carpeta**, porque Willy puede
  editar el proyecto en el panel, donde estas reglas no aplican. Si lo deja
  fuera de ellas, el token recibe 403 y Willy lo sigue pudiendo lanzar.
- Si Willy borró el espacio, al lanzar se vuelve a crear.

## Intentos y registro

Contador propio en `script_token.py`, en memoria y aparte del login: un token
malo no bloquea la contraseña. Tras 5 fallos en 60 s, 429 durante 5 minutos
aunque llegue el bueno; más fallos no alargan el bloqueo. Toda la red de
loopback cuenta como una sola clave, porque un proceso local podría cambiar de
`127.0.0.x` para no acumular fallos. Lo que viene de fuera no cuenta: ni se
compara.

Cada petición que trae la cabecera deja una línea `script-token`, usuario
`script`, en `data/audit.log`. `detail` lleva `result`, `status` y, si el token
valió, `token_id`, ocho caracteres de su huella que distinguen a los dos
activos. El token nunca se escribe.

| `result` | Significa |
|---|---|
| `accepted` | token válido; `status` dice cómo acabó |
| `invalid-token` | token equivocado |
| `rate-limited` | bloqueado por intentos |
| `not-local` | no viene de la máquina o trae cabeceras de proxy |
| `command-rejected` | comando fuera de las reglas; lleva `command` y `reason` |
| `cwd-rejected`, `cwd-missing` | carpeta fuera de la raíz, o que no existe |
| `foreign-project`, `foreign-session` | no es suyo |
| `not-evaluated` | la ruta no admite token, o la cortó algo antes (un JSON mal formado, el guard de Origin) |

## Consola real

Lo que `run-project` lanza es una consola interactiva en tmux, no `--bg`.
Comprobado el 2026-11-05 con `claude` 2.1.318, en un servidor de tmux aparte,
con una copia de la configuración (`CLAUDE_CONFIG_DIR`) sin hooks y sin enviar
ningún mensaje.

- **Una carpeta sin confianza se queda parada.** Sale «Accessing workspace… Is
  this a project you created or one you trust?», con el cursor en «No, exit».
- **Con `hasTrustDialogAccepted: true` en la carpeta no pregunta** y arranca.
- **Con esa marca en una carpeta madre tampoco pregunta**, aunque la hija no
  tenga entrada, y aunque la tenga en `false`.
- **`--permission-mode auto -n "x"` arranca en consola normal**: la línea de
  estado dice «auto mode on» y el recuadro de entrada lleva el nombre `x`.
- **El mensaje posicional:** deducido, no comprobado. `claude --help` dice
  `Usage: claude [options] [command] [prompt]` y que por defecto arranca una
  sesión interactiva, así que se entiende como el primer mensaje de esa sesión
  y se enviaría solo, sin pulsar Enter, en cuanto se pase el diálogo. No se ha
  lanzado con mensaje para no gastar.

**Receta.** En `~/.claude.json` de esa máquina,
`projects["/home/willy/proyectos/mvp-lab-proyectos"].hasTrustDialogAccepted` ya
estaba a `true` el 2026-11-05, lo que basta para todas las carpetas que cuelgan
de ahí: no hace falta tocar nada ni marcar cada entrevista. Si en otra máquina
no lo estuviera, se abre una vez `claude` a mano en esa carpeta madre y se
acepta. Lanzar en una carpeta sin ella deja la consola parada en el diálogo:
la llamada responde bien, pero el mensaje no sale y no consume nada.

## Trampas

- **Sigue ejecutando un programa.** Lo que limita es qué se lanza, no qué haga
  después `claude` en modo auto con el mensaje recibido. El mensaje lo pone el
  script: quien tenga el token elige ese texto.
- Quien tenga el token lo guarda él; el panel no puede devolverlo. Perderlo es
  generar otro.
- No sirve para el WebSocket del terminal ni para `send-command`.
- La carpeta debe existir antes de crear el proyecto.
- Un carácter rechazado también afecta a los mensajes legítimos: un `?` o un
  apóstrofo en el mensaje dan 403. El del receptor no lleva ninguno.
- Si `AUTH_ENABLED` es falso, `require_auth` deja pasar a cualquiera y estas
  rutas quedan abiertas sin token y sin estas reglas, como todo el panel.
