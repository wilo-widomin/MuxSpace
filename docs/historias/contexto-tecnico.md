# Contexto técnico para las historias de usuario

Lo que hay que saber de MuxSpace **antes** de tocar una línea. Todas las US
de `docs/historias/` dan esto por leído.

Origen del backlog: [`../auditoria-2026-07.md`](../auditoria-2026-07.md) (el
análisis) y [`../plans/seguridad-y-qa.md`](../plans/seguridad-y-qa.md) (el
plan). Las fases 0 y 1 se hicieron a mano; de la 2 a la 6 salen de aquí.

---

## Qué es esto

Un panel web que gestiona sesiones de tmux. `send-command`,
`/api/commands/{id}/launch`, `/api/projects/{id}/run` y el WebSocket del PTY
**ejecutan comandos arbitrarios** como el usuario que corre el backend. No
hay sandbox ni lista blanca.

De ahí sale el criterio que ordena todo el backlog: **el control de acceso es
el 100% del perímetro**, y cualquier fallo que permita a un tercero provocar
una acción en el navegador del usuario equivale a ejecución remota de código.
Cuando dudes entre dos diseños, gana el que reduzca ese riesgo.

## Mapa del repo

```
backend/            FastAPI. Un módulo por responsabilidad, sin capas.
  main.py           Endpoints + middlewares (CSRF por Origin, baneo de IPs,
                    cabeceras de seguridad). El archivo grande del backend.
  auth.py           Sesiones en memoria, rate limit persistido, baneo por CIDR.
  config.py         TODA la configuración, leída del entorno EN IMPORT TIME.
  datafiles.py      Escritura de backend/data/ a 0700/0600 (tmp + replace).
  dir_suggestions.py  Resolución de rutas dentro de las raíces permitidas.
  library_store.py  Comandos y proyectos del usuario (data/library.json).
  space_store.py    Espacios y asignaciones (data/spaces.json).
  upload_store.py   Historial de subidas (data/upload_history.json).
  tmux_service.py   Todo lo que habla con tmux, SIEMPRE por argv.
  pty_bridge.py     WebSocket <-> PTY (`tmux attach`).
  errors.py         AppError + http_error: los errores viajan como clave i18n.
frontend/           React + Vite + Tailwind. Sin router.
  src/components/Sidebar.jsx   2.572 líneas con 6+ componentes dentro.
  src/i18n/locales/*.json      6 idiomas, claves planas.
scripts/check-i18n.js          Único chequeo automático que existe hoy.
```

## Reglas que no se negocian

### 1. `bun`, nunca `npm` ni `npx`

En todo: instalar, ejecutar scripts, añadir dependencias. El proyecto migró
de npm a bun (commit `e1befea`) y el lockfile es `frontend/bun.lock`.

```bash
cd frontend && bun install          # NO npm install
cd frontend && bun run build        # NO npm run build
cd frontend && bunx <herramienta>   # NO npx
```

### 2. `backend/data/` son datos REALES del usuario

Ahí viven su biblioteca de comandos, el historial de subidas, las capturas
pegadas y el registro de intentos de login. **Ninguna prueba puede escribir
ahí.** El `conftest.py` aísla los stores en `tmp_path` y su primer test
verifica que ningún `_STORE_PATH` cae bajo `backend/data/`. Si tocas ese
aislamiento, ese test es lo primero que tiene que seguir pasando.

### 3. `config.py` lee el entorno en import time

`load_dotenv(...)` y todos los `os.getenv(...)` corren al importar el módulo.
Consecuencia para los tests: **las variables se fijan ANTES de importar nada
del backend**, y recargar configuración implica `importlib.reload`. Un
`monkeypatch.setenv` después del import no cambia nada.

Además, `backend/.env` es el despliegue real del usuario: los tests no lo
leen ni lo modifican (fija `MUXSPACE_*` en el entorno, que gana sobre el
`.env` porque `load_dotenv` no hace override).

### 4. Un solo worker de uvicorn

Los locks de los stores son `threading.Lock`, de proceso. Con `--workers 4`
se corrompe la biblioteca por read-modify-write concurrente. Es un requisito
implícito del despliegue; no lo rompas.

### 5. Los errores son claves i18n, no frases

