"""Biblioteca reutilizable: Comandos y Proyectos.

- **Comando**: una sola línea de shell (sin directorio). Se envía a la
  terminal con foco, o se lanza en una sesión nueva si no hay foco.
- **Proyecto**: un título, un directorio (cwd) y una lista de comandos que
  se ejecutan secuencialmente en una sesión nueva.

Ambos se persisten en un único JSON (`data/library.json`) para que la
biblioteca sobreviva a reinicios del backend. El almacenamiento es
deliberadamente simple (un archivo JSON plano) y no mantiene estado en
memoria más allá de la caché de lectura: cada mutación recarga y reescribe
el archivo completo. Suficiente para un dashboard de uso personal.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional

from datafiles import write_private
from errors import AppError

# Archivo de persistencia junto al resto del backend.
_STORE_PATH = Path(__file__).resolve().parent / "data" / "library.json"

_lock = Lock()


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
class Project:
    """Un proyecto: directorio + secuencia de comandos."""
    id: str
    title: str
    cwd: Optional[str] = None
    commands: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class _Library:
    """Snapshot de la biblioteca leída de disco."""

    def __init__(self) -> None:
        self.commands: list[Command] = []
        self.projects: list[Project] = []


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
            )
        )
    return lib


def _persist(lib: _Library) -> None:
    payload = {
        "commands": [c.to_dict() for c in lib.commands],
        "projects": [p.to_dict() for p in lib.projects],
    }
    # `write_private` hace el tmp + replace y deja el fichero a 0600: son
    # los comandos que el panel ejecuta, no algo que deba poder leer
    # cualquier usuario local de la máquina.
    write_private(_STORE_PATH, json.dumps(payload, ensure_ascii=False, indent=2))


def _default_label(command: str) -> str:
    return command if len(command) <= 60 else command[:57] + "…"


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


def _validate_command(label: str, command: str) -> tuple[str, str]:
    label = (label or "").strip()
    command = (command or "").strip()
    if not command:
        raise LibraryError("err.command_empty")
    if not label:
        label = _default_label(command)
    return label, command


def _validate_project(title: str, cwd: Optional[str], commands: list[str]) -> tuple[str, Optional[str], list[str]]:
    title = (title or "").strip()
    if not title:
        raise LibraryError("err.project_title_required")
    cwd = (cwd or "").strip() or None
    cmds = _normalize_commands(commands)
    if not cmds:
        raise LibraryError("err.project_needs_command")
    return title, cwd, cmds


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


def add_project(title: str, cwd: Optional[str], commands: list[str]) -> Project:
    """Crea y persiste un proyecto nuevo. Devuelve el proyecto creado."""
    title, cwd, cmds = _validate_project(title, cwd, commands)
    with _lock:
        lib = _load_raw()
        created = Project(id=secrets.token_hex(4), title=title, cwd=cwd, commands=cmds)
        lib.projects.append(created)
        _persist(lib)
        return created


def update_project(
    project_id: str,
    title: str,
    cwd: Optional[str],
    commands: list[str],
) -> Optional[Project]:
    """Actualiza un proyecto existente. Devuelve el proyecto o None si no existe."""
    title, cwd, cmds = _validate_project(title, cwd, commands)
    with _lock:
        lib = _load_raw()
        for p in lib.projects:
            if p.id == project_id:
                p.title = title
                p.cwd = cwd
                p.commands = cmds
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
        _persist(lib)
        return True