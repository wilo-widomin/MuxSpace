# MuxSpace — Dashboard Dinámico de Sesiones Tmux

Interfaz web para gestionar, visualizar y organizar múltiples sesiones de
tmux de forma simultánea desde el navegador. No es un emulador de terminal:
es un panel de control sobre el servidor tmux del usuario que ejecuta el
backend.

Qué hace:

- **Sesiones de tmux**: listar, crear, abrir/cerrar su vista en un *grid*
  responsivo equitativo, renombrar, separar (*detach*), enviar comandos y
  destruir.
- **Terminales xterm.js** propias conectadas por WebSocket a un puente PTY
  del backend (`tmux attach`), con copia al portapapeles controlada por el
  cliente (incluido OSC 52).
- **Biblioteca reutilizable** de **comandos** (una línea de shell) y
  **proyectos** (directorio + secuencia de comandos) lanzables en sesiones
  nuevas con un clic; persiste en disco entre reinicios.
- **Capturas y archivos**: pegar una imagen del portapapeles o subir un
  archivo a una carpeta del host, y copiar su ruta lista para pegársela a
  una herramienta de la terminal.
- **Autenticación** HTTP Basic opcional y **autocompletado** de directorios
  acotado a las raíces configuradas.

Un único proceso sirve la API, el WebSocket de las terminales y el frontend
compilado, todo en un **solo puerto local**. No depende de systemd, Docker ni
de ningún proxy (opcionales para exponerlo al exterior).

Especificación completa en [`docs/muxspace.md`](docs/muxspace.md).

> **¿Empezar desde cero?** Sigue la guía de
> [`docs/onboarding.md`](docs/onboarding.md): clonar, configurar, arrancar
> y tener tu primera sesión en el grid en 5 minutos (con troubleshooting).

## Arquitectura

| Capa | Tecnología | Responsabilidad |
|------|-----------|-----------------|
| Control (Backend) | Python · FastAPI | API REST + puente PTY (WebSocket), encapsula la CLI de `tmux`, registro de vistas y biblioteca persistente |
| Presentación (Frontend) | React · Tailwind · Vite · xterm.js | Sidebar (sesiones + biblioteca) y grid de terminales |
| Transporte | HTTP + WebSocket → PTY | API REST y bytes bidireccionales de la terminal por el mismo origen |
| Almacenamiento | JSON plano (`backend/data/`) | Biblioteca de comandos/proyectos (fuera de git) |

```
Navegador ──HTTP──────> FastAPI (API + frontend estático)
 (xterm.js) ──WebSocket─> /api/terminal/{sesión} ──PTY──> tmux attach -t <sesión>
                                    │
                                    └── subprocess ──> tmux (list/new/kill/...)
```

## Requisitos

- **Python 3.10+**
- **Bun** (solo para compilar el frontend si no existe `frontend/dist/`).
  Es el único gestor de paquetes del proyecto: `bun install` / `bun run`,
  nunca `npm`/`npx`. El lockfile es `frontend/bun.lock`.
- **tmux** (instálalo con el gestor de paquetes de tu distro: `apt install tmux`, `dnf install tmux`, `pacman -S tmux`, …)

## Puesta en marcha rápida

```bash
# Producción: un solo puerto (backend + frontend compilado)
./start.sh            # → http://127.0.0.1:8000

# Desarrollo: backend + frontend (Vite HMR) por separado
./scripts/dev.sh
```

- Producción (un solo puerto): <http://127.0.0.1:8000> (API + docs en `/docs`)
- Desarrollo — Frontend: <http://localhost:5173>, Backend: <http://localhost:8000/docs>

> **Antes del primer arranque**, pon una contraseña en `backend/.env`
> (`MUXSPACE_PASSWORD`): el backend **se niega a arrancar** si la dejas
> vacía o en `admin`. Quien entra al panel puede ejecutar comandos como el
> usuario que corre el backend, así que no hay credenciales por defecto
> que funcionen. Genera una con `openssl rand -base64 24`.

> Crea alguna sesión de tmux para probar: `tmux new -d -s trabajo`.