`http_error(400, "err.upload_name_invalid")` y la traducción vive en los
**6** locales (`de, en, es, fr, it, pt`). Una clave nueva sin sus 6
traducciones la caza `bun run check-i18n`.

### 6. tmux siempre por `argv`

Nunca por shell. La inyección de comandos vía nombre de sesión no existe como
categoría en este proyecto y así se queda. `_quote_path` expande `~` **antes**
de `shlex.quote` (`tmux_service.py`), y el comentario explica por qué: es
justo lo que se pierde en el siguiente refactor.

### 7. Commits y ramas

Toda US va en su **rama + worktree + PR**. Nada directo en `main`. Cada
commit termina con:

```
Co-authored-by: wilo-widomin <widomin@gmail.com>
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: <url de la sesión>
```

### 8. No reinicies el backend de producción

Hay un uvicorn en `127.0.0.1:8000` sirviendo el panel del usuario, con
terminales abiertas en su navegador. Las sesiones de tmux sobreviven a un
reinicio; las conexiones WebSocket no. **Pregunta antes.** Para probar,
levanta una copia aislada en otro puerto con su propio `data/`.

---

## Comandos de verificación

La lista crece con el backlog: cada fase trae sus propios comandos. Estado y
quién lo trae:

| Comando | Estado | Lo crea |
|---|---|---|
| `cd frontend && bun run build` | ✅ existe | — |
| `cd frontend && bun run check-i18n` | ✅ existe (hoy solo avisa) | pasa a error en US-009 |
| `backend/venv/bin/python -m pytest -q` | ✅ existe | US-001 |
| `backend/venv/bin/python -m ruff check backend/` | ✅ existe | US-008 |
| `cd frontend && bun run lint` | ✅ existe | US-008 |
| `cd frontend && bun run format:check` | ⚠️ existe pero **no está verde** | US-008 |
| `cd frontend && bun run test` (vitest) | ❌ | US-017 |

`format:check` es el único que no entra en el gate, y a propósito: el código no
está formateado con prettier y ponerlo lo estaría son ~1.100 líneas, **950 de
ellas en `Sidebar.jsx`**. Tiene más sentido después de trocearlo (fase 4) que
antes. La configuración (`frontend/.prettierrc`) ya está elegida para acercarse
al estilo actual —se probaron cuatro anchuras y las dos políticas de coma final,
y 88 + `trailingComma: all` es la que menos diff produce—, así que el día que se
formatee el cambio será mecánico.

Conforme una US cree uno, **añádelo a `verify` en
`.claude/us-pipeline.config.json` en el mismo PR**. Ese es el mecanismo por el
que el DoD se va apretando solo.

### `kill-server` de tmux es asíncrono (y hacía intermitente la suite)

`kill-server` vuelve cuando ha **mandado** la orden, no cuando el servidor ha
muerto. Un `new-session` que caiga en esa ventana falla con **"server exited
unexpectedly"**, que `create_session` no reconoce —no dice "duplicate
session"— y eleva como `TmuxError`.

El teardown de `tmux_aislado` hacía exactamente eso antes de cada test
siguiente, así que la suite entera fallaba **una pasada completa de cada ~20**,
en un test distinto cada vez. Medido en tmux 3.4, encadenando las dos
operaciones sin pausa:

| Encadenando | Fallos |
|---|---|
| `kill-server` + `new-session` | 30 / 500 (6 %) |
| `ServidorDePruebas.apagar()` + `new-session` | 0 / 1200 |

En la suite la tasa era mucho más baja porque entre test y test pytest gasta
decenas de milisegundos (deshacer `monkeypatch`, fixtures) que casi siempre
bastan. **"Casi siempre" es lo que no sirve con un CI que bloquea merges**: un
rojo intermitente enseña a reintentar hasta que pase, y ahí el CI deja de
valer para nada.

Por eso en `test_tmux_service.py` nunca se llama a `kill-server` directamente:
se usa `ServidorDePruebas.apagar()`, que mata y **espera** a que
`list-sessions` conteste "no server running". Si escribes un test que necesite
apagar el servidor de pruebas, usa ese helper.

No afecta a producción: `tmux_service` no llama a `kill-server` en ningún
sitio, ni debe (mataría las sesiones del usuario).

### La cobertura de los endpoints `async` no se mide (US-004)

