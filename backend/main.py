"""Dashboard Dinámico de Sesiones Tmux — Backend (Capa de Control).

Expone la API REST que el frontend consume para:
  - Listar sesiones de tmux activas.
  - Abrir una sesión en el grid (se visualiza vía el puente PTY WebSocket).
  - Cerrar la vista de una sesión.

La terminal se sirve por el puente PTY (`pty_bridge`, endpoint
`/api/terminal/{name}`) con xterm.js en el cliente.

Ver `docs/muxspace.md` para la especificación completa.
"""
from __future__ import annotations

import asyncio
import errno
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import attention_store
import audit
import chime_store
import claude_transcript
import events
import config
import library_store
import logs
import space_store
import upload_store
import worklog
from auth import (
    SESSION_COOKIE,
    check_login_allowed,
    clear_login_failures,
    create_session as create_auth_session,
    destroy_all_sessions as destroy_all_auth_sessions,
    destroy_session as destroy_auth_session,
    is_ip_banned,
    register_login_failure,
    require_auth,
    verify_credentials,
    ws_user,
)
from datafiles import ensure_dir as ensure_data_dir, harden_tree, write_private
from dir_suggestions import (
    browse as browse_dir,
    create_dir as create_dir_within_roots,
    resolve_within_roots,
    suggest as suggest_dirs,
)
from errors import http_error, http_from
from library_store import (
    LibraryError,
    add_command,
    add_project,
    delete_command,
    delete_project,
    get_command,
    get_project,
    list_commands,
    list_projects,
    update_command,
    update_project,
)
from pty_bridge import _prepare_session, bridge
from chime_store import ChimeError
from space_store import SpaceError
from tmux_service import (
    TmuxError,
    create_session,
    detach_session,
    kill_session,
    list_sessions,
    pane_info as tmux_pane_info,
    rename_session,
    send_command,
    session_exists,
)

# Caracteres permitidos en el nombre de una sesión de tmux. Evitamos
# ':' y '.' (sintaxis de targets de tmux) y espacios para que el nombre
# sea seguro y predecible.
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_log = logs.obtener(__name__)


def _slug_session_name(name: str) -> str:
    """Normaliza un nombre de sesión sustituyendo '/' y '\\' por '_'.

    Un nombre de sesión debe ser un **único segmento** de ruta: la barra
    rompe el routing REST (`/api/.../{name}`) porque el proxy que hace
    mTLS decodifica `%2F` a '/' antes de que FastAPI resuelva la ruta, y
    la petición deja de casar (405). En vez de rechazar el nombre lo
    normalizamos, que es lo que el usuario espera al teclear una barra.
    """
    return (name or "").replace("/", "_").replace("\\", "_")


def _tmux_safe_label(label: str) -> str:
    """Adapta un label para que sea un nombre de sesión válido en tmux.

    tmux prohíbe '.' y ':' en los nombres de sesión (forman parte de la
    sintaxis de target `sesion:ventana.pane`), así que los sustituimos por
    '_'. También sustituimos las barras ('/' y '\\'), porque un nombre con
    barra rompe el routing REST (`/api/.../{name}`): el proxy decodifica
    `%2F` y la petición deja de casar la ruta. El resto (espacios,
    paréntesis…) se conserva tal cual, ya que pasamos el nombre siempre
    como argumento, nunca por shell.

    Y '$', porque en un `-t` tmux lo lee como el prefijo de un **ID de
    sesión** (`$0`, `$1`…) y no como el primer carácter de un nombre: una
    sesión llamada '$X' se crea y se lista con su nombre entero, pero
    después no hay forma de apuntarla y `kill_session` devuelve False para
    siempre (ni el prefijo `=` de coincidencia exacta la rescata, tmux 3.4).
    `_SESSION_NAME_RE` ya lo bloquea en `/api/create-session`, pero esta
    función es la que usan `launch` y `run-project`, así que sin esto la
    etiqueta de un comando o el título de un proyecto que empiece por '$'
    deja una sesión que el panel no puede cerrar (S17).
    """
    safe = re.sub(r"[.:/\\$]", "_", (label or "")).strip()
    return safe or "comando"


def _next_label_name(base: str) -> str:
    """Nombre de sesión para un comando lanzado N-ésima vez.

    Si no hay ninguna sesión para este comando -> `base`.
    Si ya existen K sesiones para ese comando (contando `base` y los
    `base (n)`) -> `base (K+1)`, de modo que el sufijo refleja cuántas
    sesiones hay para ese comando. Si ese nombre concreto ya estuviera
    ocupado (p. ej. por huecos en la numeración tras cerrar alguna), se
    incrementa hasta encontrar uno libre, evitando colisiones.
    """
    pattern = re.compile(rf"^{re.escape(base)} \((\d+)\)$")
    existing = {s.name for s in list_sessions()}
    count = sum(1 for n in existing if n == base or pattern.match(n))
    if count == 0:
        return base
    n = count + 1
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


# ----------------------------------------------------------------------
# Modelos de respuesta
# ----------------------------------------------------------------------
class AttentionInfo(BaseModel):
    """Aviso pendiente de una sesión: cuándo lo pidió y con qué etiqueta."""

    at: float
    label: str | None = None


class SessionInfo(BaseModel):
    name: str
    windows: int
    attached: bool
    created: str | None = None
    # Espacio al que pertenece, o None si está sin asignar. Qué sesiones se
    # ven en el grid lo decide el cliente a partir de esto; el backend ya no
    # guarda ningún estado de "abierta en el grid".
    space: str | None = None
    # Proyecto del que salió la sesión, o None si se creó a mano. El cliente
    # lo usa para pintar los enlaces del proyecto en la cabecera del tile.
    project: str | None = None
    # Aviso pendiente, o None si la sesión no reclama nada. Va aquí y no solo
    # por el bus de eventos para que una pestaña recién abierta —o recargada—
    # vea las marcas que se emitieron mientras no estaba.
    attention: AttentionInfo | None = None


class AttentionBody(BaseModel):
    """Cuerpo opcional de la marca: una etiqueta corta de una línea."""

    label: str | None = None


class SpaceInfo(BaseModel):
    id: str
    title: str
    order: int


class SpaceBody(BaseModel):
    title: str


class AssignSpaceBody(BaseModel):
    # None o "unassigned" => devolver la sesión a "Sin asignar".
    space: str | None = None


class CreateSessionResponse(BaseModel):
    name: str
    created: bool


class KillSessionResponse(BaseModel):
    name: str
    killed: bool  # ¿se terminó la sesión de tmux?


class DetachSessionResponse(BaseModel):
    name: str
    detached: bool


class MessageResponse(BaseModel):
    message: str


class LogoutAllResponse(BaseModel):
    # Cuántas sesiones se han revocado. Sirve para saber, en la respuesta a
    # una sospecha, si había alguna sesión abierta además de la tuya.
    revoked: int


# ---------------------------------------------------------------------- #
# Biblioteca: comandos y proyectos reutilizables                         #
# ---------------------------------------------------------------------- #
class CommandInfo(BaseModel):
    id: str
    label: str
    command: str


class CommandCreateBody(BaseModel):
    label: str = ""
    command: str


class CommandUpdateBody(BaseModel):
    label: str
    command: str


class ProjectLink(BaseModel):
    url: str
    # Texto de la badge. Vacío => el backend usa el host de la URL.
    title: str = ""


class ProjectInfo(BaseModel):
    id: str
    title: str
    cwd: str | None = None
    commands: list[str]
    links: list[ProjectLink] = []
    # Id del espacio al que van las sesiones del proyecto (null = ninguno).
    space: str | None = None


class ProjectCreateBody(BaseModel):
    title: str
    cwd: str | None = None
    commands: list[str] = []
    links: list[ProjectLink] = []
    # Vacío al crear => se crea un espacio con el título del proyecto.
    space: str | None = None


class ProjectUpdateBody(BaseModel):
    title: str
    cwd: str | None = None
    commands: list[str]
    links: list[ProjectLink] = []
    space: str | None = None


# Cuerpo opcional al crear una sesión de tmux: permite ejecutar un comando
# (normalmente uno de la biblioteca) dentro del shell de la nueva sesión.
class CreateSessionBody(BaseModel):
    command: str | None = None
    cwd: str | None = None


# Cuerpo para enviar un comando a una sesión existente.
class SendCommandBody(BaseModel):
    command: str


# Cuerpo para renombrar una sesión existente.
class RenameSessionBody(BaseModel):
    new_name: str


class DirSuggestionsResponse(BaseModel):
    items: list[str]


class PasteImageResponse(BaseModel):
    filename: str
    path: str  # ruta absoluta en el host donde queda guardada la imagen


class PasteInfo(BaseModel):
    filename: str
    path: str


class ChimeNote(BaseModel):
    freq: float  # hercios
    delay: float  # segundos desde el inicio de la campanilla
    duration: float  # segundos que tarda en apagarse


class ChimeConfig(BaseModel):
    """La receta de la campanilla, no el audio: lo sintetiza el navegador."""

    mode: str  # preset | custom | file
    preset: str
    volume: float
    muted: bool
    notes: list[ChimeNote]
    timbre: str  # sine | bell
    file: str | None = None  # nombre del audio propio subido, si lo hay