## Configuración

El backend se configura por variables de entorno. Copia el ejemplo y
edítalo:

```bash
cp backend/.env.example backend/.env
```

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `MUXSPACE_AUTH_ENABLED` | `true` | Activa la autenticación HTTP Basic |
| `MUXSPACE_USERNAME` / `MUXSPACE_PASSWORD` | `admin` / *(sin valor)* | Credenciales del dashboard. La contraseña es obligatoria: el backend no arranca si está vacía o es `admin` |
| `MUXSPACE_PORT` | `8000` | Puerto del backend |
| `MUXSPACE_HOST` | `127.0.0.1` | Interfaz de enlace (`0.0.0.0` si lo pones tras un reverse proxy) |
| `MUXSPACE_TRUSTED_PROXIES` | `127.0.0.1` | IPs de proxies de confianza para `X-Forwarded-For`. Si el reverse proxy está en **otra máquina**, añade su IP o el rate limit y los baneos verán la IP del proxy en vez de la del cliente |
| `MUXSPACE_TMUX_BINARY` | `tmux` | Ruta al binario de tmux (si no está en el PATH) |
| `MUXSPACE_CORS_ORIGINS` | `localhost:5173` | Orígenes CORS permitidos (casi irrelevante en producción: mismo origen) |
| `MUXSPACE_DIR_SUGGESTION_ROOTS` | `["~"]` | Raíces para el autocompletado de directorios (`~` = home del usuario que corre el backend) |

## API

Todos los endpoints (salvo `/api/health`) requieren autenticación Basic si
está activada. El WebSocket valida el mismo token vía `?token=` (base64 de
`usuario:contraseña`).

### Sesiones de tmux

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/sessions` | Lista las sesiones de tmux y su estado de apertura en el grid |
| `POST` | `/api/create-session/{name}` | Crea una sesión nueva (`new-session -d`); body opcional `{command, cwd}` |
| `POST` | `/api/start-session/{name}` | Marca la sesión como abierta en el grid |
| `POST` | `/api/stop-session/{name}` | Oculta la sesión del grid (no la destruye) |
| `POST` | `/api/kill-session/{name}` | Destruye la sesión de tmux y la retira del grid |
| `POST` | `/api/detach-session/{name}` | Separa (*detach*) a los clientes sin destruir la sesión |
| `POST` | `/api/rename-session/{name}` | Renombra la sesión (`body: {new_name}`) |
| `POST` | `/api/send-command/{name}` | Envía un comando a la sesión y pulsa Enter (`body: {command}`) |
| `WS`  | `/api/terminal/{name}` | Puente PTY (`tmux attach`) para la terminal xterm.js |
| `GET` | `/api/dir-suggestions?q=` | Subdirectorios bajo las raíces configuradas (autocompletado) |
| `POST` | `/api/logout-all` | Revoca **todas** las sesiones, incluida la de quien llama ([para qué](#post-apilogout-all--revocar-todas-las-sesiones)) |
| `GET` | `/api/health` | Healthcheck |

### Biblioteca de comandos

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/commands` | Lista los comandos guardados |
| `POST` | `/api/commands` | Crea un comando (`body: {label?, command}`) |
| `PUT` | `/api/commands/{id}` | Actualiza un comando |
| `DELETE` | `/api/commands/{id}` | Elimina un comando |
| `POST` | `/api/commands/{id}/launch` | Lanza el comando en una sesión nueva (nombre = label, sufijo ` (N)` si existe) |

