"""Autenticación del panel: login con sesión de servidor (cookie HttpOnly).

El frontend hace `POST /api/login` con usuario y contraseña; si son válidos
se emite un token de sesión aleatorio que viaja en una cookie `HttpOnly` +
`SameSite=Lax`. A partir de ahí ni la API ni el WebSocket del terminal
necesitan credenciales explícitas: el navegador adjunta la cookie solo.

Ventajas frente al esquema anterior (HTTP Basic + token en query string):
  - La contraseña no se retiene en el cliente (antes: localStorage en claro).
  - El WebSocket no lleva credenciales en la URL (antes quedaban en logs de
    acceso, historial y proxies).
  - `SameSite=Lax` corta el CSRF: otros sitios no pueden disparar POSTs ni
    abrir el WebSocket con la cookie del usuario.

Se mantiene HTTP Basic como alternativa para clientes no-navegador
(curl, scripts): `curl -u user:pass http://.../api/sessions`.

Las sesiones viven en memoria: un reinicio del backend obliga a volver a
iniciar sesión (aceptable para un panel personal). Los intentos fallidos de
login, en cambio, persisten en `data/login_failures.json` para que un
atacante no resetee el rate limit tirando/esperando un reinicio del backend,
y para conservar un histórico de IPs atacantes consultable a posteriori.

**Un solo worker.** Aquí el problema no es solo el `threading.Lock` (que
protege entre hilos, no entre procesos): las sesiones viven en un diccionario
**en memoria**, y la memoria no se comparte entre workers. Con dos workers,
quien hace login contra el worker A recibe un 401 en la siguiente petición si
el balanceo la manda al B, porque el B no conoce ese token. El rate limit de
login se rompe de la misma forma: cada worker cuenta sus propios fallos, así
que con N workers salen N veces los intentos permitidos. Por eso el panel
arranca con `--workers 1` y `main.py` avisa si detecta más. Ver
`docs/un-solo-worker.md`.
"""
from __future__ import annotations

import ipaddress
import json
import os
import pwd
import secrets
import threading
import time
from pathlib import Path

from fastapi import HTTPException, Request, WebSocket, status

from config import (
    AUTH_ENABLED,
    AUTH_MODE,
    AUTH_PASSWORD,
    AUTH_USERNAME,
    PAM_SERVICE,
    SESSION_TTL_HOURS,
)
from datafiles import write_private
from errors import error_detail, http_error

# Nombre de la cookie de sesión que emite /api/login.
SESSION_COOKIE = "muxspace_session"

# token -> (username, expira_epoch). Protegido por lock porque los endpoints
# síncronos de FastAPI corren en un threadpool.
_sessions: dict[str, tuple[str, float]] = {}
_sessions_lock = threading.Lock()

# Anti fuerza bruta del login: ip -> registro con la ventana de rate limit
# actual (count/window_start) y el histórico acumulado del atacante
# (total_failures/first_seen/last_seen), persistido en disco.
_LOGIN_WINDOW_SECONDS = 60
_LOGIN_MAX_FAILURES = 5
# Tope de IPs registradas: al superarlo se descartan las de actividad más
# antigua, para que una botnet no infle el archivo sin límite.
_MAX_TRACKED_IPS = 1000
_FAILURES_PATH = Path(__file__).resolve().parent / "data" / "login_failures.json"
_login_lock = threading.Lock()