class DirBrowseResponse(BaseModel):
    path: str  # carpeta actual, en forma abreviada (~/...)
    parent: str | None = None  # None si subir un nivel sale de las raíces
    dirs: list[str]  # subcarpetas, en forma abreviada


class DirCreateBody(BaseModel):
    parent: str
    name: str


class DirPathResponse(BaseModel):
    path: str  # ruta abreviada de la carpeta creada/elegida


class UploadResponse(BaseModel):
    name: str  # nombre final del archivo en disco (puede diferir si hubo choque)
    path: str  # ruta absoluta en el host donde quedó guardado
    dir: str  # carpeta destino, en forma abreviada


class UploadInfo(BaseModel):
    name: str
    path: str
    dir: str


class LoginBody(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    user: str


# ----------------------------------------------------------------------
# Ciclo de vida de la app
# ----------------------------------------------------------------------
# Directorio de datos del panel: biblioteca de comandos, espacios,
# historial de subidas, intentos de login y capturas pegadas.
_DATA_DIR = Path(__file__).resolve().parent / "data"


def _workers_configurados(argv: list[str] | None = None,
                          entorno: dict[str, str] | None = None) -> int:
    """Cuántos workers pidió quien arrancó el proceso. 1 si no se pidió nada.

    El panel **solo puede correr con un worker**: los stores se protegen con
    `threading.Lock`, que es de proceso, así que dos workers hacen
    read-modify-write concurrente sobre los mismos JSON y se pierden datos
    (ver `docs/un-solo-worker.md`). Esto es lo que permite avisar en vez de
    que se descubra perdiendo la biblioteca.

    Se mira el `sys.argv` y el entorno, y NO `multiprocessing.parent_process()`,
    que sería lo obvio. Motivo, medido: uvicorn arranca los workers con
    `spawn`, y `multiprocessing.spawn` **restaura el `sys.argv` del padre en
    el hijo**, así que la bandera llega intacta al proceso que sirve. Pero
    `--reload` usa el mismo mecanismo de subproceso con UN solo worker, de
    modo que `parent_process()` también devuelve algo en desarrollo: avisaría
    de una corrupción que no existe. La bandera y la variable no se confunden.

    Los parámetros existen para poder probar la función sin montar cuatro
    despliegues de uvicorn.
    """
    argv = list(sys.argv if argv is None else argv)
    entorno = os.environ if entorno is None else entorno

    # `-w`/`--workers` es la bandera de uvicorn y también la de gunicorn, por
    # si algún día el panel se sirve con él.
    for i, arg in enumerate(argv):
        if arg in ("--workers", "-w") and i + 1 < len(argv):
            candidato = argv[i + 1]
        elif arg.startswith("--workers="):
            candidato = arg.split("=", 1)[1]
        else:
            continue
        try:
            return int(candidato)
        except ValueError:
            # `--workers hola` no es asunto nuestro: que se queje uvicorn.
            continue

    # uvicorn toma `WEB_CONCURRENCY` como default cuando no hay bandera
    # (`uvicorn/config.py`), así que un `export` heredado del entorno basta
    # para arrancar cuatro workers sin haber escrito nada en `start.sh`.
    try:
        return int(entorno.get("WEB_CONCURRENCY", "1"))
    except ValueError:
        return 1


def _migrar_espacios_de_proyectos() -> int:
    """Da un espacio a los proyectos que se crearon antes de que existiera.

    El campo `space` nació con el selector del formulario, así que todo lo que
    ya había en la biblioteca se quedó sin él — y sin espacio, la extensión de
    navegador abre el panel donde le toque en vez de en el del proyecto.

    Se casa POR TÍTULO antes de crear nada: quien ya tenía un espacio llamado
    como su proyecto no quiere un segundo igual al lado. Solo se crean los que
    de verdad faltan.

    Es idempotente: en el segundo arranque no hay ningún proyecto sin espacio
    y no toca nada.

    @returns Cuántos proyectos se han migrado.
    """
    proyectos = [p for p in library_store.list_projects() if not p.space]
    if not proyectos:
        return 0

    por_titulo = {s.title: s.id for s in space_store.list_spaces()}
    migrados = 0
    for proj in proyectos:
        space_id = por_titulo.get(proj.title)
        if space_id is None:
            try:
                space_id = space_store.create_space(proj.title).id
            except SpaceError as exc:
                # Un título que el store rechaza (vacío, larguísimo) no puede
                # tumbar el arranque del panel entero.
                _log.warning(
                    "No se pudo crear el espacio de «%s»: %s", proj.title, exc
                )
                continue
            por_titulo[proj.title] = space_id
        try:
            library_store.update_project(
                proj.id, proj.title, proj.cwd, proj.commands,
                [link.to_dict() for link in proj.links], space=space_id,
            )
        except LibraryError as exc:
            _log.warning("No se pudo migrar el proyecto «%s»: %s", proj.title, exc)
            continue
        migrados += 1
    return migrados


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Lo primero de todo: sin esto, cualquier mensaje que se emita más abajo
    # saldría al nivel que hubiera quedado por defecto.
    logs.configurar()
    # El bus de eventos reparte desde el loop; los endpoints `def` corren en
    # el threadpool y necesitan esta referencia para agendar el reparto.
    events.bind_loop(asyncio.get_running_loop())
    _log.info("MuxSpace arrancando (auth=%s, modo=%s)",
              config.AUTH_ENABLED, config.AUTH_MODE)
    # Todo lo de data/ es del usuario y solo suyo, pero se venía escribiendo
    # con el umask por defecto (0644): legible por cualquier usuario local
    # en una máquina donde el panel ya da una shell. Las escrituras nuevas
    # ya salen a 0600 (`datafiles`); esto cierra las que quedaron de antes.
    harden_tree(_DATA_DIR)
    # El secreto con el que los hooks del host marcan atención se crea aquí y
    # no la primera vez que alguien marca: quien lo necesita es un script que
    # lo LEE, y un fichero que aparece al primer uso no existe todavía cuando
    # se instala el hook. Ver `docs/avisos-de-atencion.md`.
    attention_store.hook_token()
    migrados = _migrar_espacios_de_proyectos()
    if migrados:
        _log.info("Espacio asignado a %d proyectos que no tenían", migrados)
    workers = _workers_configurados()
    if workers > 1:
        # Se emite una vez por worker, y eso es deliberado: N copias del
        # aviso son exactamente la señal de que hay N procesos peleándose por
        # los mismos ficheros.
        #
        # Iba por `uvicorn.error` para salir en la consola de arranque. Desde
        # Q6 va por el registrador del panel, que propaga a los mismos
        # manejadores: se sigue viendo igual y ahora obedece a
        # `MUXSPACE_LOG_LEVEL` como todo lo demás.
        _log.warning(
            "MuxSpace está arrancando con %d workers y SOLO admite 1. Los "
            "stores (biblioteca, espacios, subidas, sesiones) se protegen con "
            "threading.Lock, que no cruza procesos: con más de un worker dos "
            "peticiones simultáneas reescriben el mismo JSON entero y la "
            "biblioteca de comandos se corrompe (se pierden entradas sin "
            "aviso). Arranca con --workers 1 y sin WEB_CONCURRENCY. "
            "Ver docs/un-solo-worker.md.",
            workers,
        )
    yield
    # La terminal la sirve el puente PTY (`pty_bridge`) y qué se ve en el
    # grid lo decide cada pestaña del navegador: no hay ni procesos externos
    # que cerrar ni estado de vista que limpiar al apagar.


app = FastAPI(
    title="MuxSpace API",
    description="Dashboard dinámico para gestionar sesiones de tmux.",
    version="1.0.0",
    lifespan=lifespan,
    # `None` DESMONTA la ruta; no basta con no enlazarla desde ningún sitio.
    # Estas tres son rutas de Starlette, no del router de la API: no pasan por
    # `require_auth` ni las ve el contrato de rutas de los tests, así que se
    # servían con 200 a cualquiera que alcanzara el puerto. Ver DOCS_ENABLED.
    docs_url="/docs" if config.DOCS_ENABLED else None,
    redoc_url="/redoc" if config.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if config.DOCS_ENABLED else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Orígenes desde los que el navegador puede lanzar peticiones mutadoras o
# abrir el WebSocket. Imprescindible cuando la auth está desactivada (acceso
# por mTLS): el navegador presenta el certificado de cliente automáticamente,
# así que sin esta comprobación cualquier web maliciosa abierta en el
# navegador de un usuario legítimo podría disparar POSTs (CSRF) o conectar
# el terminal (cross-site WebSocket hijacking).
_ALLOWED_ORIGINS = {o.strip().rstrip("/") for o in config.CORS_ORIGINS if o.strip()}


@app.middleware("http")
async def _no_cache_api(request: Request, call_next):
    """`Cache-Control: no-store` en todo lo que cuelgue de /api.

    Estas respuestas no llevaban ninguna cabecera de caché, y sin ellas el
    navegador puede cachearlas por su cuenta (caché heurística). Visto en
    vivo: el panel se quedó sirviendo un `/api/sessions` y un `/api/projects`
    congelados —el listado no se refrescaba y los campos nuevos de un
    despliegue reciente no aparecían— por más veces que se recargara.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.middleware("http")
async def _csrf_origin_guard(request: Request, call_next):
    """403 a toda petición mutadora cuyo Origin no sea uno de los nuestros.

    Sin cabecera Origin (curl, scripts) se deja pasar: el CSRF es un ataque
    de navegador, y los navegadores siempre la envían en peticiones no-GET.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin", "").rstrip("/")
        if origin and origin not in _ALLOWED_ORIGINS:
            return JSONResponse(
                status_code=403, content={"detail": "Origen no permitido."}
            )
    return await call_next(request)


@app.middleware("http")
async def _reject_banned_ips(request: Request, call_next):
    """Corta toda petición HTTP de una IP de data/banned_ips.json con 403.

    El WebSocket del terminal no pasa por los middleware HTTP; su chequeo
    equivalente está en el handshake de `terminal_ws`.
    """
    ip = request.client.host if request.client else ""
    if is_ip_banned(ip):
        return JSONResponse(status_code=403, content={"detail": "Acceso denegado."})
    return await call_next(request)


# Cabeceras de seguridad. La clave es `frame-ancestors 'none'`: sin ella,
# una web maliciosa puede embeber el panel en un iframe invisible (el
# navegador presenta el certificado mTLS solo) y convertir un clic
# inducido en la ejecución de un proyecto. El guard de Origin no cubre ese
# caso: dentro del iframe todo es same-origin. En un panel que da shell,
# un clickjacking equivale a ejecución remota de código.
#
# `style-src 'unsafe-inline'` es necesario: xterm.js inyecta estilos en
# línea. `script-src` no lo necesita — el build de Vite no genera scripts
# inline. El WebSocket del terminal lo cubre `default-src 'self'`, que en
# CSP3 casa ws/wss del mismo origen.
_SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; frame-ancestors 'none'; "
        "img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


# Se declara el ÚLTIMO a propósito: en Starlette el middleware añadido más
# tarde queda por fuera, así que este envuelve a los demás y las cabeceras
# también salen en los 403 del guard de Origin y del baneo por IP.
@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


# Dependencia de autenticación reutilizable (sesión por cookie o HTTP
# Basic para clientes CLI). Con la auth desactivada devuelve "anonymous".
_auth = Depends(require_auth)


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
@app.get("/api/health", response_model=MessageResponse)
def health() -> MessageResponse:
    return MessageResponse(message="ok")


# ----------------------------------------------------------------------
# Login / sesión
# ----------------------------------------------------------------------
@app.post("/api/login", response_model=UserResponse)
def login(body: LoginBody, request: Request, response: Response) -> UserResponse:
    """Valida credenciales y abre sesión (cookie HttpOnly + SameSite=Lax)."""
    if not config.AUTH_ENABLED:
        return UserResponse(user="anonymous")

    ip = request.client.host if request.client else "?"
    if not check_login_allowed(ip):
        raise http_error(429, "err.login_rate_limited")
    if not verify_credentials(body.username, body.password):
        register_login_failure(ip)
        # Se anota el intento fallido, NUNCA la contraseña: quien lea el log
        # necesita saber que alguien probó desde esa IP con ese usuario, y
        # nada más. Ver la regla 2 del docstring de `audit`.
        audit.record(
            "login-failed", request=request, user=body.username, target=None
        )
        raise http_error(401, "err.bad_credentials")

    clear_login_failures(ip)
    token = create_auth_session(body.username)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        # El `Max-Age` es el techo ABSOLUTO (168 h), no la ventana de
        # inactividad (24 h), y NO se re-emite en cada petición. Es una
        # decisión, no un olvido: la caducidad de verdad la decide el
        # servidor en `session_user`, y una cookie que el navegador conserve
        # de más no da ningún acceso —la petición sale con 401 y el frontend
        # manda al login—. Re-emitirla en cada respuesta obligaría a que cada
        # endpoint del panel acepte un `Response` solo para eso, y a mandar
        # un `Set-Cookie` con una credencial viva en TODAS las respuestas,
        # incluidas las del sondeo cada 8 s. Peor por los dos lados.
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )
    # Tampoco el token de sesión: es una credencial viva, y un log de
    # auditoría que la lleve convierte el propio log en una llave.
    audit.record("login", request=request, user=body.username, target=None)
    return UserResponse(user=body.username)


@app.post("/api/logout", response_model=MessageResponse)
def logout(request: Request, response: Response) -> MessageResponse:
    """Cierra la sesión actual e invalida su cookie."""
    destroy_auth_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageResponse(message="ok")


@app.post("/api/logout-all", response_model=LogoutAllResponse)
def logout_all(
    request: Request, response: Response, user: str = _auth
) -> LogoutAllResponse:
    """Invalida **todas** las sesiones abiertas, incluida la de quien llama.

    Para cuando se sospecha que una cookie de sesión anda por donde no debe:
    hasta ahora la única forma de revocarlas era reiniciar el backend, que
    además se lleva por delante las terminales abiertas.

    Se lleva la propia por delante a propósito. Una revocación con
    excepciones no revoca nada: si el atacante es quien la llama, dejarle su
    sesión viva convierte el endpoint en un arma en su favor.

    Exige autenticación (`_auth`): sin ella sería un botón de "echar al
    dueño" accesible a cualquiera que alcance el puerto.
    """
    cuantas = destroy_all_auth_sessions()
    # La cookie del que llama ya no vale para nada, pero se borra igual para
    # que su navegador no siga mandándola en cada petición.
    response.delete_cookie(SESSION_COOKIE, path="/")
    audit.record("logout-all", request=request, user=user,
                 detail={"revoked": cuantas})
    return LogoutAllResponse(revoked=cuantas)


@app.get("/api/me", response_model=UserResponse)
def me(user: str = _auth) -> UserResponse:
    """Devuelve el usuario autenticado; 401 si no hay sesión válida."""
    return UserResponse(user=user)


@app.get("/api/dir-suggestions", response_model=DirSuggestionsResponse)
def dir_suggestions(q: str = "", user: str = _auth) -> DirSuggestionsResponse:
    """Autocompletado de directorios para los campos "directorio" del UI.

    Devuelve los subdirectorios inmediatos que coinciden con el prefijo `q`,
    pero solo cuando el directorio a listar cae bajo una de las raíces
    configuradas (`MUXSPACE_DIR_SUGGESTION_ROOTS`, con `~` expandido al
    home del usuario que ejecuta el backend).
    """
    return DirSuggestionsResponse(items=suggest_dirs(q))


async def _read_capped(request: Request, max_bytes: int, code: str) -> bytes:
    """Lee el cuerpo de la petición abortando en cuanto supera el tope.

    `await request.body()` bufferiza el cuerpo ENTERO antes de que podamos
    mirarlo: un POST de varios GB tumba el proceso aunque el límite sea de
    100 MB. Aquí se corta por `Content-Length` primero (el caso honesto) y,
    si no viene o miente, en cuanto los trozos leídos pasan del tope.
    """
    mb = max_bytes // (1024 * 1024)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise http_error(413, code, mb=mb)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise http_error(413, code, mb=mb)
        chunks.append(chunk)
    return b"".join(chunks)


# Directorio donde se depositan las imágenes que el usuario pega desde el
# panel (apaño para poder compartir capturas con Claude, que lee el fichero
# resultante). Cae bajo backend/data/, que está fuera del control de versiones.
_PASTE_DIR = Path(__file__).resolve().parent / "data" / "pastes"

# Extensiones por content-type aceptado. El navegador pega las capturas como
# image/png; cubrimos también los formatos habituales por si se arrastra un
# fichero.
_PASTE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# Tope de tamaño para una imagen pegada (evita llenar el disco por accidente).
_PASTE_MAX_BYTES = 25 * 1024 * 1024

# Cuántas capturas conservamos. Tras cada pegado se borran las más antiguas
# hasta dejar solo estas N, para que el directorio no crezca sin control.
_PASTE_KEEP = 5

# Un nombre de captura válido: paste-<índice>.<ext>. Se usa al servir un
# fichero concreto para no dejar escapar la ruta fuera de _PASTE_DIR.
_PASTE_NAME_RE = re.compile(r"^paste-\d+\.(?:png|jpg|webp|gif)$")


def _list_paste_files() -> list[Path]:
    """Capturas existentes ordenadas de más nueva a más vieja.

    El índice numérico de `paste-NNN` es creciente con el tiempo, así que
    ordenamos por ese número de forma descendente.
    """
    files = []
    for p in _PASTE_DIR.glob("paste-*"):
        m = re.match(r"paste-(\d+)", p.name)
        if m and p.is_file():
            files.append((int(m.group(1)), p))
    files.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in files]