### Biblioteca de proyectos

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/api/projects` | Lista los proyectos guardados |
| `POST` | `/api/projects` | Crea un proyecto (`body: {title, cwd?, commands: []}`) |
| `PUT` | `/api/projects/{id}` | Actualiza un proyecto |
| `DELETE` | `/api/projects/{id}` | Elimina un proyecto |
| `POST` | `/api/projects/{id}/run` | Ejecuta el proyecto: crea una sesión, `cd <cwd>` y lanza los comandos en orden |

### Capturas y archivos

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/paste-image` | Guarda la imagen pegada (bytes crudos) en `backend/data/pastes/` y devuelve su ruta |
| `GET` | `/api/pastes` | Lista las capturas guardadas (la más nueva primero) |
| `GET` | `/api/pastes/{filename}` | Devuelve la imagen (miniatura/visor del panel) |
| `DELETE` | `/api/pastes/{filename}` | Borra una captura del disco |
| `GET` | `/api/dir-browse?path=` | Subcarpetas de `path` para el navegador de carpetas (vacío = primera raíz) |
| `POST` | `/api/dir-create` | Crea una subcarpeta (`body: {parent, name}`), siempre bajo una raíz |
| `POST` | `/api/upload?dir=&name=` | Sube un archivo (bytes crudos) a la carpeta elegida; no pisa existentes (` (2)`, ` (3)`…) |
| `GET` | `/api/uploads` | Historial de las últimas subidas |
| `DELETE` | `/api/uploads?path=` | Quita una entrada del historial (**no** borra el archivo del disco) |

## Flujo de trabajo

1. El frontend pide la lista de sesiones (`GET /api/sessions`, refresca cada
   8 s) y la biblioteca (`/api/commands`, `/api/projects`).
2. Al clicar una sesión: `POST /api/start-session/{name}` la marca como abierta.
3. El frontend añade un tile con una terminal xterm.js que abre un WebSocket a
   `/api/terminal/{name}`.
4. El backend abre un PTY y ejecuta `tmux attach -t <nombre>`, transmitiendo
   bytes en ambos sentidos. El cliente envía el tamaño del tile para que tmux
   se ajuste al espacio disponible.
5. Al clicar la **X**: se retira del grid y `POST /api/stop-session/{name}`
   deja de mostrarla (la sesión de tmux sigue viva).

El grid recalcula filas y columnas para repartir el espacio de forma
equitativa (1 sesión = 100%, 4 sesiones = 2×2). El estado de tmux persiste
aunque se recargue la web: solo se cierra la "ventana" de visualización.

### Sidebar

- **Sesiones** (arriba, colapsable): catálogo y acciones por sesión.
- Debajo, cuatro persianas en **acordeón** (solo una abierta a la vez; la
  que quede abierta se recuerda entre recargas y se puede redimensionar
  arrastrando su divisor):
  - **Proyectos** y **Comandos**: la biblioteca, con el `+` de alta junto
    al título y los formularios de alta/edición en un **modal** central.
  - **Pegar imagen para Claude**: pega una captura del portapapeles, se
    sube a `backend/data/pastes/` y copia su ruta.
  - **Subir archivo**: elige carpeta destino con un navegador tipo
    explorador, sube (o arrastra) el archivo y copia su ruta.
- Las rutas copiadas van **entrecomilladas** si llevan espacios o
  caracteres que interpretaría el shell, para poder pegarlas de una pieza.
- La anchura del sidebar es arrastrable.

## CI: qué bloquea un merge

`.github/workflows/ci.yml` corre en cada `pull_request` y en cada `push` a
`main`, con dos jobs en paralelo. **Si alguno se pone en rojo, no se mergea.**

| Job | Pasos |
|---|---|
| `backend` | instalar tmux → `pip install -r backend/requirements-dev.txt` → `ruff check backend/` → `pytest --cov=backend --cov-fail-under=60` |
| `frontend` | `bun install --frozen-lockfile` → `bun run lint` → `bun run test` (vitest) → `bun run build` → `bun run check-i18n` |

Todo eso se reproduce en local con los comandos de la sección siguiente: si el
CI comprueba algo que no puedes ejecutar en tu máquina, deja de ser útil y pasa
a ser un obstáculo.

Tres detalles que no son evidentes:

- **El job de backend instala `tmux`**, y no es un adorno:
  `test_tmux_service.py` habla con un tmux real por un socket propio (`-L`).
  Sin el paquete, sus 55 tests se **saltan en silencio** —el `skipif` los marca
  como omitidos, no como fallo— y nadie se entera de que la mitad con más
  riesgo del módulo no se está probando.
