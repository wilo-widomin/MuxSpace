# Tmux Panel — Dashboard Dinámico de Sesiones Tmux

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
- **Autenticación** HTTP Basic opcional y **autocompletado** de directorios
  acotado a las raíces configuradas.

Un único proceso sirve la API, el WebSocket de las terminales y el frontend
compilado, todo en un **solo puerto local**. No depende de systemd, Docker ni
de ningún proxy (opcionales para exponerlo al exterior).

Especificación completa en [`docs/tmux_panel.md`](docs/tmux_panel.md).

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
- **Node.js 18+** (solo para compilar el frontend si no existe `frontend/dist/`)
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

Credenciales por defecto: **admin / admin** (configurables, ver abajo).

> Crea alguna sesión de tmux para probar: `tmux new -d -s trabajo`.

## Configuración

El backend se configura por variables de entorno. Copia el ejemplo y
edítalo:

```bash
cp backend/.env.example backend/.env
```

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `TMUX_PANEL_AUTH_ENABLED` | `true` | Activa la autenticación HTTP Basic |
| `TMUX_PANEL_USERNAME` / `TMUX_PANEL_PASSWORD` | `admin` / `admin` | Credenciales del dashboard |
| `TMUX_PANEL_PORT` | `8000` | Puerto del backend |
| `TMUX_PANEL_HOST` | `127.0.0.1` | Interfaz de enlace (`0.0.0.0` si lo pones tras un reverse proxy) |
| `TMUX_PANEL_TMUX_BINARY` | `tmux` | Ruta al binario de tmux (si no está en el PATH) |
| `TMUX_PANEL_CORS_ORIGINS` | `localhost:5173` | Orígenes CORS permitidos (casi irrelevante en producción: mismo origen) |
| `TMUX_PANEL_DIR_SUGGESTION_ROOTS` | `["~"]` | Raíces para el autocompletado de directorios (`~` = home del usuario que corre el backend) |

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
- **Comandos** y **Proyectos** (abajo, secciones fijas redimensionables
  entre sí): la biblioteca, con formularios de alta/edición en un **modal**
  central. La anchura del sidebar es arrastrable.

## Estructura del proyecto

```
tmux-panel/
├── backend/
│   ├── main.py            # App FastAPI y endpoints (sesiones + biblioteca)
│   ├── config.py          # Configuración por entorno (carga backend/.env)
│   ├── tmux_service.py    # Encapsula la CLI de tmux (list/new/kill/...)
│   ├── pty_bridge.py      # Puente WebSocket ↔ PTY (tmux attach)
│   ├── open_registry.py   # Registro en memoria de sesiones abiertas en el grid
│   ├── auth.py            # Autenticación HTTP Basic (+ token del WebSocket)
│   ├── command_store.py   # Persistencia de la biblioteca de comandos (JSON)
│   ├── library_store.py   # Persistencia de la biblioteca de proyectos (JSON)
│   ├── dir_suggestions.py # Autocompletado de directorios acotado a raíces
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
    ├── onboarding.md     # Guía de puesta en marcha paso a paso
    └── tmux_panel.md     # Especificación
```

## Seguridad

- **Autenticación**: login con sesión de servidor (cookie `HttpOnly` +
  `SameSite=Lax`), validando en modo `env` (usuario/contraseña fijos) o
  `pam` (credenciales de Linux). HTTP Basic se mantiene como alternativa
  para clientes CLI (`curl -u`). Para producción, sitúa el panel tras un
  *reverse proxy* (Caddy/Nginx) con TLS.
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
- **Bind local por defecto** (`TMUX_PANEL_HOST=127.0.0.1`). Usa `0.0.0.0`
  solo si vas a poner un proxy delante.
- **Autocompletado acotado**: las sugerencias de directorios solo listan
  bajo las raíces configuradas (`TMUX_PANEL_DIR_SUGGESTION_ROOTS`, `~` =
  home del usuario que corre el backend).
- **Portapapeles**: xterm.js propio + OSC 52. El backend activa en cada
  sesión, *best-effort*, `allow-passthrough on` y `set-clipboard on`
  (ignora errores en tmux antiguos).

## Producción

`./start.sh` prepara todo y arranca en un puerto:

1. Verifica `tmux`, `python3` y (solo si toca compilar) `npm`.
2. Crea el venv del backend e instala `requirements.txt` si no existe.
3. Compila el frontend (`npm run build` → `frontend/dist/`) si no existe.
4. Arranca uvicorn sirviendo **API + frontend** en el `HOST:PORT` de
   `backend/.env` (por defecto `127.0.0.1:8000`).

Para reconstruir el frontend a mano tras cambios de UI:

```bash
cd frontend && npm run build      # regenera frontend/dist/
```

Si lo quieres siempre disponible, envuélvelo en un servicio de systemd (u
otro supervisor) que lo arranque con tu usuario y lo reinicie solo. Un
*reverse proxy* delante (Caddy/Nginx) queda fuera del alcance del propio
panel y es opcional.