@app.post("/api/paste-image", response_model=PasteImageResponse)
async def paste_image(request: Request, user: str = _auth) -> PasteImageResponse:
    """Guarda en disco la imagen que el usuario pega en el panel.

    El cuerpo de la petición son los bytes crudos de la imagen y el
    Content-Type indica el formato. Devuelve la ruta absoluta del fichero
    guardado para que se pueda compartir con Claude.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = _PASTE_EXT.get(content_type)
    if ext is None:
        raise http_error(415, "err.image_unsupported_format")
    data = await _read_capped(request, _PASTE_MAX_BYTES, "err.image_too_large")
    if not data:
        raise http_error(400, "err.image_missing")

    ensure_data_dir(_PASTE_DIR)
    # Nombre secuencial paste-NNN.ext: siguiente índice libre según lo que ya
    # exista, para no pisar capturas anteriores.
    nums = []
    for p in _PASTE_DIR.glob("paste-*"):
        m = re.match(r"paste-(\d+)", p.name)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    filename = f"paste-{n:03d}{ext}"
    target = _PASTE_DIR / filename
    write_private(target, data)

    # Retención: dejamos solo las _PASTE_KEEP más recientes (la recién
    # guardada incluida) y borramos el resto.
    for old in _list_paste_files()[_PASTE_KEEP:]:
        try:
            old.unlink()
        except OSError:
            pass  # si otra petición ya la borró, seguimos

    return PasteImageResponse(filename=filename, path=str(target))


@app.get("/api/pastes", response_model=list[PasteInfo])
def list_pastes(user: str = _auth) -> list[PasteInfo]:
    """Lista las capturas guardadas (máx. _PASTE_KEEP, la más nueva primero)."""
    return [
        PasteInfo(filename=p.name, path=str(p))
        for p in _list_paste_files()[:_PASTE_KEEP]
    ]


@app.get("/api/pastes/{filename}")
def get_paste(filename: str, user: str = _auth) -> FileResponse:
    """Sirve los bytes de una captura concreta (para las miniaturas)."""
    if not _PASTE_NAME_RE.match(filename):
        raise http_error(404, "err.paste_not_found")
    target = _PASTE_DIR / filename
    if not target.is_file():
        raise http_error(404, "err.paste_not_found")
    return FileResponse(str(target))


# ----------------------------------------------------------------------
# Campanilla del aviso de atención
# ----------------------------------------------------------------------
# Todo lo de aquí exige sesión del panel. El secreto del host (el que usan
# los hooks) sirve para MARCAR atención y para nada más: quien pueda avisar
# no tiene por qué poder cambiar lo que suena, ni subir un fichero.
@app.get("/api/chime", response_model=ChimeConfig)
def get_chime(user: str = _auth) -> ChimeConfig:
    """Ajuste actual de la campanilla."""
    return ChimeConfig(**chime_store.get())


@app.put("/api/chime", response_model=ChimeConfig)
def put_chime(cfg: ChimeConfig, user: str = _auth) -> ChimeConfig:
    """Guarda el ajuste. El nombre del audio lo decide el servidor."""
    try:
        return ChimeConfig(**chime_store.save(cfg.model_dump()))
    except ChimeError as exc:
        raise http_from(exc.status, exc) from exc


@app.post("/api/chime/audio", response_model=ChimeConfig)
async def upload_chime_audio(request: Request, user: str = _auth) -> ChimeConfig:
    """Sube una campanilla propia (bytes crudos, tipo en el Content-Type)."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    data = await _read_capped(
        request, chime_store.AUDIO_MAX_BYTES, "err.chime_audio_too_large"
    )
    try:
        return ChimeConfig(**chime_store.save_audio(data, content_type))
    except ChimeError as exc:
        raise http_from(exc.status, exc) from exc