- **`check-i18n` corre como error, no como aviso.** Una clave que falte degrada
  la interfaz en silencio en los otros cinco idiomas, que es justo lo que nadie
  va a ver probando a mano.
- **La cobertura se mide sin los tests** (`[tool.coverage.run] omit` en
  `pyproject.toml`). Con ellos sale 90% y no significa nada: un test se ejecuta
  entero por definición. Sin ellos, hoy es el **76%**, y el gate está en 60.
  El margen es deliberado — los endpoints `async` no se miden bien (coverage
  deja de trazar la corrutina en cuanto se suspende), así que subir el listón
  chocaría con ese techo artificial y no con la calidad de las pruebas.

### Protección de rama (se configura a mano, una vez)

El workflow **por sí solo no impide mergear**: hace falta marcar los checks
como obligatorios en GitHub. En *Settings → Branches → Add branch protection
rule* para `main`, activar *Require status checks to pass before merging* y
seleccionar `backend` y `frontend`.

## Calidad: tests, linters y formato

```bash
# Instalar las dependencias de desarrollo (pytest, ruff…)
backend/venv/bin/python -m pip install -r backend/requirements-dev.txt

# Backend
backend/venv/bin/python -m pytest -q            # tests
backend/venv/bin/python -m ruff check backend/  # linter
backend/venv/bin/python -m ruff check backend/ --fix   # arreglar lo mecánico

# Frontend (siempre bun, nunca npm ni npx)
cd frontend
bun run lint          # eslint
bun run test          # vitest (una vez); `bun run test:watch` para desarrollar
bun run build         # que compile
bun run check-i18n    # que no falten claves en los 6 idiomas
```

**`ruff`** lleva las reglas `E,F,I,B` más **`S`** (`flake8-bandit`), que está ahí
por lo que este panel hace: ejecuta comandos como el usuario que lo corre. Donde
`S` se silencia es siempre con un `# noqa: SXXX` en la línea concreta y con el
motivo escrito al lado — nunca desactivando la regla en la configuración. El
caso más repetido es `S603` (`subprocess` sin `shell=True`), que aquí es
justamente la forma **correcta** de invocar tmux.

**`eslint`** lleva a propósito muy pocas reglas: las que valen son
`react-hooks/rules-of-hooks` y `exhaustive-deps`, que detectan bugs de verdad.
Un preajuste pesado traería cientos de reglas de estilo que este repo no sigue.

**`prettier`** está configurado (`frontend/.prettierrc`) para acercarse al estilo
que ya tiene el repo, pero **el código todavía no está formateado con él**:

```bash
cd frontend
bun run format:check   # hoy NO está en verde: ~1.100 líneas difieren
bun run format         # reformatea (cambio grande, hacerlo en su propio PR)
```

Formatear entero es un cambio mecánico de ~1.100 líneas, y 950 caen en
`Sidebar.jsx`. Tiene más sentido después de trocearlo (fase 4) que antes, así
que `format:check` **no** forma parte del gate de CI.

## Estructura del proyecto

```
muxspace/
├── backend/
│   ├── main.py            # App FastAPI y endpoints (sesiones + biblioteca)
│   ├── config.py          # Configuración por entorno (carga backend/.env)
│   ├── tmux_service.py    # Encapsula la CLI de tmux (list/new/kill/...)
│   ├── pty_bridge.py      # Puente WebSocket ↔ PTY (tmux attach)
│   ├── auth.py            # Autenticación (sesión por cookie + guard del WebSocket)
│   ├── space_store.py     # Persistencia de espacios y asignación de sesiones (JSON)
│   ├── errors.py          # AppError: códigos traducibles + detalle técnico
│   ├── library_store.py   # Persistencia de la biblioteca de comandos y proyectos (JSON)
│   ├── dir_suggestions.py # Autocompletado y navegación de directorios (raíces)
│   ├── upload_store.py    # Historial de los últimos archivos subidos (JSON)
│   ├── data/              # JSON de la biblioteca (se crea sola; fuera de git)
│   ├── requirements.txt
│   ├── .env.example       # Plantilla de configuración genérica
│   └── .env               # Configuración del despliegue (fuera de git)
├── frontend/
│   ├── src/
│   │   ├── App.jsx        # Estado global, orquestación y polling
│   │   ├── api.js         # Cliente HTTP/WS + auth
│   │   └── components/    # Sidebar, SessionGrid, TerminalTile,
│   │                     #   XtermTerminal, LoginScreen
│   └── package.json
├── start.sh               # Arranque de producción (un puerto)
├── scripts/
│   └── dev.sh             # Arranca backend + frontend (Vite HMR)
└── docs/
    ├── onboarding.md          # Guía de puesta en marcha paso a paso
    ├── muxspace.md            # Especificación
    ├── mtls.md                # Acceso por certificado de cliente
    ├── auditoria-2026-07.md   # Auditoría de seguridad y calidad
    └── plans/
        ├── seguridad-y-qa.md  # Plan de corrección de la auditoría
        └── i18n.md            # Plan de internacionalización
```

