---
dominio: conversaciones-claude
actualizado: 2026-11-27
archivos:
  - backend/claude_sessions.py
  - backend/main.py
  - backend/config.py
  - backend/tests/test_claude_sessions.py
  - frontend/src/api.js
  - frontend/src/lib/claudeSessions.js
  - frontend/src/components/ClaudeSessions.jsx
  - frontend/src/components/ClaudeSnippet.jsx
  - frontend/src/components/Sidebar.jsx
  - frontend/src/App.jsx
  - frontend/e2e/sesiones-claude.spec.js
depende_de: [sesiones/_dominio, biblioteca/_dominio, acceso/_dominio, i18n/_dominio]
---

# Conversaciones de Claude

Buscar, leer, exportar y **retomar** las conversaciones pasadas de Claude Code
desde el panel. No confundir con `sesiones/`, que son las sesiones de **tmux**.
Los datos no son de muxspace: los sirve el API de sesiones de project-dashboard
(`127.0.0.1:9880`, solo lectura; su referencia es
`project-dashboard/docs/agent-context/sesiones/_dominio.md`, sección «API»).

## Reglas de seguridad (de Willy, no se negocian)

Las transcripciones pueden llevar contraseñas y claves.

- **Se consulta al momento y se tira.** Nada en `backend/data/`, ni caché, ni
  `localStorage`. Hay un test que lo vigila.
- **No se registra lo buscado**: ni la consulta, ni la respuesta, ni el texto de
  error del API. Los logs llevan solo operación y tipo de fallo; la auditoría
  anota `claude-sessions-search` **sin consulta** y `claude-resume` con el id.
  Por eso la búsqueda es `POST` con la consulta en el cuerpo: en un `GET`
  quedaría en el registro de accesos de uvicorn.
- **El navegador nunca habla con el 9880.** Todo cuelga de `/api/claude-sessions`
  con la autenticación normal (`_auth`; el token de scripts no entra),
  `no-store` y sin CORS abierto.
- Cada respuesta se **reconstruye campo a campo** (lista blanca): no sale `cwd`
  ni `size` ni la ruta del archivo en disco, y lo que el API añada no pasa.
- **El 503 («sesiones apagadas») se devuelve tal cual** —`detail.mensaje` y
  `detail.detail` con el comando— y la pantalla lo enseña literal. Nada intenta
  encenderlas.

## Cómo funciona

- `claude_sessions.py` es el cliente (`urllib`, sin proxies, plazo de 8 s y 15 s
  para buscar) y traduce los fallos a claves `err.claude_session*`: 404, 409
  (con las coincidencias), 400, 502 (caído o respuesta rara) y 504.
  `config.CLAUDE_SESSIONS_URL` (`MUXSPACE_CLAUDE_SESSIONS_URL`).
- **Filtro por proyecto.** El cliente manda `project_id` y el **servidor** saca la
  carpeta del proyecto. El API filtra por subcadena (`mvp-lab` casa con
  `mvp-lab-analisis`), así que `en_proyecto` repite el filtro: carpeta igual o
  hija por `/` (los worktrees cuentan). Los aciertos de búsqueda no traen `cwd`:
  se compara su `project`.
- **Fragmentos.** `trocear_fragmento` parte el `snippet` en trozos
  `{text, mark, secret}`: `mark` viene de « », `secret` de patrones (`sk-…`,
  `ghp_…`, `xox…`, `AKIA…`, JWT, `password=`/`contraseña:` + valor, cadenas de
  32+ caracteres mezclando letras y cifras). `ClaudeSnippet` los pinta siempre
  como texto, con `<mark>` y un «mostrar» por trozo secreto. Es ofuscación a la
  vista: el trozo viaja igualmente.
- **Retomar en el grid** (`POST …/{id}/open-in-grid`): exige el UUID entero, pide
  `/resume` al API y **rehace** el comando con la carpeta y el UUID validados
  (`claude --resume <uuid>` + `cd <carpeta citada>` de `create_session`), sin
  ejecutar texto del API. Nombre `Claude <8 hex>` con el sufijo ` (N)` de
  siempre. Con `project_id`, la sesión se asigna al espacio del proyecto y se
  vincula a él (`library_store.link_session`). Carpeta desaparecida: 409.
  `script_policy.py` no interviene: es solo del token de scripts.

## Interfaz

`ClaudeSessions.jsx` es una pantalla encima del panel (no una ruta: retomar tiene
que abrir la terminal en esta página). Se abre desde la lupa de la sección
Proyectos y del sidebar plegado (búsqueda global) y desde el bocadillo de cada
proyecto **con carpeta** (su pestaña «Sesiones», más una búsqueda acotada).
Lista por última actividad, búsqueda con filtros (quién habló, tipo, regex,
subagentes, orden), visor paginado y los botones Copiar comando, Exportar y
Retomar. Controles de 44 px y sin atajos obligatorios (tablet). Las fechas, con
`formatIsoDate` (ISO → `formatDate`).

## Trampas

- Los aciertos **no traen el índice del mensaje**: abrir uno lleva al principio.
- El icono de búsqueda **no va en la cabecera del sidebar**: ya va justa y un
  icono más se sale de la barra al 130 % (`e2e/cabecera.spec.js`).
- `ApiError.body` lleva el cuerpo codificado entero; el 503 y el 409 lo necesitan.
- Los tests y el E2E simulan el API (servidor local de prueba y `page.route`);
  `conftest.py` apunta `MUXSPACE_CLAUDE_SESSIONS_URL` al puerto 9.
- Tras tocar `backend/` hay que reiniciar el backend vivo (`proj-tmux`).