@app.get("/api/chime/audio")
def get_chime_audio(user: str = _auth) -> FileResponse:
    """Sirve la campanilla propia para que el navegador la reproduzca."""
    path = chime_store.audio_file()
    if path is None:
        raise http_error(404, "err.chime_no_audio")
    return FileResponse(path)


@app.delete("/api/chime/audio", response_model=ChimeConfig)
def delete_chime_audio(user: str = _auth) -> ChimeConfig:
    """Borra la campanilla propia y vuelve al sonido del panel."""
    try:
        return ChimeConfig(**chime_store.delete_audio())
    except ChimeError as exc:
        raise http_from(exc.status, exc) from exc


@app.delete("/api/pastes/{filename}", response_model=MessageResponse)
def delete_paste(filename: str, user: str = _auth) -> MessageResponse:
    """Borra una captura concreta (la X de la galería en el panel)."""
    if not _PASTE_NAME_RE.match(filename):
        raise http_error(404, "err.paste_not_found")
    target = _PASTE_DIR / filename
    if target.is_file():
        try:
            target.unlink()
        except OSError as exc:
            raise http_error(500, "err.paste_delete_failed") from exc
    return MessageResponse(message="ok")


# ----------------------------------------------------------------------
# Subir archivos a una carpeta elegida (navegador de carpetas del panel).
#
# A diferencia de "pegar imagen" (destino fijo en data/pastes/), aquí el
# usuario elige la carpeta con un modal tipo explorador. Por seguridad, toda
# ruta —tanto la que se navega como la de destino de la subida— tiene que
# caer bajo las raíces configuradas (`MUXSPACE_DIR_SUGGESTION_ROOTS`); de eso
# se encarga `dir_suggestions.resolve_within_roots`. Los archivos subidos son
# ficheros reales del usuario: nunca los borramos, solo guardamos un pequeño
# historial (`upload_store`) para poder recopiar su ruta.
# ----------------------------------------------------------------------

# Tope de tamaño por archivo subido (se lee el cuerpo entero en memoria).
_UPLOAD_MAX_BYTES = 100 * 1024 * 1024

# Nombre de archivo válido: sin separadores de ruta ni componentes "." / "..".
# Se aplica al nombre original que envía el navegador para evitar escapar de
# la carpeta destino (path traversal).
_UPLOAD_NAME_RE = re.compile(r"^[^/\\\x00]+$")

# Nombre de carpeta válido al crear una subcarpeta desde el modal: un único
# segmento, sin separadores, sin "." aislado ni "..", y que no empiece por
# punto (nada de carpetas ocultas por accidente).
_DIR_NAME_RE = re.compile(r"^(?!\.)[^/\\\x00]+$")


def _unique_target(directory: Path, name: str) -> Path:
    """Ruta destino que no pisa un archivo existente.

    Si `name` ya existe en `directory`, inserta " (2)", " (3)"… antes de la
    extensión, como haría un navegador al descargar dos veces lo mismo.
    """
    target = directory / name
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    i = 2
    while True:
        candidate = directory / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


@app.get("/api/dir-browse", response_model=DirBrowseResponse)
def dir_browse(path: str = "", user: str = _auth) -> DirBrowseResponse:
    """Lista las subcarpetas de `path` para el navegador de carpetas.

    `path` vacío arranca en la primera raíz configurada. 404 si la carpeta
    no existe o cae fuera de las raíces permitidas.
    """
    result = browse_dir(path)
    if result is None:
        raise http_error(404, "err.dir_not_found")
    return DirBrowseResponse(**result)


@app.post("/api/dir-create", response_model=DirPathResponse)
def dir_create(body: DirCreateBody, user: str = _auth) -> DirPathResponse:
    """Crea una subcarpeta dentro de `parent` (ambos bajo una raíz)."""
    name = (body.name or "").strip()
    if not _DIR_NAME_RE.match(name) or name in (".", ".."):
        raise http_error(400, "err.dir_name_invalid")
    created = create_dir_within_roots(body.parent, name)
    if created is None:
        raise http_error(400, "err.dir_create_failed")
    return DirPathResponse(path=created)