## Seguridad

- **Autenticación**: login con sesión de servidor (cookie `HttpOnly` +
  `SameSite=Lax`), validando en modo `env` (usuario/contraseña fijos) o
  `pam` (credenciales de Linux). HTTP Basic se mantiene como alternativa
  para clientes CLI (`curl -u`). Para producción, sitúa el panel tras un
  *reverse proxy* (Caddy/Nginx) con TLS.
- **Caducidad de sesión por inactividad**: 24 h sin usar el panel y hay que
  volver a entrar (`MUXSPACE_SESSION_IDLE_HOURS`). Cada petición renueva la
  ventana, así que trabajar no interrumpe. Por encima hay un **techo
  absoluto** que no se renueva nunca (`MUXSPACE_SESSION_TTL_HOURS`, 7 días):
  sin él, una cookie robada duraría para siempre con solo usarla una vez al
  día. Ver abajo.
- **Revocación global**: `POST /api/logout-all` (ver abajo).
- **Anti fuerza bruta**: máximo 5 fallos de login por IP y minuto (aplica
  también a la vía HTTP Basic). Los contadores y el histórico de IPs
  atacantes persisten en `backend/data/login_failures.json`, así que un
  reinicio del backend no los resetea.
- **Lista negra de IPs**: `backend/data/banned_ips.json` — array JSON de
  IPs o rangos CIDR (IPv4/IPv6) con el acceso prohibido (403 en HTTP y
  rechazo del WebSocket). Se recarga en caliente al editar el archivo,
  sin reiniciar. Plantilla en `backend/data/banned_ips.json.example`.
- **Acceso por certificado (mTLS)**: opcionalmente, el proxy con TLS puede
  exigir certificado de cliente y eliminar la contraseña de la ecuación.
  Guía completa y script de emisión en `docs/mtls.md` +
  `scripts/mtls-client-cert.sh`.
- **Sin puertos extra ni iframes**: las terminales viajan por el mismo
  origen que la API (`/api/terminal/...`); no se abren puertos
  adicionales por sesión.
- **Bind local por defecto** (`MUXSPACE_HOST=127.0.0.1`). Usa `0.0.0.0`
  solo si vas a poner un proxy delante.
- **Autocompletado acotado**: las sugerencias de directorios solo listan
  bajo las raíces configuradas (`MUXSPACE_DIR_SUGGESTION_ROOTS`, `~` =
  home del usuario que corre el backend).
- **Portapapeles**: xterm.js propio + OSC 52. El backend activa en cada
  sesión, *best-effort*, `allow-passthrough on` y `set-clipboard on`
  (ignora errores en tmux antiguos).
- **Registro de auditoría**: `backend/data/audit.log` (ver abajo).

### Sesiones: cuánto duran y cómo revocarlas

Una sesión vive mientras se cumplan **las dos** condiciones. Muere con la
primera que falle:

| | Variable | Default | ¿Se renueva? |
|---|---|---|---|
| Inactividad | `MUXSPACE_SESSION_IDLE_HOURS` | 24 h | **Sí**, en cada petición autenticada |
| Techo absoluto | `MUXSPACE_SESSION_TTL_HOURS` | 168 h (7 días) | **No**, se fija al hacer login |

