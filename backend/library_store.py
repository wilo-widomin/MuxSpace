"""Biblioteca reutilizable: Comandos, Textos rápidos y Proyectos.

- **Comando**: una sola línea de shell (sin directorio). Se envía a la
  terminal con foco, o se lanza en una sesión nueva si no hay foco.
- **Texto rápido** (`Snippet`): texto que se ESCRIBE en la terminal. Existe
  para lo que se teclea a menudo y no es un comando de shell —nombres de
  skills, órdenes a un agente— desde una tableta, donde escribir treinta
  caracteres exactos es el trabajo caro. Cada uno decide con `submit` si
  además se envía (Enter) o se queda en el prompt para seguir escribiendo.
- **Proyecto**: un título, un directorio (cwd) y una lista de comandos que
  se ejecutan secuencialmente en una sesión nueva. Puede llevar además una
  lista de **enlaces** (URL + título) que el panel pinta como badges en la
  cabecera de las terminales de ese proyecto.

El mismo JSON guarda qué sesión de tmux salió de qué proyecto
(`session_projects`), que es lo que permite saber qué enlaces tocan en cada
terminal.

Ambos se persisten en un único JSON (`data/library.json`) para que la
biblioteca sobreviva a reinicios del backend. El almacenamiento es
deliberadamente simple (un archivo JSON plano) y no mantiene estado en
memoria más allá de la caché de lectura: cada mutación recarga y reescribe
el archivo completo. Suficiente para un dashboard de uso personal.

**Un solo worker.** El `Lock` de abajo es un `threading.Lock`: protege entre
hilos, no entre procesos. Como cada mutación reescribe `library.json`
**entero** (read-modify-write), dos workers de uvicorn que guarden a la vez
producen la pérdida silenciosa de lo que escribió el otro: el segundo
sobreescribe con la copia que leyó antes. Por eso el panel arranca con
`--workers 1` y `main.py` avisa si detecta más. Ver `docs/un-solo-worker.md`.
"""
from __future__ import annotations

import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional
from urllib.parse import urlparse

from datafiles import write_private
from errors import AppError

# Archivo de persistencia junto al resto del backend.
_STORE_PATH = Path(__file__).resolve().parent / "data" / "library.json"

_lock = Lock()

# Límites de los enlaces de un proyecto. No hay razón técnica para estos
# números: son los que hacen que la fila de badges de la cabecera siga
# siendo legible en un tile estrecho.
_MAX_LINKS = 12
_MAX_LINK_TITLE = 40

# Un texto rápido es un atajo de teclado, no un documento: para pegar algo
# largo está el redactor de la terminal, que además guarda borrador.
_MAX_SNIPPET_TEXT = 2000

# Únicos esquemas admitidos. El enlace acaba en un `<a href>` del panel, así
# que `javascript:` y `data:` son ejecución de código en la página: no basta
# con que el navegador los ignore, no deben poder guardarse.
_ALLOWED_SCHEMES = ("http", "https")

# `esquema:` al principio de la cadena, tal como lo define el RFC 3986.
_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


class LibraryError(AppError):
    """Error de validación o de persistencia de la biblioteca."""


@dataclass
class Command:
    """Un comando de una sola línea guardado en la biblioteca."""
    id: str
    label: str
    command: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Snippet:
    """Un texto rápido: lo que se escribe en la terminal.

    `submit` decide qué pasa después de escribirlo: `True` manda Enter —el
    texto es la orden entera y no hay nada que añadir—, `False` lo deja en el
    prompt para seguir escribiendo, que es el caso de un prefijo como
    `/code-review ` al que le falta el argumento.
    """
    id: str
    label: str
    text: str
    submit: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Link:
    """Un enlace del proyecto: la URL y el texto que se ve en la badge."""
    url: str
    title: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Project:
    """Un proyecto: directorio + secuencia de comandos + enlaces."""
    id: str
    title: str
    cwd: Optional[str] = None
    commands: list[str] = field(default_factory=list)
    # Enlaces asociados (repositorio, panel de despliegue, documentación...).
    # Se pintan como badges en la cabecera de la terminal del proyecto.
    links: list[Link] = field(default_factory=list)
    # Espacio al que van las sesiones de este proyecto. Es el `id` de un
    # espacio de `space_store`; `None` = sin espacio. La biblioteca NO valida
    # que exista: quien lo comprueba es la capa HTTP, que sí ve los dos
    # almacenes (ver `_project_info` en `main.py`).
    space: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class _Library:
    """Snapshot de la biblioteca leída de disco."""

    def __init__(self) -> None:
        self.commands: list[Command] = []
        self.snippets: list[Snippet] = []
        self.projects: list[Project] = []
        # `nombre de sesión -> id de proyecto`. Vive aquí y no en el nombre
        # de la sesión porque el nombre se puede cambiar (`rename-session`)
        # y el título del proyecto también: casar por texto perdía el
        # vínculo en cuanto se tocaba cualquiera de los dos.
        self.session_projects: dict[str, str] = {}