@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(
    request: Request, dir: str = "", name: str = "", user: str = _auth
) -> UploadResponse:
    """Guarda un archivo subido en la carpeta `dir` elegida por el usuario.

    El cuerpo son los bytes crudos del archivo y `name` su nombre original.
    Devuelve la ruta absoluta donde quedó guardado (para compartirla con
    Claude) y la registra en el historial de subidas.
    """
    directory = resolve_within_roots(dir)
    if directory is None:
        raise http_error(400, "err.upload_dir_invalid")

    filename = (name or "").strip()
    if not filename or not _UPLOAD_NAME_RE.match(filename) or filename in (".", ".."):
        raise http_error(400, "err.upload_name_invalid")

    data = await _read_capped(request, _UPLOAD_MAX_BYTES, "err.upload_too_large")
    if not data:
        raise http_error(400, "err.upload_missing")

    target = _unique_target(directory, filename)
    try:
        # O_NOFOLLOW: si `target` es un symlink, falla en vez de escribir en
        # su destino, que puede estar FUERA de las raíces permitidas.
        # `_unique_target` no lo detecta porque `Path.exists()` sigue los
        # enlaces y un symlink colgante le parece un hueco libre. O_EXCL
        # cierra además la carrera entre esa comprobación y esta escritura.
        fd = os.open(
            target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError as exc:
        raise http_error(409, "err.upload_exists") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            # El destino es un symlink (colgante o no). Para quien sube, el
            # nombre está ocupado; lo que no vamos a hacer es seguir el
            # enlace y escribir donde apunte.
            raise http_error(409, "err.upload_exists") from exc
        raise http_error(500, "err.upload_failed") from exc
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except OSError as exc:
        raise http_error(500, "err.upload_failed") from exc

    upload_store.add(target.name, str(target), dir)
    audit.record(
        "upload", request=request, user=user, target=str(target),
        detail={"name": target.name, "dir": dir, "bytes": len(data)},
    )
    return UploadResponse(name=target.name, path=str(target), dir=dir)


@app.get("/api/uploads", response_model=list[UploadInfo])
def list_uploads(user: str = _auth) -> list[UploadInfo]:
    """Historial de las últimas subidas (la más reciente primero)."""
    return [UploadInfo(**item) for item in upload_store.list_recent()]


@app.delete("/api/uploads", response_model=list[UploadInfo])
def delete_upload(path: str, user: str = _auth) -> list[UploadInfo]:
    """Quita una entrada del historial (NO borra el archivo real del disco)."""
    return [UploadInfo(**item) for item in upload_store.remove(path)]


@app.websocket("/api/terminal/{name}")
async def terminal_ws(websocket: WebSocket, name: str) -> None:
    """Puente WebSocket <-> PTY que ejecuta `tmux attach -t {name}`.

    Es la vía por la que el frontend (nuestro xterm.js propio) visualiza e
    interactúa con una sesión de tmux. Se autentica con la cookie de sesión
    del login (el navegador la adjunta en el handshake). La copia al
    portapapeles la resuelve el cliente con navigator.clipboard.
    """
    ws_ip = websocket.client.host if websocket.client else ""
    if is_ip_banned(ws_ip):
        await websocket.close(code=1008)
        return
    ws_origin = websocket.headers.get("origin", "").rstrip("/")
    if ws_origin and ws_origin not in _ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    if ws_user(websocket) is None:
        await websocket.close(code=1008)
        return
    try:
        exists = session_exists(name)
    except TmuxError:
        exists = False
    if not exists:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    _prepare_session(name)
    await bridge(websocket, name)


def _modo(valor: str | None) -> str | None:
    """Modo de cálculo pedido, o None para el de la configuración.

    Lo que no se reconozca se ignora en vez de fallar: el modo es una forma de
    MIRAR los mismos datos, y un panel viejo pidiendo un modo que ya no existe
    debe seguir viendo sus horas.
    """
    limpio = (valor or "").strip().lower()
    return limpio if limpio in worklog.MODOS else None


class WorkBeat(BaseModel):
    """Latido de actividad. NO dice qué se tecleó: solo que hubo entrada."""

    space: str
    # Sesión que el usuario estaba mirando, para poder distinguir después las
    # horas con un agente delante. Opcional: un espacio puede estar vacío.
    session: str | None = None
    # 'auto' (medido: foco + entrada) o 'manual' (declarado: el usuario
    # encendió el cronómetro para trabajar fuera del panel). Se guarda para
    # poder mirarlos por separado, nunca para descartar uno.
    mode: str | None = None


@app.post("/api/worklog/beat")
def post_work_beat(beat: WorkBeat, user: str = _auth) -> dict:
    """Anota la ranura actual como trabajada en ese espacio.

    Quién decide que hay actividad es el CLIENTE, y solo mira entrada del
    usuario (teclado, ratón, scroll). La salida del terminal no cuenta: con el
    agente construyendo, el PTY escupe texto durante minutos con el usuario en
    otra pestaña, y contarlo mediría justo las horas que no se trabajan.

    La hora la pone el servidor. Si la ranura ya estaba tomada, no pasa nada:
    es exactamente lo que impide que dos pestañas cuenten doble.
    """
    espacio = (beat.space or "").strip()[:64] or "unassigned"
    sesion = (beat.session or "").strip()[:64] or None

    comando = None
    if sesion:
        try:
            comando = tmux_pane_info(sesion)["command"] or None
        except TmuxError:
            # La sesión pudo morir entre el latido y esta consulta. El tiempo
            # se registra igual: lo que se mide es al usuario, no a tmux.
            comando = None

    inicio = worklog.registrar(espacio, sesion, comando, source=beat.mode or "auto")
    return {"slot": inicio, "slot_seconds": worklog.SLOT_SECONDS}


@app.get("/api/worklog/summary")
def get_work_summary(
    desde: float | None = None,
    hasta: float | None = None,
    tz: int = 0,
    bridge: int | None = None,
    space: str | None = None,
    modo: str | None = None,
    user: str = _auth,
) -> dict:
    """Totales de tiempo trabajado: general, por espacio y por día local.

    `desde`/`hasta` en segundos epoch; `tz` es el desfase local en minutos
    (el del navegador), porque agrupar por UTC partiría la jornada de noche.

    `bridge` es el tope del puente de continuidad en minutos (0 lo apaga). Va
    por consulta y no solo en la configuración porque el puente se aplica al
    leer: cambiarlo recalcula el histórico entero al instante, así que se puede
    probar un valor desde el panel sin reiniciar ni tocar los datos.

    Con `space`, el resumen ENTERO es de ese espacio. Es el mismo filtro que
    entiende `/api/worklog/blocks`: la vista de tiempos los pide a la vez y las
    cifras de arriba tienen que hablar de lo mismo que la lista de abajo.
    """
    # Un desfase fuera de las zonas reales solo puede venir de un cliente roto.
    tz = max(-14 * 60, min(tz, 14 * 60))
    return worklog.resumen(
        desde, hasta, tz, bridge, (space or "").strip()[:64] or None, _modo(modo)
    )


@app.get("/api/worklog/blocks")
def get_work_blocks(
    desde: float | None = None,
    hasta: float | None = None,
    space: str | None = None,
    bridge: int | None = None,
    modo: str | None = None,
    tz: int = 0,
    user: str = _auth,
) -> list[dict]:
    """Tramos de trabajo (inicio y fin) derivados de las ranuras.

    Los tramos no se guardan: se derivan al leer agrupando ranuras contiguas.
    Guardarlos obligaría a cerrarlos, y un tramo sin cerrar —portátil cerrado,
    wifi caído— o se pierde entero o cuenta ocho horas.

    `bridge`: tope del puente de continuidad en minutos, igual que en el
    resumen. Los dos endpoints tienen que recibir el mismo o la lista de
    tramos no sumará el total.
    """
    tz = max(-14 * 60, min(tz, 14 * 60))
    return worklog.bloques(
        desde, hasta, (space or "").strip()[:64] or None, bridge, _modo(modo), tz
    )


class PauseRange(BaseModel):
    """Una pausa ya pasada: la respuesta a «¿estabas fuera?»."""

    start: float
    end: float


@app.get("/api/worklog/pauses")
def get_work_pauses(
    desde: float | None = None, hasta: float | None = None, user: str = _auth
) -> dict:
    """Pausas del periodo y el modo de cálculo vigente.

    El modo viaja con las pausas porque el panel necesita los dos para saber
    si enseñar el botón: en 'measured' las pausas no pintan nada.
    """
    return {
        "mode": worklog.MODO_POR_DEFECTO,
        "max_day_hours": worklog.JORNADA_MAX_HORAS,
        "pauses": worklog.pausas(desde, hasta),
        # Última ranura con actividad. El panel ya no pregunta nada con esto
        # —los huecos largos se descuentan solos—, pero sigue sirviendo para
        # saber si el registro está vivo.
        "last_slot": worklog.ultima_ranura(),
    }


@app.post("/api/worklog/pause")
def post_work_pause(user: str = _auth) -> dict:
    """Empieza una pausa: «me voy»."""
    return {"start": worklog.pausar()}


@app.post("/api/worklog/resume")
def post_work_resume(user: str = _auth) -> dict:
    """Cierra la pausa abierta: «ya estoy»."""
    cerrada = worklog.reanudar()
    return {"pause": cerrada}


@app.post("/api/worklog/pauses")
def post_work_pause_range(rango: PauseRange, user: str = _auth) -> dict:
    """Marca una pausa YA pasada, desde la vista de tiempos.

    Es para las ausencias cortas, las que no llegan al umbral que descuenta
    solo: nadie se acuerda de pulsar «me voy» antes de levantarse, y media
    hora de reunión sí se puede apuntar después.
    """
    if rango.end < rango.start:
        raise HTTPException(status_code=400, detail="rango_invalido")
    return worklog.marcar_pausa(rango.start, rango.end)


@app.delete("/api/worklog/pauses/{inicio}")
def delete_work_pause(inicio: float, user: str = _auth) -> dict:
    """Quita una pausa: marcar de más tiene que poder deshacerse."""
    return {"deleted": worklog.borrar_pausa(inicio)}


class GapRange(BaseModel):
    """La respuesta a una ausencia deducida: si ese hueco era trabajo o no."""

    start: float
    end: float
    # 'false' es «estaba fuera»: no cambia ningún total, pero se guarda para
    # que la pregunta del panel no vuelva a saltar en la siguiente ventana.
    worked: bool = True


@app.get("/api/worklog/gaps")
def get_work_gaps(
    desde: float | None = None,
    hasta: float | None = None,
    tz: int = 0,
    umbral: int | None = None,
    user: str = _auth,
) -> dict:
    """Ausencias deducidas del periodo: huecos largos sin ninguna señal.

    No están guardadas en ninguna parte: se derivan al leer, igual que los
    tramos. Por eso cambiar el umbral recalcula el histórico entero sin tocar
    un dato, y por eso lo que se guarda es lo contrario —el reclamo de que un
    hueco sí era trabajo—, que es lo único que no se puede deducir.
    """
    tz = max(-14 * 60, min(tz, 14 * 60))
    return {
        "absence_minutes": worklog.AUSENCIA_MIN,
        "gaps": worklog.huecos(desde, hasta, tz, umbral),
    }


@app.post("/api/worklog/gaps")
def post_work_gap_claim(rango: GapRange, user: str = _auth) -> dict:
    """Responde a un hueco descontado: «ese rato sí estaba trabajando» o no.

    La respuesta vive en el SERVIDOR, no en la pestaña. Es lo que permite que
    pregunte una sola ventana: se contesta en la que estás mirando y las demás
    lo saben en cuanto vuelven a consultar.
    """
    if rango.end < rango.start:
        raise HTTPException(status_code=400, detail="rango_invalido")
    return worklog.reclamar_hueco(rango.start, rango.end, rango.worked)


@app.delete("/api/worklog/gaps/{inicio}")
def delete_work_gap_claim(inicio: float, user: str = _auth) -> dict:
    """Borra la respuesta: el hueco vuelve a descontarse (y a preguntarse)."""
    return {"deleted": worklog.borrar_reclamo(inicio)}


@app.get("/api/terminal/{name}/transcript")
def get_transcript(name: str, user: str = _auth) -> dict:
    """La conversación de la sesión de Claude que corre en ese panel.

    Es la búsqueda que no puede hacer tmux: un panel con Claude Code ocupa la
    pantalla alternativa y su historial en tmux es cero, así que lo que se fue
    de pantalla no está en ningún buffer. Sí está en el `.jsonl` de la
    sesión, y esto lo sirve para que el panel lo enseñe y se pueda buscar.

    No recibe ninguna ruta del cliente: el directorio sale del panel de tmux,
    y de él el proyecto. Lo único que viaja es el nombre de la sesión.
    """
    if not _SESSION_NAME_RE.match(name):
        raise http_error(400, "err.session_name_invalid", {"name": name})
    try:
        panel = tmux_pane_info(name)
    except TmuxError as exc:
        raise http_from(404, exc) from exc
    if not panel["path"]:
        return {"available": False, "reason": "no_project", "messages": []}
    return claude_transcript.para_cwd(panel["path"])


# Sufijo ` (N)` que `_next_label_name` le pone a la segunda sesión de un
# mismo título en adelante. Se quita para casar por nombre (ver abajo).
_SUFIJO_REPETIDA = re.compile(r" \(\d+\)$")


def _project_by_name() -> dict[str, str]:
    """`nombre de sesión que produciría cada proyecto -> id del proyecto`.

    Es el plan B del vínculo explícito: las sesiones que ya existían antes
    de que el panel anotara de qué proyecto salía cada una no tienen entrada
    en `session_projects`, y sin esto sus terminales no enseñarían nunca los
    enlaces del proyecto. Casar por nombre es frágil —renombrar cualquiera
    de los dos lo rompe—, y por eso es solo el plan B: en cuanto la sesión
    se lanza desde el panel, manda el vínculo guardado.
    """
    return {_tmux_safe_label(p.title): p.id for p in list_projects()}


def _project_of(
    name: str,
    by_project: dict[str, str] | None = None,
    por_titulo: dict[str, str] | None = None,
) -> str | None:
    """Proyecto del que salió la sesión `name`, o `None` si no sale de ninguno.

    Manda el vínculo explícito (`session_projects`); el nombre solo se mira
    cuando no lo hay, y es el plan B que documenta `_project_by_name`. Los
    dos mapas se pueden pasar ya cargados para no releer la biblioteca una
    vez por sesión al listar el catálogo entero.
    """
    if by_project is None:
        by_project = library_store.session_projects()
    explicito = by_project.get(name)
    if explicito is not None:
        return explicito
    if por_titulo is None:
        por_titulo = _project_by_name()
    return por_titulo.get(_SUFIJO_REPETIDA.sub("", name))


@app.get("/api/sessions", response_model=list[SessionInfo])
def get_sessions(user: str = _auth) -> list[SessionInfo]:
    """Devuelve el catálogo de sesiones de tmux y el espacio de cada una."""
    try:
        sessions = list_sessions()
    except TmuxError as exc:
        raise http_from(500, exc) from exc

    by_name = space_store.assignments()
    by_project = library_store.session_projects()
    avisos = attention_store.pending()
    por_titulo = _project_by_name()

    def proyecto_de(nombre: str) -> str | None:
        return _project_of(nombre, by_project, por_titulo)

    return [
        SessionInfo(
            name=s.name,
            windows=s.windows,
            attached=s.attached,
            created=s.created,
            space=by_name.get(s.name),
            project=proyecto_de(s.name),
            attention=_aviso(avisos.get(s.name)),
        )
        for s in sessions
    ]


@app.post("/api/create-session/{name}", response_model=CreateSessionResponse)
def create_session_endpoint(
    request: Request,
    name: str,
    # `Body(...)` en el default ES la forma de declarar un cuerpo opcional en
    # FastAPI: el framework lo lee como metadato del parámetro, no como un
    # valor mutable compartido entre llamadas, que es el fallo contra el que
    # existe B008.
    body: CreateSessionBody = Body(default_factory=CreateSessionBody),  # noqa: B008
    user: str = _auth,
) -> CreateSessionResponse:
    """Crea una nueva sesión de tmux con el nombre indicado.

    El cuerpo opcional `{command, cwd}` permite ejecutar un comando de la
    biblioteca dentro del shell de la nueva sesión justo al crearla.
    """
    name = _slug_session_name(name)
    if not _SESSION_NAME_RE.match(name):
        raise http_error(400, "err.session_name_invalid")
    try:
        created = create_session(name, command=body.command, cwd=body.cwd)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    if not created:
        raise http_error(409, "err.session_exists", name=name)
    audit.record(
        "create-session",
        request=request,
        user=user,
        target=name,
        detail={"command": body.command, "cwd": body.cwd},
    )
    return CreateSessionResponse(name=name, created=True)


# Nombre base de las terminales que nace de un tile. Va en inglés como el
# resto del código, y el sufijo " (N)" se lo pone `_next_label_name`.
_TERMINAL_BASE = "Terminal"


@app.post("/api/sessions/{name}/spawn", response_model=CreateSessionResponse)
def spawn_terminal_endpoint(
    request: Request, name: str, user: str = _auth
) -> CreateSessionResponse:
    """Crea otra sesión de tmux en el mismo directorio que `name`.

    Es el icono de terminal de la cabecera de cada tile: "otra terminal
    aquí mismo". El directorio NO viaja desde el cliente —lo lee el
    servidor del panel activo de la sesión (`pane_current_path`)—, así que
    el navegador no puede pedir una sesión en un directorio arbitrario.

    Si tmux no sabe decir el directorio (sesión recién muerta, panel raro),
    la sesión se crea igual en el directorio por defecto: quedarse sin
    terminal es peor que quedarse sin el `cd`.
    """
    try:
        panel = tmux_pane_info(name)
    except TmuxError as exc:
        raise http_from(404, exc) from exc

    cwd = panel["path"] or None
    new_name = _next_label_name(_TERMINAL_BASE)
    try:
        created = create_session(new_name, cwd=cwd)
        if not created:
            # Carrera muy improbable: el nombre libre dejó de estarlo entre
            # el cálculo y la creación. Se reintenta una vez, igual que en
            # `launch`.
            new_name = _next_label_name(_TERMINAL_BASE)
            created = create_session(new_name, cwd=cwd)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    if not created:
        raise http_error(409, "err.session_exists", name=new_name)

    # La terminal hija hereda el proyecto de la madre: el icono significa
    # "otra terminal aquí mismo", y "aquí" incluye los enlaces de la
    # cabecera, no solo el directorio. El nombre nuevo es `Terminal (N)`,
    # así que sin este vínculo explícito no lo rescataría nadie: el plan B
    # por título nunca casaría.
    proyecto = _project_of(name)
    if proyecto is not None:
        library_store.link_session(new_name, proyecto)

    audit.record(
        "spawn-terminal",
        request=request,
        user=user,
        target=new_name,
        detail={"from": name, "cwd": cwd, "project_id": proyecto},
    )
    return CreateSessionResponse(name=new_name, created=True)


@app.post("/api/kill-session/{name}", response_model=KillSessionResponse)
def kill_session_endpoint(
    request: Request, name: str, user: str = _auth
) -> KillSessionResponse:
    """Termina la sesión de tmux `name` con `tmux kill-session`.

    Su terminal (puente PTY) se cierra sola al desaparecer la sesión, y la
    vista del grid se actualiza en el cliente al refrescar el listado.
    """
    try:
        killed = kill_session(name)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    # La sesión ya no existe: su asignación de espacio sobra y, si alguien
    # crea otra con el mismo nombre, no debe heredar el espacio de la vieja.
    space_store.forget_session(name)
    library_store.forget_session(name)
    attention_store.forget_session(name)
    _publicar_atencion(name, None)
    audit.record(
        "kill-session", request=request, user=user, target=name,
        detail={"killed": killed},
    )
    return KillSessionResponse(name=name, killed=killed)


@app.post("/api/detach-session/{name}", response_model=DetachSessionResponse)
def detach_session_endpoint(name: str, user: str = _auth) -> DetachSessionResponse:
    """Separa (detach) a todos los clientes de la sesión sin destruirla."""
    try:
        detached = detach_session(name)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    return DetachSessionResponse(name=name, detached=detached)


@app.post("/api/send-command/{name}", response_model=MessageResponse)
def send_command_endpoint(
    request: Request,
    name: str,
    body: SendCommandBody,
    user: str = _auth,
) -> MessageResponse:
    """Envía un comando a la sesión de tmux indicada y pulsa Enter."""
    try:
        if not session_exists(name):
            raise http_error(404, "err.session_missing", name=name)
    except TmuxError as exc:
        raise http_from(500, exc) from exc

    try:
        send_command(name, body.command)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    audit.record(
        "send-command", request=request, user=user, target=name,
        detail={"command": body.command},
    )
    return MessageResponse(message="ok")


@app.post("/api/rename-session/{name}", response_model=MessageResponse)
def rename_session_endpoint(
    request: Request,
    name: str,
    body: RenameSessionBody,
    user: str = _auth,
) -> MessageResponse:
    """Renombra la sesión de tmux `name` a `body.new_name`.

    Arrastra su asignación de espacio al nuevo nombre para que la sesión no
    se caiga a "Sin asignar" solo por renombrarla.
    """
    new_name = _slug_session_name((body.new_name or "").strip())
    if not _SESSION_NAME_RE.match(new_name):
        raise http_error(400, "err.session_name_invalid")
    try:
        if not session_exists(name):
            raise http_error(404, "err.session_missing", name=name)
        if new_name != name:
            rename_session(name, new_name)
    except TmuxError as exc:
        raise http_from(500, exc) from exc

    space_store.rename_session(name, new_name)
    library_store.rename_session(name, new_name)
    if new_name != name:
        attention_store.rename_session(name, new_name)
        _publicar_atencion(name, None)
        _publicar_atencion(new_name, attention_store.get(new_name))
    audit.record(
        "rename-session", request=request, user=user, target=name,
        detail={"new_name": new_name},
    )
    return MessageResponse(message="ok")


# ---------------------------------------------------------------------- #
# Atención: qué sesiones reclaman al usuario                             #
# ---------------------------------------------------------------------- #
# Cabecera con el secreto del host. La marca la pide un hook que corre en la
# máquina, sin navegador ni cookie; ver `attention_store.hook_token`.
_HOOK_TOKEN_HEADER = "X-Muxspace-Token"

# Segundos de silencio antes de mandar un latido por el bus de eventos.
_EVENTS_PING = 30.0


def _aviso(pendiente: attention_store.Attention | None) -> AttentionInfo | None:
    """Traduce el aviso interno al modelo que sale por la API."""
    if pendiente is None:
        return None
    return AttentionInfo(at=pendiente.at, label=pendiente.label)


def _publicar_atencion(
    name: str, pendiente: attention_store.Attention | None
) -> None:
    """Anuncia a las pestañas abiertas que una sesión marcó o desmarcó.

    `attention: None` es el evento de apagado. Se manda siempre, también
    cuando no había marca, para que una pestaña que se perdió el encendido no
    se quede con una señal que ya nadie tiene.
    """
    aviso = _aviso(pendiente)
    events.publish({
        "type": "attention",
        "session": name,
        "attention": aviso.model_dump() if aviso else None,
    })


def _attention_auth(request: Request) -> str:
    """Autoriza a marcar: secreto del host, o sesión del panel.

    El hook presenta el secreto; el panel, su cookie. Se comprueba primero el
    secreto porque el hook nunca traerá cookie y no tiene sentido hacerle
    pagar un 401 antes.
    """
    if attention_store.token_matches(request.headers.get(_HOOK_TOKEN_HEADER)):
        return "hook"
    return require_auth(request)


@app.post("/api/attention/{name}", response_model=AttentionInfo)
async def mark_attention(
    name: str,
    body: AttentionBody | None = Body(default=None),
    user: str = Depends(_attention_auth),
) -> AttentionInfo:
    """Marca que la sesión `name` reclama la atención del usuario.

    No se comprueba que la sesión exista en tmux: quien marca es un proceso
    que corre DENTRO de ella, así que existe por construcción, y un `tmux
    list-sessions` de más en el camino solo añadiría una forma de que el
    aviso se pierda.
    """
    pendiente = attention_store.mark(name, body.label if body else None)
    _publicar_atencion(name, pendiente)
    return _aviso(pendiente)


@app.delete("/api/attention/{name}", response_model=MessageResponse)
async def clear_attention(name: str, user: str = _auth) -> MessageResponse:
    """Apaga la marca de `name`: el usuario ya ha atendido esa terminal.

    Idempotente y silencioso si no había marca. Lo llama el panel al teclear
    o pulsar en el tile, y eso pasa constantemente: un 404 aquí solo serviría
    para llenar la consola del navegador de errores que no lo son.
    """
    attention_store.clear(name)
    _publicar_atencion(name, None)
    return MessageResponse(message="ok")


@app.delete("/api/attention", response_model=MessageResponse)
async def clear_all_attention(user: str = _auth) -> MessageResponse:
    """Apaga todas las marcas de golpe."""
    for nombre in attention_store.clear_all():
        _publicar_atencion(nombre, None)
    return MessageResponse(message="ok")


@app.websocket("/api/events")
async def events_ws(websocket: WebSocket) -> None:
    """Avisos empujados a la pestaña: uno por pestaña, no por terminal.

    Existe porque el sondeo del listado se detiene con la pestaña oculta, que
    es cuando hace falta enterarse. Se autentica igual que el terminal (la
    cookie del handshake) y cierra con 1008 sin distinguir causa.
    """
    ws_ip = websocket.client.host if websocket.client else ""
    if is_ip_banned(ws_ip):
        await websocket.close(code=1008)
        return
    ws_origin = websocket.headers.get("origin", "").rstrip("/")
    if ws_origin and ws_origin not in _ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return
    if ws_user(websocket) is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    async with events.subscribe() as cola:
        try:
            while True:
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=_EVENTS_PING)
                except asyncio.TimeoutError:
                    # Latido: un WebSocket callado el tiempo suficiente lo
                    # corta el proxy de delante, y el cliente se enteraría de
                    # que está desconectado justo cuando llega un aviso.
                    evento = {"type": "ping"}
                await websocket.send_json(evento)
        except Exception:
            # Cliente que se va (pestaña cerrada, red que cae): no es un
            # error del servidor y no merece ruido en el registro.
            pass