`coverage.py` deja de trazar el frame de una corrutina en cuanto el bucle de
eventos la suspende. Consecuencia medida: `upload_file` figura cubierto **hasta
la línea del `await _read_capped(...)` y ni una más**, mientras que las
funciones síncronas que llama justo después (`_unique_target`,
`upload_store.add`) salen al 100 %. Por eso `main.py` no pasa del ~53 % aunque
sus endpoints estén ejercitados a fondo (con todas las fases cerradas llegó al
68 %, que sigue siendo el módulo más castigado por este efecto).

Probado y descartado: `concurrency = thread` en la config de coverage no lo
cambia.

Dos consecuencias prácticas:

- Los objetivos «≥85 % en los endpoints de subida» de las US de la fase 2 **no
  son medibles** tal y como están escritos. La garantía real de esas US son las
  mutaciones documentadas en sus PR, no el porcentaje.
- **Afecta a dónde puede estar `--cov-fail-under`.** Cuando se escribió esto,
  con la fase 2 a medias, el total global era del 63 % y el gate se fijó en 60.
  Con todas las fases cerradas el total es del **84,7 %** y el gate está en
  **80** (PR #47): el techo artificial sigue ahí —`main.py` en 68 % y
  `pty_bridge.py` en 72 % aun con tests de sobra—, y por eso el listón no sube
  hasta el 85, donde ya salta.

### En un worktree del pipeline

`backend/venv/` y `frontend/node_modules/` están en `.gitignore`, así que un
worktree recién creado **no los tiene** y los comandos de arriba fallan con
`No such file or directory` o `vite: command not found`. Se resuelve
enlazándolos al repo principal, que es de donde salen igualmente:

```bash
ln -sfn /home/willy/proyectos/muxspace/backend/venv        <worktree>/backend/venv
ln -sfn /home/willy/proyectos/muxspace/frontend/node_modules <worktree>/frontend/node_modules
```

Se enlazan y no se reinstalan porque un worktree es efímero: duplicar un venv
y un `node_modules` por historia son cientos de megas para nada. Ambos
patrones están en `.gitignore` en su forma sin barra para que el symlink no
ensucie `git status`.

## Roster del ciclo

`~/.claude/agents/` está vacío, así que los roles del CLAUDE.md global
(`senior-backend-python`, etc.) no existen como subagentes. El pipeline usa el
roster genérico:

| Fase del ciclo | Agente |
|---|---|
| Arquitecto | `Plan` |
| Desarrollador | `general-purpose` |
| Tester | `general-purpose` |
| Auditor | `general-purpose` (pasada de code-review sobre el diff) |

---

## Definition of Done

Un cambio está terminado cuando:

1. **Tiene un test que falla sin el cambio.** No "un test que pasa": uno que
   demuestre el problema. Para las US de la fase 2, el test *es* el entregable.
2. Los comandos de `verify` que ya existan pasan (ver la tabla de arriba).
   Los que aún no existen no bloquean.
3. `bun run check-i18n` sin claves faltantes.
4. `bun run build` verde.
5. README/docs actualizados si cambia comportamiento observable.
6. Si toca **autenticación, rutas o ficheros**, lleva un **test de seguridad
   específico** — no vale la cobertura genérica.
7. Ninguna prueba escribe en `backend/data/`.
8. Sin secretos ni rutas absolutas del despliegue en el código.
9. Los comentarios explican **por qué**, no qué. El código de este repo tiene
   ese estilo; mantenlo.

A partir de la fase 3 el CI hace de guardián de 2, 3 y 4.

## Ya resuelto (no lo rehagas)

Las fases 0 y 1 se hicieron a mano antes de arrancar el pipeline (PR #1):

- Cabeceras de seguridad con `frame-ancestors 'none'` (S1).
- `O_NOFOLLOW | O_EXCL` en `/api/upload` (S3).
- `_read_capped`: tope de tamaño antes de bufferizar (S4).
- `COOKIE_SECURE` por defecto `true` (S6).
- Parser único para `CORS_ORIGINS` (S7).
- `backend/data/` a 0700/0600 con `datafiles` (S9).
- **`upload_store._save` atómico**: cayó de propina al centralizar el
  tmp + replace en `datafiles.write_private`. El punto correspondiente de la
  Fase 5 del plan ya no tiene trabajo pendiente.