def _load_raw() -> _Library:
    """Lee el JSON de disco. Ausente o corrupto => biblioteca vacía."""
    lib = _Library()
    if not _STORE_PATH.is_file():
        return lib
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    # `ValueError` y no `json.JSONDecodeError`: el archivo se serializa con
    # `ensure_ascii=False`, así que uno cortado en medio de un carácter
    # multibyte hace lanzar al `read_text` un `UnicodeDecodeError` — hermano
    # de `JSONDecodeError` bajo `ValueError`, y no subclase suya. Capturar
    # solo el segundo rompía el contrato "leer nunca lanza" (S15).
    except (ValueError, OSError):
        return lib
    if not isinstance(data, dict):
        return lib

    for item in data.get("commands") if isinstance(data.get("commands"), list) else []:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", "")).strip()
        if not command:
            continue
        lib.commands.append(
            Command(
                id=str(item.get("id", "")),
                label=str(item.get("label", "")).strip() or _default_label(command),
                command=command,
            )
        )

    raw_snippets = data.get("snippets")
    for item in raw_snippets if isinstance(raw_snippets, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        lib.snippets.append(
            Snippet(
                id=str(item.get("id", "")),
                label=str(item.get("label", "")).strip() or _default_label(text),
                text=text[:_MAX_SNIPPET_TEXT],
                # Los textos guardados antes de que esto existiera no llevan
                # la clave: no enviar es lo que hacían, y lo que se espera.
                submit=bool(item.get("submit", False)),
            )
        )

    for item in data.get("projects") if isinstance(data.get("projects"), list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        cmds = _normalize_commands(item.get("commands"))
        lib.projects.append(
            Project(
                id=str(item.get("id", "")),
                title=title,
                cwd=item.get("cwd") or None,
                commands=cmds,
                # Al LEER se descartan en silencio los enlaces inválidos, en
                # vez de rechazar el proyecto entero: leer nunca lanza.
                links=_normalize_links(item.get("links"), strict=False),
                space=str(item.get("space") or "").strip() or None,
            )
        )

    raw_links = data.get("session_projects")
    if isinstance(raw_links, dict):
        known = {p.id for p in lib.projects}
        for name, project_id in raw_links.items():
            # Un vínculo a un proyecto ya borrado no sirve para nada y se
            # limpia solo en la siguiente escritura.
            if isinstance(name, str) and project_id in known:
                lib.session_projects[name] = str(project_id)
    return lib


def _persist(lib: _Library) -> None:
    payload = {
        "commands": [c.to_dict() for c in lib.commands],
        "snippets": [s.to_dict() for s in lib.snippets],
        "projects": [p.to_dict() for p in lib.projects],
        "session_projects": lib.session_projects,
    }
    # `write_private` hace el tmp + replace y deja el fichero a 0600: son
    # los comandos que el panel ejecuta, no algo que deba poder leer
    # cualquier usuario local de la máquina.
    write_private(_STORE_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def _default_label(command: str) -> str:
    # Solo la primera línea: un texto rápido de varias líneas tiene que caber
    # en una fila de la lista, y lo que lo identifica es cómo empieza.
    primera = command.splitlines()[0] if command else ""
    return primera if len(primera) <= 60 else primera[:57] + "…"


def _normalize_commands(raw) -> list[str]:
    """Aplana/limpia una lista de comandos; descarta vacíos."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for entry in raw:
        text = str(entry).strip() if entry is not None else ""
        if text:
            out.append(text)
    return out


def _normalize_link(raw: dict) -> Optional[Link]:
    """Limpia un enlace suelto. Devuelve None si no hay URL utilizable."""
    url = str(raw.get("url", "")).strip()
    if not url:
        return None
    # Sin esquema se asume https: quien escribe "github.com/foo" quiere un
    # enlace, no una ruta relativa al propio panel (que es como lo leería
    # el navegador). Pero "javascript:alert(1)" SÍ trae esquema, y prefijarle
    # https:// lo convertía en una URL válida en vez de rechazarlo: por eso
    # se mira si hay `esquema:` antes de decidir.
    if "://" not in url:
        if _SCHEME_RE.match(url):
            raise LibraryError("err.project_link_invalid", {"url": url})
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.netloc:
        raise LibraryError("err.project_link_invalid", {"url": url})
    title = str(raw.get("title", "")).strip()
    # Sin título, el host: es lo que el usuario reconocería de un vistazo.
    if not title:
        title = parsed.netloc
    if len(title) > _MAX_LINK_TITLE:
        title = title[: _MAX_LINK_TITLE - 1] + "…"
    return Link(url=url, title=title)


def _normalize_links(raw, *, strict: bool = True) -> list[Link]:
    """Limpia una lista de enlaces; descarta los que no tienen URL.

    Con `strict=False` (lectura de disco) una URL inválida se descarta en
    silencio; con `strict=True` (lo que manda el usuario) se rechaza, para
    que quien escribe `javascript:...` en el modal se entere.
    """
    if not isinstance(raw, list):
        return []
    out: list[Link] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            link = _normalize_link(entry)
        except LibraryError:
            if strict:
                raise
            continue
        if link is not None:
            out.append(link)
    if strict and len(out) > _MAX_LINKS:
        raise LibraryError("err.project_too_many_links", {"max": _MAX_LINKS})
    return out[:_MAX_LINKS]


def _validate_command(label: str, command: str) -> tuple[str, str]:
    label = (label or "").strip()
    command = (command or "").strip()
    if not command:
        raise LibraryError("err.command_empty")
    if not label:
        label = _default_label(command)
    return label, command


def _validate_snippet(label: str, text: str) -> tuple[str, str]:
    label = (label or "").strip()
    text = (text or "").strip()
    if not text:
        raise LibraryError("err.snippet_empty")
    if len(text) > _MAX_SNIPPET_TEXT:
        raise LibraryError("err.snippet_too_long", {"max": _MAX_SNIPPET_TEXT})
    if not label:
        label = _default_label(text)
    return label, text


def _validate_project(
    title: str, cwd: Optional[str], commands: list[str], links=None, space=None
) -> tuple[str, Optional[str], list[str], list[Link], Optional[str]]:
    title = (title or "").strip()
    if not title:
        raise LibraryError("err.project_title_required")
    cwd = (cwd or "").strip() or None
    cmds = _normalize_commands(commands)
    if not cmds:
        raise LibraryError("err.project_needs_command")
    space_id = (str(space) if space is not None else "").strip() or None
    return title, cwd, cmds, _normalize_links(links), space_id


# ---------------------------------------------------------------------- #
# Comandos                                                                #
# ---------------------------------------------------------------------- #
def list_commands() -> list[Command]:
    """Devuelve todos los comandos guardados, en orden de inserción."""
    with _lock:
        return _load_raw().commands


def get_command(cmd_id: str) -> Optional[Command]:
    """Devuelve un comando por id, o None si no existe."""
    with _lock:
        for c in _load_raw().commands:
            if c.id == cmd_id:
                return c
    return None


def add_command(label: str, command: str) -> Command:
    """Crea y persiste un comando nuevo. Devuelve el comando creado."""
    label, command = _validate_command(label, command)
    with _lock:
        lib = _load_raw()
        created = Command(id=secrets.token_hex(4), label=label, command=command)
        lib.commands.append(created)
        _persist(lib)
        return created


def update_command(
    cmd_id: str,
    label: str,
    command: str,
) -> Optional[Command]:
    """Actualiza un comando existente. Devuelve el comando o None si no existe."""
    label, command = _validate_command(label, command)
    with _lock:
        lib = _load_raw()
        for c in lib.commands:
            if c.id == cmd_id:
                c.label = label
                c.command = command
                _persist(lib)
                return c
        return None


def delete_command(cmd_id: str) -> bool:
    """Elimina un comando por id. Devuelve True si se borró."""
    with _lock:
        lib = _load_raw()
        remaining = [c for c in lib.commands if c.id != cmd_id]
        if len(remaining) == len(lib.commands):
            return False
        lib.commands = remaining
        _persist(lib)
        return True


# ---------------------------------------------------------------------- #
# Textos rápidos                                                          #
# ---------------------------------------------------------------------- #
def list_snippets() -> list[Snippet]:
    """Devuelve todos los textos rápidos, en orden de inserción."""
    with _lock:
        return _load_raw().snippets


def get_snippet(snippet_id: str) -> Optional[Snippet]:
    """Devuelve un texto rápido por id, o None si no existe."""
    with _lock:
        for s in _load_raw().snippets:
            if s.id == snippet_id:
                return s
    return None


def add_snippet(label: str, text: str, submit: bool = False) -> Snippet:
    """Crea y persiste un texto rápido nuevo."""
    label, text = _validate_snippet(label, text)
    with _lock:
        lib = _load_raw()
        created = Snippet(
            id=secrets.token_hex(4), label=label, text=text, submit=bool(submit)
        )
        lib.snippets.append(created)
        _persist(lib)
        return created


def update_snippet(
    snippet_id: str, label: str, text: str, submit: bool = False
) -> Optional[Snippet]:
    """Actualiza un texto rápido. Devuelve None si no existe."""
    label, text = _validate_snippet(label, text)
    with _lock:
        lib = _load_raw()
        for s in lib.snippets:
            if s.id == snippet_id:
                s.label = label
                s.text = text
                s.submit = bool(submit)
                _persist(lib)
                return s
        return None


def delete_snippet(snippet_id: str) -> bool:
    """Elimina un texto rápido por id. Devuelve True si se borró."""
    with _lock:
        lib = _load_raw()
        remaining = [s for s in lib.snippets if s.id != snippet_id]
        if len(remaining) == len(lib.snippets):
            return False
        lib.snippets = remaining
        _persist(lib)
        return True


# ---------------------------------------------------------------------- #
# Proyectos                                                               #
# ---------------------------------------------------------------------- #
def list_projects() -> list[Project]:
    """Devuelve todos los proyectos guardados, en orden de inserción."""
    with _lock:
        return _load_raw().projects


def get_project(project_id: str) -> Optional[Project]:
    """Devuelve un proyecto por id, o None si no existe."""
    with _lock:
        for p in _load_raw().projects:
            if p.id == project_id:
                return p
    return None


def add_project(
    title: str, cwd: Optional[str], commands: list[str], links=None, space=None
) -> Project:
    """Crea y persiste un proyecto nuevo. Devuelve el proyecto creado."""
    title, cwd, cmds, lnks, space_id = _validate_project(
        title, cwd, commands, links, space
    )
    with _lock:
        lib = _load_raw()
        created = Project(
            id=secrets.token_hex(4), title=title, cwd=cwd, commands=cmds,
            links=lnks, space=space_id,
        )
        lib.projects.append(created)
        _persist(lib)
        return created


def update_project(
    project_id: str,
    title: str,
    cwd: Optional[str],
    commands: list[str],
    links=None,
    space=None,
) -> Optional[Project]:
    """Actualiza un proyecto existente. Devuelve el proyecto o None si no existe."""
    title, cwd, cmds, lnks, space_id = _validate_project(
        title, cwd, commands, links, space
    )
    with _lock:
        lib = _load_raw()
        for p in lib.projects:
            if p.id == project_id:
                p.title = title
                p.cwd = cwd
                p.commands = cmds
                p.links = lnks
                p.space = space_id
                _persist(lib)
                return p
        return None


def delete_project(project_id: str) -> bool:
    """Elimina un proyecto por id. Devuelve True si se borró."""
    with _lock:
        lib = _load_raw()
        remaining = [p for p in lib.projects if p.id != project_id]
        if len(remaining) == len(lib.projects):
            return False
        lib.projects = remaining
        lib.session_projects = {
            name: pid
            for name, pid in lib.session_projects.items()
            if pid != project_id
        }
        _persist(lib)
        return True


# ---------------------------------------------------------------------- #
# Vínculo sesión -> proyecto                                              #
# ---------------------------------------------------------------------- #
def session_projects() -> dict[str, str]:
    """Mapa `nombre de sesión -> id de proyecto` de las sesiones lanzadas."""
    with _lock:
        return dict(_load_raw().session_projects)


def link_session(session_name: str, project_id: str) -> None:
    """Anota que esta sesión de tmux salió de este proyecto."""
    with _lock:
        lib = _load_raw()
        lib.session_projects[session_name] = project_id
        _persist(lib)


def rename_session(old: str, new: str) -> None:
    """Arrastra el vínculo al nuevo nombre tras renombrar en tmux."""
    if old == new:
        return
    with _lock:
        lib = _load_raw()
        project_id = lib.session_projects.pop(old, None)
        if project_id is not None:
            lib.session_projects[new] = project_id
            _persist(lib)


def forget_session(session_name: str) -> None:
    """Olvida el vínculo de una sesión destruida (kill-session)."""
    with _lock:
        lib = _load_raw()
        if lib.session_projects.pop(session_name, None) is not None:
            _persist(lib)