# ---------------------------------------------------------------------- #
# Espacios: agrupar sesiones por cliente / categoría / proyecto           #
# ---------------------------------------------------------------------- #
@app.get("/api/spaces", response_model=list[SpaceInfo])
def get_spaces(user: str = _auth) -> list[SpaceInfo]:
    """Espacios existentes, en orden. "Sin asignar" es virtual y no sale."""
    return [SpaceInfo(**s.to_dict()) for s in space_store.list_spaces()]


@app.post("/api/spaces", response_model=SpaceInfo, status_code=201)
def create_space_endpoint(body: SpaceBody, user: str = _auth) -> SpaceInfo:
    try:
        return SpaceInfo(**space_store.create_space(body.title).to_dict())
    except SpaceError as exc:
        raise http_from(400, exc) from exc


@app.put("/api/spaces/{space_id}", response_model=SpaceInfo)
def update_space_endpoint(
    space_id: str, body: SpaceBody, user: str = _auth
) -> SpaceInfo:
    try:
        return SpaceInfo(**space_store.update_space(space_id, body.title).to_dict())
    except SpaceError as exc:
        raise http_from(400, exc) from exc


@app.delete("/api/spaces/{space_id}", response_model=MessageResponse)
def delete_space_endpoint(space_id: str, user: str = _auth) -> MessageResponse:
    """Borra el espacio; sus sesiones vuelven a "Sin asignar", intactas."""
    try:
        space_store.delete_space(space_id)
    except SpaceError as exc:
        raise http_from(404, exc) from exc
    return MessageResponse(message="ok")