En la práctica: si usas el panel a diario no vuelves a ver el login hasta que
pasen 7 días desde que entraste; si lo dejas quieto un día, caduca.

El techo absoluto es la parte que parece redundante y no lo es. Una ventana
deslizante **sin** techo es peor que el TTL fijo que sustituye: a quien te
robe la cookie le basta con tocar el panel una vez al día para tenerla viva
indefinidamente. El techo pone un final que ninguna actividad puede mover.

El WebSocket del terminal también renueva la ventana, así que tener una
terminal abierta cuenta como usar el panel.

> **Cambio de comportamiento respecto de versiones anteriores**: antes la
> sesión duraba 168 h fijas desde el login. Si tu despliegue usa PAM con
> `SESSION_TTL_HOURS=168`, ahora vas a hacer login más a menudo: cuando pases
> más de 24 h sin abrir el panel. Sube `MUXSPACE_SESSION_IDLE_HOURS` si te
> molesta, teniendo en cuenta que quien tenga la sesión abierta tiene una
> shell.

#### `POST /api/logout-all` — revocar todas las sesiones

Invalida **todas** las sesiones abiertas, incluida la de quien lo llama.
Devuelve `{"revoked": N}` con cuántas había.

```bash
# Con la cookie de sesión (exige estar autenticado)
curl -X POST -b muxspace_session=<token> https://tu-panel/api/logout-all

# O con HTTP Basic, que sigue valiendo para clientes CLI
curl -X POST -u usuario:contraseña https://tu-panel/api/logout-all
```

**Cuándo usarlo**: cuando sospeches que una cookie de sesión anda por donde
no debe — un portátil perdido, una sesión abierta en un equipo ajeno, un
navegador compartido. Hasta ahora la única forma de revocarlas era reiniciar
el backend, que además se lleva por delante las terminales abiertas.

Se revoca también la sesión de quien llama, y es a propósito: una revocación
con excepciones no revoca nada. Si el atacante es quien la llama, dejarle su
sesión viva convertiría el endpoint en un arma en su favor.

**No hay botón en el panel**, y es una decisión: es una medida de emergencia
que se usa cuando sospechas de una cookie robada, y en ese momento lo que
quieres es una orden que funcione desde cualquier terminal, no un clic en la
interfaz que tienes en duda. Para cerrar tu propia sesión, el panel ya tiene
"Cerrar sesión" en el pie de la barra lateral.

### Registro de auditoría

Este panel da shell, así que deja traza de **qué** se ejecutó, **en qué
sesión**, **cuándo** y **desde qué IP**. Vive en `backend/data/audit.log`,
con permisos `0600` (registra los comandos del usuario: no puede quedar
legible para el resto del sistema).

El formato es **JSONL**: un objeto JSON por línea, sin envoltorio. Se elige
por lo aburrido que es —se lee con `tail`, se filtra con `grep`, se procesa
con `jq`, y una línea corrupta no arrastra a las demás—; un array JSON
habría que reescribirlo entero en cada anotación.

Campos de cada línea:

| Campo | Contenido |
|---|---|
| `ts` | Marca de tiempo ISO 8601 **con zona** (UTC). Nunca epoch pelado |
| `ip` | IP del cliente (respetando `X-Forwarded-For` de proxies de confianza) |
| `user` | Usuario autenticado que lanzó la acción |
| `action` | El verbo: `login`, `login-failed`, `create-session`, `kill-session`, `rename-session`, `send-command`, `launch`, `run-project`, `upload` |
| `target` | El objeto sobre el que se actúa (normalmente el nombre de la sesión, o la ruta en `upload`) |
| `detail` | Lo necesario para reconstruir qué pasó: el comando enviado, la ruta subida, el nombre nuevo al renombrar… |

```bash
# Todo lo que se ha ejecutado en las sesiones, con su hora e IP
jq -r 'select(.action=="send-command") | "\(.ts) \(.ip) \(.target) → \(.detail.command)"' \
   backend/data/audit.log
```

