"""Dashboard Dinámico de Sesiones Tmux — Backend (Capa de Control).

Expone la API REST que el frontend consume para:
  - Listar sesiones de tmux activas.
  - Abrir una sesión en el grid (se visualiza vía el puente PTY WebSocket).
  - Cerrar la vista de una sesión.

La terminal se sirve por el puente PTY (`pty_bridge`, endpoint
`/api/terminal/{name}`) con xterm.js en el cliente.

Ver `docs/tmux_panel.md` para la especificación completa.
"""
from __future__ import annotations

import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
from auth import (
    SESSION_COOKIE,
    check_login_allowed,
    clear_login_failures,
    is_ip_banned,
    create_session as create_auth_session,
    destroy_session as destroy_auth_session,
    register_login_failure,
    require_auth,
    verify_credentials,
    ws_user,
)
from dir_suggestions import suggest as suggest_dirs
from errors import http_error, http_from
from pty_bridge import bridge, _prepare_session
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
import space_store
from space_store import SpaceError
from tmux_service import (
    TmuxError,
    create_session,
    detach_session,
    kill_session,
    list_sessions,
    rename_session,
    send_command,
    session_exists,
)

# Caracteres permitidos en el nombre de una sesión de tmux. Evitamos
# ':' y '.' (sintaxis de targets de tmux) y espacios para que el nombre
# sea seguro y predecible.
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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
    """
    safe = re.sub(r"[.:/\\]", "_", (label or "")).strip()
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
class SessionInfo(BaseModel):
    name: str
    windows: int
    attached: bool
    created: str | None = None
    # Espacio al que pertenece, o None si está sin asignar. Qué sesiones se
    # ven en el grid lo decide el cliente a partir de esto; el backend ya no
    # guarda ningún estado de "abierta en el grid".
    space: str | None = None


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


class ProjectInfo(BaseModel):
    id: str
    title: str
    cwd: str | None = None
    commands: list[str]


class ProjectCreateBody(BaseModel):
    title: str
    cwd: str | None = None
    commands: list[str] = []


class ProjectUpdateBody(BaseModel):
    title: str
    cwd: str | None = None
    commands: list[str]


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


class LoginBody(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    user: str


# ----------------------------------------------------------------------
# Ciclo de vida de la app
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # La terminal la sirve el puente PTY (`pty_bridge`) y qué se ve en el
    # grid lo decide cada pestaña del navegador: no hay ni procesos externos
    # que cerrar ni estado de vista que limpiar al apagar.


app = FastAPI(
    title="Tmux Panel API",
    description="Dashboard dinámico para gestionar sesiones de tmux.",
    version="1.0.0",
    lifespan=lifespan,
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
        raise http_error(401, "err.bad_credentials")

    clear_login_failures(ip)
    token = create_auth_session(body.username)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=config.SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        secure=config.COOKIE_SECURE,
        path="/",
    )
    return UserResponse(user=body.username)


@app.post("/api/logout", response_model=MessageResponse)
def logout(request: Request, response: Response) -> MessageResponse:
    """Cierra la sesión actual e invalida su cookie."""
    destroy_auth_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return MessageResponse(message="ok")


@app.get("/api/me", response_model=UserResponse)
def me(user: str = _auth) -> UserResponse:
    """Devuelve el usuario autenticado; 401 si no hay sesión válida."""
    return UserResponse(user=user)


@app.get("/api/dir-suggestions", response_model=DirSuggestionsResponse)
def dir_suggestions(q: str = "", user: str = _auth) -> DirSuggestionsResponse:
    """Autocompletado de directorios para los campos "directorio" del UI.

    Devuelve los subdirectorios inmediatos que coinciden con el prefijo `q`,
    pero solo cuando el directorio a listar cae bajo una de las raíces
    configuradas (`TMUX_PANEL_DIR_SUGGESTION_ROOTS`, con `~` expandido al
    home del usuario que ejecuta el backend).
    """
    return DirSuggestionsResponse(items=suggest_dirs(q))


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
    data = await request.body()
    if not data:
        raise http_error(400, "err.image_missing")
    if len(data) > _PASTE_MAX_BYTES:
        raise http_error(
            413, "err.image_too_large", mb=_PASTE_MAX_BYTES // (1024 * 1024)
        )

    _PASTE_DIR.mkdir(parents=True, exist_ok=True)
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
    target.write_bytes(data)

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


@app.get("/api/sessions", response_model=list[SessionInfo])
def get_sessions(user: str = _auth) -> list[SessionInfo]:
    """Devuelve el catálogo de sesiones de tmux y el espacio de cada una."""
    try:
        sessions = list_sessions()
    except TmuxError as exc:
        raise http_from(500, exc) from exc

    by_name = space_store.assignments()
    return [
        SessionInfo(
            name=s.name,
            windows=s.windows,
            attached=s.attached,
            created=s.created,
            space=by_name.get(s.name),
        )
        for s in sessions
    ]


@app.post("/api/create-session/{name}", response_model=CreateSessionResponse)
def create_session_endpoint(
    name: str,
    body: CreateSessionBody = Body(default_factory=CreateSessionBody),
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
    return CreateSessionResponse(name=name, created=True)


@app.post("/api/kill-session/{name}", response_model=KillSessionResponse)
def kill_session_endpoint(name: str, user: str = _auth) -> KillSessionResponse:
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
    return MessageResponse(message="ok")


@app.post("/api/rename-session/{name}", response_model=MessageResponse)
def rename_session_endpoint(
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
    return MessageResponse(message="ok")


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
@app.get("/api/projects", response_model=list[ProjectInfo])
def get_projects(user: str = _auth) -> list[ProjectInfo]:
    """Devuelve todos los proyectos guardados en la biblioteca."""
    return [ProjectInfo(**p.to_dict()) for p in list_projects()]


@app.post("/api/projects", response_model=ProjectInfo, status_code=201)
def create_project(
    body: ProjectCreateBody,
    user: str = _auth,
) -> ProjectInfo:
    """Crea un proyecto nuevo en la biblioteca."""
    # El título se usa como nombre de la sesión al ejecutar el proyecto, así
    # que normalizamos las barras aquí también (ver `_slug_session_name`).
    title = _slug_session_name(body.title)
    try:
        created = add_project(title, body.cwd, body.commands)
    except LibraryError as exc:
        raise http_from(400, exc) from exc
    return ProjectInfo(**created.to_dict())


@app.put("/api/projects/{project_id}", response_model=ProjectInfo)
def update_project_endpoint(
    project_id: str,
    body: ProjectUpdateBody,
    user: str = _auth,
) -> ProjectInfo:
    """Actualiza un proyecto existente."""
    title = _slug_session_name(body.title)
    try:
        updated = update_project(project_id, title, body.cwd, body.commands)
    except LibraryError as exc:
        raise http_from(400, exc) from exc
    if updated is None:
        raise http_error(404, "err.project_not_found")
    return ProjectInfo(**updated.to_dict())


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
if _FRONTEND_DIST.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(_FRONTEND_DIST), html=True),
        name="frontend",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=False)
