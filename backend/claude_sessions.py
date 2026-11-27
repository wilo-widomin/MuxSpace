"""Cliente del API de sesiones de Claude Code (project-dashboard).

Willy busca aquí en sus conversaciones pasadas, las lee y las retoma. Las
transcripciones **pueden llevar contraseñas y claves** pegadas en mitad de una
charla, así que este módulo cumple unas reglas que no se negocian:

- **Se consulta al momento y se tira.** Nada se guarda en disco, en caché ni en
  `backend/data/`. No hay estado de proceso salvo la configuración.
- **No se registra lo buscado.** Ni la consulta, ni la respuesta, ni el texto
  de un error del API (puede repetir lo buscado): los logs llevan solo el
  nombre de la operación y el tipo de fallo.
- **Solo habla el servidor.** El navegador nunca llega al API; los errores se
  traducen a claves i18n y el 503 («sesiones apagadas») se devuelve tal cual,
  mensaje y comando incluidos, **sin intentar encenderlas**.
- **No sale ninguna ruta de archivo en disco.** Cada respuesta se reconstruye
  campo a campo con una lista blanca; lo que el API añada mañana no pasa.

El API filtra `project` por subcadena de la ruta (`mvp-lab` casa también con
`mvp-lab-analisis`), así que el filtro fino se repite aquí con `en_proyecto`.

Son funciones sin estado. El HTTP va con `urllib` (stdlib), sin proxies: es una
llamada a la propia máquina.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import socket
import urllib.error
import urllib.parse
import urllib.request

import config
import logs
from errors import AppError

_log = logs.obtener(__name__)

# Plazos cortos: una petición colgada ocuparía un hilo del servidor. La
# búsqueda con regex puede tardar más en el API (tiene un tope de 20 s allí).
TIMEOUT_S = 8.0
TIMEOUT_BUSQUEDA_S = 15.0

# Tope de lo que se lee de una respuesta: una exportación de una sesión de
# 40 MB cabe, pero un API desbocado no puede llenar la memoria.
_MAX_BYTES = 64 * 1024 * 1024
_MAX_BYTES_ERROR = 64 * 1024

# Id de sesión de Claude Code: un UUID. Para leer o exportar se admite también
# un prefijo hexadecimal (el API lo resuelve y avisa si es ambiguo); para
# retomar se exige el UUID entero, porque acaba dentro de un comando de shell.
_ID_O_PREFIJO = re.compile(r"^[0-9a-fA-F][0-9a-fA-F-]{3,35}$")
_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ROLES = ("user", "assistant")
TIPOS = ("text", "thinking", "tool_use", "tool_result")
ORDENES = ("date", "relevance")

_MAX_CONSULTA = 500
_MAX_LISTA = 200
_MAX_BUSQUEDA = 100
_MAX_PAGINA = 200


class SessionsError(AppError):
    """Fallo al hablar con el API de sesiones, ya con su código y estado HTTP.

    `extra` lleva lo que el cliente necesita además del código: en el 503, el
    mensaje y el comando del API tal cual; en el 409, las coincidencias.
    """

    def __init__(self, status: int, code: str, extra: dict | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.extra = extra or {}

    @property
    def detail(self) -> dict:
        return {"code": self.code, **self.extra}


# ----------------------------------------------------------------------
# Validación (funciones puras)
# ----------------------------------------------------------------------
def id_valido(session_id: str) -> bool:
    """¿Es un id o prefijo de sesión admisible para leer o exportar?"""
    return bool(_ID_O_PREFIJO.match(session_id or ""))


def uuid_valido(session_id: str) -> bool:
    """¿Es un UUID entero? Es lo único que se admite para retomar."""
    return bool(_UUID.match(session_id or ""))


def en_proyecto(ruta: str | None, cwd_proyecto: str) -> bool:
    """¿Cuelga `ruta` del proyecto `cwd_proyecto`? Igual o hija por `/`.

    El filtro `project` del API busca la cadena dentro de la ruta, y eso casa
    `/a/mvp-lab` con `/a/mvp-lab-analisis`. Aquí se compara por tramos de
    ruta. Los worktrees (`<proyecto>/.claude/worktrees/…`) son hijos del
    proyecto y entran por la misma regla. No se resuelven enlaces simbólicos:
    se comparan las rutas tal como las guardó cada lado.
    """
    if not ruta or not cwd_proyecto:
        return False
    base = os.path.normpath(os.path.expanduser(cwd_proyecto))
    candidata = os.path.normpath(ruta)
    return candidata == base or candidata.startswith(base.rstrip("/") + "/")


# ----------------------------------------------------------------------
# Secretos en los fragmentos
# ----------------------------------------------------------------------
# Un fragmento de búsqueda llega a la pantalla aunque nadie haya abierto la
# conversación: lo que parezca una clave se esconde y se enseña con un «mostrar»
# por trozo. Es solo ofuscación a la vista (el trozo viaja igualmente, Willy es
# el único lector); no sustituye a no guardar nada.
_PATRONES_SECRETO = [
    # Claves con prefijo conocido.
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}"),
    # JWT: tres tramos en base64url, el primero empieza por `eyJ`.
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
]
# `contraseña: valor`, `password=valor`, `token: valor`… El secreto es el
# valor (grupo 1), no la etiqueta. Admite comillas.
_VALOR_ETIQUETADO = re.compile(
    r"(?i)\b(?:password|passwd|pwd|pass|contrase(?:ñ|n)a|clave|secret(?:o)?|"
    r"token|api[_-]?key|apikey)\b[\"']?\s*[:=]\s*[\"']?([^\s\"',;»]{3,})"
)
# Cadena larga de aspecto aleatorio: 32 o más caracteres con letras y cifras.
_TOKEN_LARGO = re.compile(r"[A-Za-z0-9_+/=-]{32,}")


def _parece_aleatorio(texto: str) -> bool:
    """Letras y cifras mezcladas y no un UUID ni una ruta: probable token."""
    if _UUID.match(texto):
        return False
    if texto.count("/") > 1 or texto.count("-") > 3:
        return False
    return any(c.isdigit() for c in texto) and any(c.isalpha() for c in texto)


def _tramos_secretos(plano: str) -> list[tuple[int, int]]:
    tramos: list[tuple[int, int]] = []
    for patron in _PATRONES_SECRETO:
        tramos += [m.span() for m in patron.finditer(plano)]
    tramos += [m.span(1) for m in _VALOR_ETIQUETADO.finditer(plano)]
    for m in _TOKEN_LARGO.finditer(plano):
        if _parece_aleatorio(m.group()):
            tramos.append(m.span())
    return tramos


def trocear_fragmento(snippet: str) -> list[dict]:
    """Parte un fragmento del API en trozos `{text, mark, secret}`.

    `mark` dice si el trozo estaba entre « y » (lo encontrado) y `secret` si
    parece una clave. Se decide aquí, sobre el texto, para que el cliente no
    tenga que interpretar nada: pinta cada trozo como texto y listo. Un
    secreto que cruce el límite de una marca se parte en dos trozos, ambos
    secretos. El texto sin marcas ni secretos sale en un solo trozo.
    """
    texto = snippet if isinstance(snippet, str) else ""
    plano: list[str] = []
    marcado: list[bool] = []
    dentro = False
    for caracter in texto:
        if caracter == "«":
            dentro = True
        elif caracter == "»":
            dentro = False
        else:
            plano.append(caracter)
            marcado.append(dentro)
    cadena = "".join(plano)
    secreto = [False] * len(cadena)
    for inicio, fin in _tramos_secretos(cadena):
        for i in range(inicio, fin):
            secreto[i] = True

    trozos: list[dict] = []
    for i, caracter in enumerate(cadena):
        ultimo = trozos[-1] if trozos else None
        if ultimo and ultimo["mark"] == marcado[i] and ultimo["secret"] == secreto[i]:
            ultimo["text"] += caracter
        else:
            trozos.append({"text": caracter, "mark": marcado[i], "secret": secreto[i]})
    return trozos


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------
# Sin proxies del entorno: es la propia máquina, y un `http_proxy` exportado
# mandaría las conversaciones por donde no toca.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _leer_cuerpo(respuesta, tope: int) -> bytes:
    cuerpo = respuesta.read(tope + 1)
    if len(cuerpo) > tope:
        raise SessionsError(502, "err.claude_sessions_upstream")
    return cuerpo


def _error_http(exc: urllib.error.HTTPError) -> SessionsError:
    """Traduce un estado de error del API a un código i18n.

    El texto del error del API **no** se reenvía salvo en el 503: en un 400 de
    regex puede repetir lo buscado.
    """
    try:
        cuerpo = json.loads(exc.read(_MAX_BYTES_ERROR).decode("utf-8", "replace"))
    except (ValueError, OSError):
        cuerpo = {}
    if not isinstance(cuerpo, dict):
        cuerpo = {}
    if exc.code == 503:
        # Tal cual: el mensaje y el comando para encenderlas los pone el API.
        # Aquí no se enciende nada.
        return SessionsError(
            503,
            "err.claude_sessions_disabled",
            {
                "mensaje": str(cuerpo.get("error") or ""),
                "detail": str(cuerpo.get("detail") or ""),
            },
        )
    if exc.code == 404:
        return SessionsError(404, "err.claude_session_not_found")
    if exc.code == 409:
        coincidencias = [
            {"id": str(m.get("id", "")), "title": str(m.get("title", ""))}
            for m in cuerpo.get("matches", [])
            if isinstance(m, dict)
        ][:20]
        return SessionsError(
            409, "err.claude_session_ambiguous", {"matches": coincidencias}
        )
    if exc.code == 400:
        return SessionsError(400, "err.claude_sessions_bad_request")
    return SessionsError(502, "err.claude_sessions_upstream")


def _pedir(operacion: str, ruta: str, consulta: dict | None = None,
           timeout: float | None = None, tope: int = _MAX_BYTES) -> bytes:
    """GET al API. `operacion` es lo único que se escribe en el log."""
    url = config.CLAUDE_SESSIONS_URL + ruta
    if consulta:
        url += "?" + urllib.parse.urlencode(consulta)
    try:
        with _opener.open(url, timeout=timeout or TIMEOUT_S) as respuesta:
            return _leer_cuerpo(respuesta, tope)
    except urllib.error.HTTPError as exc:
        error = _error_http(exc)
        _log.warning("sesiones de Claude: %s -> %s", operacion, exc.code)
        raise error from None
    except (TimeoutError, socket.timeout):
        _log.warning("sesiones de Claude: %s -> tiempo agotado", operacion)
        raise SessionsError(504, "err.claude_sessions_timeout") from None
    except urllib.error.URLError as exc:
        # Un timeout de conexión llega envuelto en URLError.
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            _log.warning("sesiones de Claude: %s -> tiempo agotado", operacion)
            raise SessionsError(504, "err.claude_sessions_timeout") from None
        _log.warning("sesiones de Claude: %s -> API caído", operacion)
        raise SessionsError(502, "err.claude_sessions_down") from None
    except OSError:
        _log.warning("sesiones de Claude: %s -> API caído", operacion)
        raise SessionsError(502, "err.claude_sessions_down") from None


def _json(operacion: str, ruta: str, consulta: dict | None = None,
          timeout: float | None = None) -> dict:
    cuerpo = _pedir(operacion, ruta, consulta, timeout)
    try:
        datos = json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        _log.warning("sesiones de Claude: %s -> respuesta ilegible", operacion)
        raise SessionsError(502, "err.claude_sessions_upstream") from None
    if not isinstance(datos, dict):
        raise SessionsError(502, "err.claude_sessions_upstream")
    return datos


# ----------------------------------------------------------------------
# Reconstrucción con lista blanca
# ----------------------------------------------------------------------
def _sesion_publica(fila: dict) -> dict:
    """Una sesión del API, solo con lo que la pantalla necesita.

    Quedan fuera `cwd` y `size`: la pantalla no los usa, y la carpeta solo la
    necesita el servidor para retomar.
    """
    return {
        "id": str(fila.get("id", "")),
        "project": str(fila.get("project") or ""),
        "branch": str(fila.get("branch") or ""),
        "first_ts": str(fila.get("first_ts") or ""),
        "last_ts": str(fila.get("last_ts") or ""),
        "n_messages": int(fila.get("n_messages") or 0),
        "title": str(fila.get("title") or ""),
        "title_kind": str(fila.get("title_kind") or ""),
        "has_compact": bool(fila.get("has_compact")),
        "empty": bool(fila.get("empty")),
        "n_subagent": int(fila.get("n_subagent") or 0),
    }


def _acierto_publico(fila: dict) -> dict:
    return {
        "session_id": str(fila.get("session_id", "")),
        "project": str(fila.get("project") or ""),
        "title": str(fila.get("title") or ""),
        "role": str(fila.get("role") or ""),
        "kind": str(fila.get("kind") or ""),
        "ts": str(fila.get("ts") or ""),
        "agent_id": str(fila.get("agent_id") or ""),
        "segments": trocear_fragmento(fila.get("snippet") or ""),
    }


def _mensaje_publico(fila: dict) -> dict:
    return {
        "role": str(fila.get("role") or ""),
        "ts": str(fila.get("ts") or ""),
        "agent": str(fila.get("agent") or ""),
        "blocks": [
            {
                "kind": str(b.get("kind") or ""),
                "text": str(b.get("text") or ""),
                "error": bool(b.get("error")),
            }
            for b in fila.get("blocks", [])
            if isinstance(b, dict)
        ],
    }


def _entero(valor, por_defecto: int, tope: int) -> int:
    try:
        return max(0, min(int(valor), tope))
    except (TypeError, ValueError):
        return por_defecto


def _filtros_comunes(since: str | None, project_cwd: str | None) -> dict:
    consulta: dict = {}
    if since:
        if not _FECHA.match(since):
            raise SessionsError(400, "err.claude_sessions_bad_request")
        consulta["since"] = since
    if project_cwd:
        # Pre-filtro del API (subcadena); el filtro fino se repite abajo.
        consulta["project"] = os.path.normpath(os.path.expanduser(project_cwd))
    return consulta


# ----------------------------------------------------------------------
# Operaciones
# ----------------------------------------------------------------------
def listar(project_cwd: str | None = None, since: str | None = None,
           limit: int = 100) -> list[dict]:
    """Sesiones por última actividad, acotadas a la carpeta de un proyecto."""
    limit = _entero(limit, 100, _MAX_LISTA) or 100
    consulta = _filtros_comunes(since, project_cwd)
    # Con filtro de proyecto se pide de más: el API corta por `limit` antes de
    # que aquí se descarten las de carpetas que solo comparten prefijo.
    consulta["limit"] = min(limit * 5, 2000) if project_cwd else limit
    datos = _json("listar", "/sessions", consulta)
    filas = [f for f in datos.get("sessions", []) if isinstance(f, dict)]
    if project_cwd:
        filas = [
            f for f in filas
            if en_proyecto(f.get("cwd") or f.get("project"), project_cwd)
        ]
    return [_sesion_publica(f) for f in filas[:limit]]


def buscar(
    query: str,
    *,
    project_cwd: str | None = None,
    role: str = "",
    regex: bool = False,
    kinds: list[str] | None = None,
    subagents: bool = False,
    sort: str = "date",
    since: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Búsqueda en las conversaciones. **Nunca registra `query`.**"""
    query = (query or "").strip()
    if not query or len(query) > _MAX_CONSULTA:
        raise SessionsError(400, "err.claude_sessions_query_invalid")
    if role and role not in ROLES:
        raise SessionsError(400, "err.claude_sessions_bad_request")
    if sort not in ORDENES:
        raise SessionsError(400, "err.claude_sessions_bad_request")
    tipos = [k for k in (kinds or ["text"]) if k in TIPOS] or ["text"]
    limit = _entero(limit, 50, _MAX_BUSQUEDA) or 50

    consulta = _filtros_comunes(since, project_cwd)
    consulta.update(
        q=query,
        kinds=",".join(tipos),
        sort=sort,
        limit=min(limit * 3, 500) if project_cwd else limit,
    )
    if role:
        consulta["role"] = role
    if regex:
        consulta["regex"] = "1"
    if subagents:
        consulta["subagents"] = "1"
    datos = _json("buscar", "/sessions/search", consulta, TIMEOUT_BUSQUEDA_S)
    filas = [f for f in datos.get("hits", []) if isinstance(f, dict)]
    if project_cwd:
        filas = [f for f in filas if en_proyecto(f.get("project"), project_cwd)]
    return [_acierto_publico(f) for f in filas[:limit]]