**Nunca** se registran credenciales: del login solo queda si hubo éxito,
desde dónde y con qué usuario; ni la contraseña ni el token de sesión
llegan al fichero (un log de auditoría que lleve el token es una llave, no
una traza).

Dos decisiones conscientes sobre la rotación, que conviene conocer antes de
montar nada encima:

- **Solo rota por tamaño, nunca por tiempo.** Al superar los 5 MB el
  fichero pasa a `audit.log.1` y se abre uno nuevo. No hay rotación diaria
  ni semanal: si necesitas cortes por fecha, filtra por `ts` con `jq`.
- **Se conserva una sola rotación.** Al rotar de nuevo, el `audit.log.1`
  anterior se pierde. Sin ese techo el log crecería sin límite en el mismo
  disco que guarda las sesiones del usuario. Quien necesite histórico
  completo debe llevarse los ficheros fuera (un `rsync` periódico basta).

Escribir en el log **nunca** tumba una petición: si el disco se llena o los
permisos cambian, el error se traga y la acción sigue adelante. Un panel
que deja de funcionar porque no puede escribir su propio log de auditoría
es peor que un panel sin log.

> **Auditoría (2026-07-27)**: hay hallazgos abiertos, dos de severidad alta
> (falta de cabeceras de seguridad y API accesible sin autenticación desde
> localhost). Informe completo en
> [`docs/auditoria-2026-07.md`](docs/auditoria-2026-07.md) y plan de
> corrección en [`docs/plans/seguridad-y-qa.md`](docs/plans/seguridad-y-qa.md).

## Producción

`./start.sh` prepara todo y arranca en un puerto:

1. Verifica `tmux`, `python3` y (solo si toca compilar) `bun`.
2. Crea el venv del backend e instala `requirements.txt` si no existe.
3. Compila el frontend (`bun run build` → `frontend/dist/`) si no existe.
4. Arranca uvicorn sirviendo **API + frontend** en el `HOST:PORT` de
   `backend/.env` (por defecto `127.0.0.1:8000`), con **un solo worker**
   (ver abajo: no es opcional).

### ⚠️ Un solo worker de uvicorn

**MuxSpace solo puede correr con `--workers 1`.** No es una recomendación ni
un default que nadie tocó: con más de un worker **se corrompe la biblioteca
de comandos** y **el login deja de funcionar**.

El porqué: los stores (`library_store`, `space_store`, `upload_store`) se
protegen con `threading.Lock`, que es **de proceso**, y cada mutación
reescribe su JSON **entero**. Con dos workers, dos peticiones simultáneas
leen la misma copia del fichero y la segunda en guardar borra lo que hizo la
primera. Sin excepción, sin log, sin 500: el usuario ve que su comando se
creó y al refrescar ya no está.

Y las sesiones de login viven en un diccionario **en memoria**, que no se
comparte entre procesos: quien entre por el worker A recibe un 401 en cuanto
una petición caiga en el B. El rate limit de login se multiplica por el
número de workers por el mismo motivo.

Cómo está protegido:

- `start.sh` pasa `--workers 1` explícito y hace `unset WEB_CONCURRENCY`.
- Si arrancas uvicorn a mano, **no** uses `--workers N` ni dejes
  `WEB_CONCURRENCY` en el entorno: uvicorn lo toma como valor por defecto y
  levanta varios workers sin que hayas escrito ninguna bandera.
- Si aun así arranca con más de uno, el backend lo avisa por el log de
  uvicorn en cada worker, diciendo qué se va a corromper.

La alternativa para escalar de verdad (locking de fichero con `fcntl.flock`)
está evaluada y descartada, con las razones y el orden correcto de
implementación, en [`docs/un-solo-worker.md`](docs/un-solo-worker.md).

Para reconstruir el frontend a mano tras cambios de UI:

```bash
cd frontend && bun run build      # regenera frontend/dist/
```

Si lo quieres siempre disponible, envuélvelo en un servicio de systemd (u
otro supervisor) que lo arranque con tu usuario y lo reinicie solo. Un
*reverse proxy* delante (Caddy/Nginx) queda fuera del alcance del propio
panel y es opcional.