def _load_login_failures() -> dict[str, dict]:
    """Lee el JSON de disco. Ausente o corrupto => registro vacío."""
    if not _FAILURES_PATH.is_file():
        return {}
    try:
        data = json.loads(_FAILURES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {ip: rec for ip, rec in data.items() if isinstance(rec, dict)}


_login_failures: dict[str, dict] = _load_login_failures()


def _persist_login_failures_locked() -> None:
    """Vuelca el registro a disco (llamar con `_login_lock` cogido).

    Escritura atómica (tmp + replace) para no dejar un JSON a medias si el
    proceso muere durante el volcado.
    """
    if len(_login_failures) > _MAX_TRACKED_IPS:
        by_age = sorted(
            _login_failures, key=lambda ip: _login_failures[ip].get("last_seen", 0)
        )
        for ip in by_age[: len(_login_failures) - _MAX_TRACKED_IPS]:
            del _login_failures[ip]
    write_private(
        _FAILURES_PATH, json.dumps(_login_failures, ensure_ascii=False, indent=2)
    )


def _compare(a: str, b: str) -> bool:
    """compare_digest sobre bytes: constante en tiempo y sin el TypeError
    que lanza la variante str si algún lado contiene no-ASCII."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _backend_user() -> str:
    """Usuario del sistema que ejecuta el backend (por UID, no por $USER)."""
    return pwd.getpwuid(os.getuid()).pw_name


def _pam_verify(username: str, password: str) -> bool:
    """Valida contra el sistema (PAM), solo para el usuario del backend.

    Sin privilegios de root, el helper de PAM (`unix_chkpwd`) únicamente
    permite verificar la contraseña del usuario que ejecuta el proceso —
    que es justo el dueño de las sesiones de tmux que sirve el panel, así
    que nadie más debe poder entrar de todos modos.
    """
    if not username or not password:
        return False
    if not _compare(username, _backend_user()):
        return False
    import pam  # import diferido: solo hace falta en modo pam

    return bool(pam.pam().authenticate(username, password, service=PAM_SERVICE))


def verify_credentials(username: str, password: str) -> bool:
    """Valida usuario y contraseña según el modo configurado (env | pam)."""
    if AUTH_MODE == "pam":
        return _pam_verify(username or "", password or "")
    ok_user = _compare(username or "", AUTH_USERNAME)
    ok_pass = _compare(password or "", AUTH_PASSWORD)
    return ok_user and ok_pass


# ----------------------------------------------------------------------
# Sesiones (token aleatorio en cookie HttpOnly)
# ----------------------------------------------------------------------
def create_session(username: str) -> str:
    """Crea una sesión nueva y devuelve su token (valor de la cookie)."""
    token = secrets.token_urlsafe(32)
    expires = time.time() + SESSION_TTL_HOURS * 3600
    with _sessions_lock:
        _purge_expired_locked()
        _sessions[token] = (username, expires)
    return token


def destroy_session(token: str | None) -> None:
    """Invalida el token de sesión (logout)."""
    if not token:
        return
    with _sessions_lock:
        _sessions.pop(token, None)


def session_user(token: str | None) -> str | None:
    """Usuario de la sesión, o None si el token no existe o expiró."""
    if not token:
        return None
    now = time.time()
    with _sessions_lock:
        entry = _sessions.get(token)
        if entry is None:
            return None
        username, expires = entry
        if expires < now:
            del _sessions[token]
            return None
        return username


def _purge_expired_locked() -> None:
    now = time.time()
    expired = [t for t, (_, exp) in _sessions.items() if exp < now]
    for t in expired:
        del _sessions[t]


# ----------------------------------------------------------------------
# Límite de intentos de login por IP
# ----------------------------------------------------------------------
def check_login_allowed(ip: str) -> bool:
    """False si la IP agotó los intentos de la ventana actual."""
    now = time.time()
    with _login_lock:
        rec = _login_failures.get(ip)
        if rec is None:
            return True
        if now - rec.get("window_start", 0.0) > _LOGIN_WINDOW_SECONDS:
            return True
        return rec.get("count", 0) < _LOGIN_MAX_FAILURES


def register_login_failure(ip: str) -> None:
    now = time.time()
    with _login_lock:
        rec = _login_failures.setdefault(
            ip,
            {"count": 0, "window_start": now, "total_failures": 0, "first_seen": now},
        )
        if now - rec.get("window_start", 0.0) > _LOGIN_WINDOW_SECONDS:
            rec["count"] = 0
            rec["window_start"] = now
        rec["count"] = rec.get("count", 0) + 1
        rec["total_failures"] = rec.get("total_failures", 0) + 1
        rec["last_seen"] = now
        _persist_login_failures_locked()


def clear_login_failures(ip: str) -> None:
    """Resetea la ventana de la IP tras un login correcto.

    Se conserva el histórico (total_failures/first_seen/last_seen): que el
    dueño acierte la contraseña no borra el rastro de intentos previos.
    """
    with _login_lock:
        rec = _login_failures.get(ip)
        if rec is None or rec.get("count", 0) == 0:
            return
        rec["count"] = 0
        _persist_login_failures_locked()


# ----------------------------------------------------------------------
# Lista negra de IPs (data/banned_ips.json)
# ----------------------------------------------------------------------
# Array JSON de IPs o rangos CIDR con el acceso prohibido a todo el panel
# (HTTP y WebSocket), p. ej.: ["203.0.113.7", "198.51.100.0/24"].
# Se recarga en caliente al detectar que cambió el mtime del archivo, así
# que se puede banear una IP editándolo sin reiniciar el backend.
_BANNED_PATH = Path(__file__).resolve().parent / "data" / "banned_ips.json"
_banned_lock = threading.Lock()
_banned_mtime: float = -1.0
_banned_networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []


def _reload_banned_locked() -> None:
    global _banned_mtime, _banned_networks
    try:
        mtime = _BANNED_PATH.stat().st_mtime
    except OSError:  # el archivo no existe: nada baneado
        _banned_mtime = -1.0
        _banned_networks = []
        return
    if mtime == _banned_mtime:
        return
    try:
        data = json.loads(_BANNED_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return  # JSON a medio editar/corrupto: conservar la lista anterior
    networks = []
    for entry in data if isinstance(data, list) else []:
        try:
            # strict=False admite "1.2.3.4/24" con bits de host puestos;
            # una IP suelta se interpreta como red /32 (o /128 en IPv6).
            networks.append(ipaddress.ip_network(str(entry).strip(), strict=False))
        except ValueError:
            continue  # entrada malformada: se ignora, no tumba la lista
    _banned_mtime = mtime
    _banned_networks = networks


def is_ip_banned(ip: str) -> bool:
    """True si la IP cae en alguna entrada de data/banned_ips.json."""
    with _banned_lock:
        _reload_banned_locked()
        if not _banned_networks:
            return False
        networks = list(_banned_networks)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


# ----------------------------------------------------------------------
# Dependencia de autenticación para los endpoints HTTP
# ----------------------------------------------------------------------
def _basic_user(request: Request) -> str | None:
    """Valida una cabecera `Authorization: Basic` si viene (curl/scripts).

    Pasa por el mismo rate limit por IP que /api/login: sin esto, esta ruta
    permitiría fuerza bruta ilimitada contra cualquier endpoint autenticado.
    Solo cuenta como fallo si la cabecera Basic viene y es incorrecta (una
    petición sin credenciales no penaliza).
    """
    header = request.headers.get("authorization", "")
    scheme, _, payload = header.partition(" ")
    if scheme.lower() != "basic" or not payload:
        return None
    ip = request.client.host if request.client else "?"
    if not check_login_allowed(ip):
        raise http_error(
            status.HTTP_429_TOO_MANY_REQUESTS, "err.login_rate_limited"
        )
    import base64

    try:
        raw = base64.b64decode(payload).decode("utf-8")
    except Exception:
        register_login_failure(ip)
        return None
    user, sep, pw = raw.partition(":")
    if sep and verify_credentials(user, pw):
        clear_login_failures(ip)
        return user
    register_login_failure(ip)
    return None


def require_auth(request: Request) -> str:
    """Dependencia FastAPI: sesión por cookie o, en su defecto, HTTP Basic.

    No enviamos `WWW-Authenticate` en el 401 para que el navegador no
    superponga su diálogo nativo al login propio del frontend.
    """
    if not AUTH_ENABLED:
        return "anonymous"

    user = session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        user = _basic_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_detail("err.unauthenticated"),
        )
    return user


def ws_user(websocket: WebSocket) -> str | None:
    """Autenticación del WebSocket del terminal vía cookie de sesión.

    El navegador adjunta las cookies en el handshake, así que no hace
    falta (ni se acepta) ningún token en la URL.
    """
    if not AUTH_ENABLED:
        return "anonymous"
    return session_user(websocket.cookies.get(SESSION_COOKIE))