def leer(session_id: str, *, offset: int = 0, limit: int = 50,
         thinking: bool = False, tools: bool = False,
         subagents: bool = False) -> dict:
    """Una página de la conversación. Admite id completo o prefijo."""
    if not id_valido(session_id):
        raise SessionsError(400, "err.claude_session_id_invalid")
    consulta = {
        "offset": _entero(offset, 0, 10**7),
        "limit": _entero(limit, 50, _MAX_PAGINA) or 50,
    }
    for nombre, valor in (("thinking", thinking), ("tools", tools),
                          ("subagents", subagents)):
        if valor:
            consulta[nombre] = "1"
    datos = _json("leer", f"/sessions/{session_id}", consulta)
    return {
        "session": _sesion_publica(datos.get("session") or {}),
        "messages": [
            _mensaje_publico(m) for m in datos.get("messages", [])
            if isinstance(m, dict)
        ],
        "offset": _entero(datos.get("offset"), 0, 10**9),
        "truncated": bool(datos.get("truncated")),
    }


def exportar(session_id: str) -> tuple[str, str]:
    """Markdown de la sesión y un nombre de archivo para la descarga."""
    if not id_valido(session_id):
        raise SessionsError(400, "err.claude_session_id_invalid")
    cuerpo = _pedir("exportar", f"/sessions/{session_id}/export")
    try:
        texto = cuerpo.decode("utf-8")
    except UnicodeDecodeError:
        raise SessionsError(502, "err.claude_sessions_upstream") from None
    return texto, f"{session_id[:8]}.md"