@app.put("/api/sessions/{name}/space", response_model=MessageResponse)
def assign_space_endpoint(
    name: str, body: AssignSpaceBody, user: str = _auth
) -> MessageResponse:
    """Mueve una sesión a un espacio (o la deja sin asignar con `null`)."""
    try:
        if not session_exists(name):
            raise http_error(404, "err.session_missing", name=name)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    try:
        space_store.assign(name, body.space)
    except SpaceError as exc:
        raise http_from(400, exc) from exc
    return MessageResponse(message="ok")


# ---------------------------------------------------------------------- #
# Biblioteca de comandos reutilizables (CRUD)                            #
# ---------------------------------------------------------------------- #
@app.get("/api/commands", response_model=list[CommandInfo])
def get_commands(user: str = _auth) -> list[CommandInfo]:
    """Devuelve todos los comandos guardados en la biblioteca."""
    return [CommandInfo(**c.to_dict()) for c in list_commands()]


@app.post("/api/commands/{cmd_id}/launch", response_model=CreateSessionResponse)
def launch_command_endpoint(
    request: Request,
    cmd_id: str,
    user: str = _auth,
) -> CreateSessionResponse:
    """Lanza un comando de la biblioteca en una nueva sesión de tmux.

    El nombre de la sesión es el **label** del comando. Si ya existen
    sesiones para ese mismo comando, se añade el sufijo ` (N)` donde N es
    la cantidad de sesiones ya abiertas para ese comando. Lo usa el frontend
    para ejecutar un Comando cuando ninguna terminal del grid tiene foco.
    """
    cmd = get_command(cmd_id)
    if cmd is None:
        raise http_error(404, "err.command_not_found")

    base = _tmux_safe_label(cmd.label)
    name = _next_label_name(base)

    try:
        created = create_session(name, command=cmd.command)
    except TmuxError as exc:
        raise http_from(500, exc) from exc
    if not created:
        # Carrera muy improbable: el nombre libre dejó de estarlo entre la
        # comprobación y la creación. Lo reintentamos una vez.
        name = _next_label_name(base)
        try:
            created = create_session(name, command=cmd.command)
        except TmuxError as exc:
            raise http_from(500, exc) from exc
    audit.record(
        "launch", request=request, user=user, target=name,
        detail={"command_id": cmd_id, "command": cmd.command},
    )
    return CreateSessionResponse(name=name, created=True)


