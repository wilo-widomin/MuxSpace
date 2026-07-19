"""Biblioteca de comandos reutilizables.

Cada "comando" es una sola línea de shell que el usuario puede ejecutar al
crear una nueva sesión de tmux (por ejemplo: `cd ~/proyectos/foo && nvim`,
`htop`, `python -m http.server`). Los comandos se persisten en un JSON para
que la biblioteca sobreviva a reinicios del backend.

El almacenamiento es deliberadamente simple (un archivo JSON plano) y no
mantiene estado en memoria más allá de la caché de lectura: cada mutación
recarga y reescribe el archivo completo. Suficiente para un dashboard de
uso personal.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Optional

from errors import AppError

# Archivo de persistencia junto al resto del backend.
_STORE_PATH = Path(__file__).resolve().parent / "data" / "commands.json"

_lock = Lock()


class CommandError(AppError):
    """Error de validación o de persistencia de la biblioteca de comandos."""


@dataclass
class Command:
    """Un comando guardado en la biblioteca."""
    id: str
    label: str
    command: str
    cwd: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_dir() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_raw() -> list[Command]:
    """Lee el JSON de disco. Ausente o corrupto => lista vacía."""
    if not _STORE_PATH.is_file():
        return []
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    commands: list[Command] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        commands.append(
            Command(
                id=str(item.get("id", "")),
                label=str(item.get("label", "")).strip(),
                command=str(item.get("command", "")),
                cwd=item.get("cwd") or None,
            )
        )
    return commands


def _persist(commands: list[Command]) -> None:
    _ensure_dir()
    payload = [c.to_dict() for c in commands]
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(_STORE_PATH)


def list_commands() -> list[Command]:
    """Devuelve todos los comandos guardados, en orden de inserción."""
    with _lock:
        return _load_raw()


def get_command(cmd_id: str) -> Optional[Command]:
    """Devuelve un comando por id, o None si no existe."""
    with _lock:
        for c in _load_raw():
            if c.id == cmd_id:
                return c
    return None


def _validate(label: str, command: str) -> tuple[str, str]:
    label = (label or "").strip()
    command = (command or "").strip()
    if not command:
        raise CommandError("err.command_empty")
    if not label:
        # Si no se indica etiqueta, usamos el propio comando como nombre.
        label = command if len(command) <= 60 else command[:57] + "…"
    return label, command


def add_command(label: str, command: str, cwd: Optional[str] = None) -> Command:
    """Crea y persiste un comando nuevo. Devuelve el comando creado."""
    label, command = _validate(label, command)
    with _lock:
        commands = _load_raw()
        created = Command(
            id=secrets.token_hex(4),
            label=label,
            command=command,
            cwd=(cwd or None),
        )
        commands.append(created)
        _persist(commands)
        return created


def update_command(
    cmd_id: str,
    label: str,
    command: str,
    cwd: Optional[str] = None,
) -> Optional[Command]:
    """Actualiza un comando existente. Devuelve el comando o None si no existe."""
    label, command = _validate(label, command)
    with _lock:
        commands = _load_raw()
        for c in commands:
            if c.id == cmd_id:
                c.label = label
                c.command = command
                c.cwd = cwd or None
                _persist(commands)
                return c
        return None


def delete_command(cmd_id: str) -> bool:
    """Elimina un comando por id. Devuelve True si se borró."""
    with _lock:
        commands = _load_raw()
        remaining = [c for c in commands if c.id != cmd_id]
        if len(remaining) == len(commands):
            return False
        _persist(remaining)
        return True