def destino_de_retomar(session_id: str) -> dict:
    """Carpeta y comando para retomar. `{cwd, exists, command}`.

    El comando del API es shell (`cd … && claude --resume …`); aquí se rehace
    a partir de la carpeta y del id, que se valida entero, para que lo que se
    ejecute en una terminal nunca sea texto del API sin revisar. Con el UUID
    entero y la carpeta citada con `shlex.quote`, no hay nada que inyectar.
    """
    if not id_valido(session_id):
        raise SessionsError(400, "err.claude_session_id_invalid")
    datos = _json("retomar", f"/sessions/{session_id}/resume")
    cwd = str(datos.get("cwd") or "")
    existe = (
        bool(datos.get("exists"))
        and os.path.isabs(cwd)
        and not re.search(r"[\x00-\x1f\x7f]", cwd)
        and os.path.isdir(cwd)
    )
    # El API resuelve prefijos; para ejecutar hace falta el UUID entero, que
    # se saca del propio comando que devuelve (`claude --resume <uuid>`).
    comando_api = str(datos.get("command") or "")
    completo = re.search(r"--resume ([0-9a-fA-F-]{36})\s*$", comando_api)
    uuid = completo.group(1) if completo and uuid_valido(completo.group(1)) else ""
    comando = (
        f"cd {shlex.quote(cwd)} && claude --resume {uuid}" if existe and uuid else ""
    )
    return {"cwd": cwd if existe else "", "exists": existe and bool(uuid),
            "command": comando, "session_id": uuid}