@app.post("/api/commands", response_model=CommandInfo, status_code=201)
def create_command(
    body: CommandCreateBody,
    user: str = _auth,
) -> CommandInfo:
    """Crea un comando nuevo en la biblioteca."""
    try:
        created = add_command(body.label, body.command)
    except LibraryError as exc:
        raise http_from(400, exc) from exc
    return CommandInfo(**created.to_dict())


@app.put("/api/commands/{cmd_id}", response_model=CommandInfo)
def update_command_endpoint(
    cmd_id: str,
    body: CommandUpdateBody,
    user: str = _auth,
) -> CommandInfo:
    """Actualiza un comando existente."""
    try:
        updated = update_command(cmd_id, body.label, body.command)
    except LibraryError as exc:
        raise http_from(400, exc) from exc
    if updated is None:
        raise http_error(404, "err.command_not_found")
    return CommandInfo(**updated.to_dict())


@app.delete("/api/commands/{cmd_id}", response_model=MessageResponse)
def delete_command_endpoint(
    cmd_id: str,
    user: str = _auth,
) -> MessageResponse:
    """Elimina un comando de la biblioteca."""
    if not delete_command(cmd_id):
        raise http_error(404, "err.command_not_found")
    return MessageResponse(message="ok")


# ---------------------------------------------------------------------- #
# Biblioteca de proyectos (CRUD + ejecución)                              #
# ---------------------------------------------------------------------- #
def _project_info(proj, known_spaces: set[str] | None = None) -> ProjectInfo:
    """Convierte un proyecto de la biblioteca en su respuesta HTTP.

    Un espacio se puede borrar sin que la biblioteca se entere, así que aquí
    se comprueba que el que guarda el proyecto siga existiendo; si no, se
    devuelve `null` en vez de un id muerto que abriría un espacio fantasma.
    """
    data = proj.to_dict()
    if data.get("space"):
        if known_spaces is None:
            known_spaces = {s.id for s in space_store.list_spaces()}
        if data["space"] not in known_spaces:
            data["space"] = None
    return ProjectInfo(**data)


@app.get("/api/projects", response_model=list[ProjectInfo])
def get_projects(user: str = _auth) -> list[ProjectInfo]:
    """Devuelve todos los proyectos guardados en la biblioteca."""
    known = {s.id for s in space_store.list_spaces()}
    return [_project_info(p, known) for p in list_projects()]


@app.post("/api/projects", response_model=ProjectInfo, status_code=201)
def create_project(
    body: ProjectCreateBody,
    user: str = _auth,
) -> ProjectInfo:
    """Crea un proyecto nuevo en la biblioteca."""
    # El título se usa como nombre de la sesión al ejecutar el proyecto, así
    # que normalizamos las barras aquí también (ver `_slug_session_name`).
    title = _slug_session_name(body.title)
    # Sin espacio elegido se crea uno con el título del proyecto: es lo que
    # el formulario de alta anuncia, y evita que la extensión de navegador
    # tenga que abrir un proyecto que no lleva a ninguna parte.
    space_id = (body.space or "").strip() or None
    created_space: str | None = None
    if space_id is None:
        try:
            created_space = space_store.create_space(title).id
        except SpaceError as exc:
            raise http_from(400, exc) from exc
        space_id = created_space
    try:
        created = add_project(
            title, body.cwd, body.commands,
            [link.model_dump() for link in body.links],
            space=space_id,
        )
    except LibraryError as exc:
        # El espacio recién creado se queda huérfano si el proyecto no llega
        # a existir, así que se deshace antes de propagar el error.
        if created_space is not None:
            try:
                space_store.delete_space(created_space)
            except SpaceError:
                pass
        raise http_from(400, exc) from exc
    return _project_info(created)


@app.put("/api/projects/{project_id}", response_model=ProjectInfo)
def update_project_endpoint(
    project_id: str,
    body: ProjectUpdateBody,
    user: str = _auth,
) -> ProjectInfo:
    """Actualiza un proyecto existente."""
    title = _slug_session_name(body.title)
    try:
        updated = update_project(
            project_id, title, body.cwd, body.commands,
            [link.model_dump() for link in body.links],
            space=(body.space or "").strip() or None,
        )
    except LibraryError as exc:
        raise http_from(400, exc) from exc
    if updated is None:
        raise http_error(404, "err.project_not_found")
    return _project_info(updated)


@app.delete("/api/projects/{project_id}", response_model=MessageResponse)
def delete_project_endpoint(
    project_id: str,
    user: str = _auth,
) -> MessageResponse:
    """Elimina un proyecto de la biblioteca."""
    if not delete_project(project_id):
        raise http_error(404, "err.project_not_found")
    return MessageResponse(message="ok")


@app.post("/api/projects/{project_id}/run", response_model=CreateSessionResponse)
def run_project_endpoint(
    request: Request,
    project_id: str,
    user: str = _auth,
) -> CreateSessionResponse:
    """Ejecuta un proyecto en una sesión nueva de tmux.

    Crea una sesión con el **título** como nombre (sufijo ` (N)` si ya
    existen sesiones para ese título), hace `cd <cwd>` y ejecuta la lista
    de comandos secuencialmente en el mismo shell. El primer comando se
    inyecta al crear la sesión (`cd <cwd> && <cmd>`); los siguientes se
    envían con `send-keys` en orden.
    """
    proj = get_project(project_id)
    if proj is None:
        raise http_error(404, "err.project_not_found")
    if not proj.commands:
        raise http_error(400, "err.project_no_commands")

    base = _tmux_safe_label(proj.title)
    name = _next_label_name(base)
    first, rest = proj.commands[0], proj.commands[1:]

    def _try_create(n: str) -> str | None:
        try:
            if create_session(n, command=first, cwd=proj.cwd):
                return n
        except TmuxError as exc:
            raise http_from(500, exc) from exc
        return None

    created_name = _try_create(name)
    if created_name is None:
        # Carrera muy improbable: el nombre libre dejó de estarlo entre la
        # comprobación y la creación. Lo reintentamos una vez.
        created_name = _try_create(_next_label_name(base))
        if created_name is None:
            raise http_error(409, "err.session_exists", name=name)
    name = created_name

    # Comandos restantes, secuencialmente en el mismo shell (ya posicionado
    # en cwd por el `cd` del primer comando).
    for cmd in rest:
        try:
            send_command(name, cmd)
        except TmuxError as exc:
            raise http_from(500, exc) from exc

    # La sesión nace en el espacio del proyecto: es lo que hace que abrir
    # `?space=<id>` enseñe algo. Un espacio borrado a mano deja de existir
    # sin que la biblioteca se entere, y eso no puede tumbar el lanzamiento.
    if proj.space:
        try:
            space_store.assign(name, proj.space)
        except SpaceError:
            pass

    # El vínculo se guarda para que la cabecera del tile sepa qué enlaces
    # tocan. Sobrevive a renombrar la sesión (ver `rename-session`).
    library_store.link_session(name, project_id)

    audit.record(
        "run-project", request=request, user=user, target=name,
        detail={"project_id": project_id, "cwd": proj.cwd,
                "commands": proj.commands},
    )
    return CreateSessionResponse(name=name, created=True)


# ----------------------------------------------------------------------
# Frontend estático (build de Vite)
# ----------------------------------------------------------------------
# En producción el backend sirve directamente el build del frontend
# (frontend/dist), de modo que Caddy solo necesita un reverse_proxy a
# este proceso. `html=True` hace que `/` devuelva index.html y sirve los
# assets bajo `/assets/...`. Se monta al final para que las rutas /api
# tengan prioridad.
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.get("/dashboard")
def get_dashboard() -> FileResponse:
    """Sirve el `index.html` para la vista de tiempos.

    Hace falta una ruta explícita: `StaticFiles` devuelve 404 para lo que no
    es un archivo, y `/dashboard` es una ruta del cliente (la resuelve
    `App.jsx` mirando el `pathname`, sin router). Sin esto, recargar ahí o
    abrirla en pestaña nueva daría un 404 del servidor.

    No lleva autenticación porque no devuelve datos: es la misma cáscara que
    `/`. Los tiempos viajan por `/api/worklog/*`, que sí la exige.
    """
    indice = _FRONTEND_DIST / "index.html"
    if not indice.is_file():
        raise http_error(404, "err.http", {"status": 404})
    return FileResponse(str(indice))


if _FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
