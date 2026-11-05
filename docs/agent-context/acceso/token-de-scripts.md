---
dominio: acceso
accion: token-de-scripts
actualizado: 2026-11-05
archivos:
  - backend/script_token.py
  - backend/main.py
  - backend/tests/test_auth_contract.py
  - backend/tests/test_script_token.py
depende_de: [acceso/_dominio, biblioteca/ejecutar-proyecto, espacios/_dominio]
---

# Token de scripts

Un proceso de la misma máquina puede crear un proyecto de la biblioteca,
lanzarlo y borrarlo sin cookie y sin la contraseña del sistema. Lo necesita el
receptor de entrevistas, que corre programado.

## Cómo se usa

El secreto se crea al arrancar el panel en `backend/data/script_token`, con
permisos 0600, y va en la cabecera `X-Muxspace-Script-Token`:

    TOKEN=$(cat /home/willy/proyectos/muxspace/backend/data/script_token)
    curl -s -H "X-Muxspace-Script-Token: $TOKEN" http://127.0.0.1:8000/api/projects

## Reglas

- Abre solo estas rutas, enumeradas en `RUTAS_CON_TOKEN_DE_SCRIPTS` de
  `test_auth_contract.py`:
  - `GET` y `POST /api/projects`
  - `POST /api/projects/{id}/run`
  - `DELETE /api/projects/{id}`
  - `GET /api/sessions`
  - `POST /api/kill-session/{name}`
  - `GET` y `POST /api/spaces`
  - `DELETE /api/spaces/{id}`
- Sin secreto válido, esas rutas siguen exigiendo sesión del panel o Basic.
- Lo que hace con él un script consta en la auditoría con el usuario `script`.
- Un secreto equivocado da 401 y no cuenta como intento de contraseña.
- Para rotarlo: borrar el archivo y reiniciar `proj-tmux`. Hay que reiniciar
  porque el panel lo guarda en memoria.

## Trampas

- **Lanzar un proyecto ejecuta shell.** El secreto ahorra exponer la contraseña
  del sistema, no el poder de ejecutar órdenes como el usuario del panel.
- El archivo es legible por cualquier proceso de ese usuario, también por una
  consola de Claude que lea texto de un cliente.
- No sirve para el WebSocket del terminal: un script no puede escribir en una
  sesión con él, y tampoco `send-command`.
- La carpeta del proyecto debe existir antes de lanzarlo: si falla el `cd`, la
  llamada responde bien y el comando no arranca.
