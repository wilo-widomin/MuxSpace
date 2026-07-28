"""Espacios: agrupaciones de sesiones (clientes, categorías, proyectos...).

Un **espacio** es un título y nada más; la pertenencia vive aparte, en un
mapa `nombre de sesión -> id de espacio`. Cada sesión pertenece como mucho
a un espacio (modelo de carpetas, no de etiquetas), así que "ver solo las
terminales de este espacio" no tiene ambigüedad.

Las sesiones sin entrada en ese mapa forman el espacio **"Sin asignar"**,
que es virtual: no ocupa sitio en el JSON y no se puede borrar ni renombrar.
Ahí caen las sesiones de tmux creadas fuera del panel.

Este módulo sustituye a `open_registry`, que guardaba en el servidor qué
sesiones estaban "abiertas en el grid". Aquello era un resto de la época de
ttyd (cuando "abierta" significaba "hay un proceso ttyd corriendo", estado
real del servidor). Desde que xterm.js se conecta bajo demanda al puente
PTY, qué se ve en pantalla es asunto de cada pestaña del navegador, no del
backend: mantenerlo aquí impedía tener dos pestañas con vistas distintas.
Lo que sí es compartido —y por eso se persiste aquí— es la organización.

Persistencia en `data/spaces.json`, con el mismo enfoque deliberadamente
simple que `library_store`: un JSON plano que se reescribe entero en cada
mutación. Suficiente para un dashboard de uso personal.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from datafiles import write_private
from errors import AppError

_STORE_PATH = Path(__file__).resolve().parent / "data" / "spaces.json"

_lock = Lock()

# Longitud máxima del título de un espacio.
_MAX_TITLE = 60

# Identificador del espacio virtual de las sesiones sin asignar. No existe
# en el JSON: es simplemente "no tener entrada en `assignments`".
UNASSIGNED = "unassigned"


class SpaceError(AppError):
    """Error de validación o de persistencia de los espacios."""


@dataclass
class Space:
    """Un espacio con nombre. `order` fija su posición en el selector."""
    id: str
    title: str
    order: int

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "order": self.order}


def _read() -> dict:
    """Carga el JSON completo, tolerando que aún no exista o esté corrupto."""
    if not _STORE_PATH.exists():
        return {"spaces": [], "assignments": {}}
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    # `ValueError` y no `json.JSONDecodeError`: el archivo se serializa con
    # `ensure_ascii=False`, así que uno cortado en medio de un carácter
    # multibyte hace lanzar al `read_text` un `UnicodeDecodeError` — hermano
    # de `JSONDecodeError` bajo `ValueError`, y no subclase suya. Capturar
    # solo el segundo rompía el contrato "leer nunca lanza" (S15).
    except (ValueError, OSError):
        # Un archivo ilegible no debe tumbar el panel: se parte de vacío y
        # la primera escritura lo deja consistente otra vez.
        return {"spaces": [], "assignments": {}}
    spaces = raw.get("spaces")
    assignments = raw.get("assignments")
    return {
        "spaces": spaces if isinstance(spaces, list) else [],
        "assignments": assignments if isinstance(assignments, dict) else {},
    }


def _write(data: dict) -> None:
    try:
        # tmp + replace y 0600 (ver `datafiles`): antes se reescribía el
        # JSON en sitio, así que una caída a media escritura dejaba el
        # archivo truncado y los espacios se perdían.
        write_private(_STORE_PATH, json.dumps(data, indent=2, ensure_ascii=False))
    except OSError as exc:
        raise SpaceError("err.spaces_save_failed", technical=str(exc)) from exc


def _clean_title(title: str) -> str:
    title = (title or "").strip()
    if not title:
        raise SpaceError("err.space_title_empty")
    if len(title) > _MAX_TITLE:
        raise SpaceError("err.space_title_too_long", {"max": _MAX_TITLE})
    return title


def list_spaces() -> list[Space]:
    """Espacios reales (sin el virtual "Sin asignar"), en orden."""
    with _lock:
        data = _read()
    spaces = [
        Space(id=s["id"], title=s["title"], order=s.get("order", 0))
        for s in data["spaces"]
        if isinstance(s, dict) and "id" in s and "title" in s
    ]
    spaces.sort(key=lambda s: (s.order, s.title))
    return spaces


def create_space(title: str) -> Space:
    title = _clean_title(title)
    with _lock:
        data = _read()
        orders = [s.get("order", 0) for s in data["spaces"]]
        space = Space(
            id=f"sp_{secrets.token_hex(6)}",
            title=title,
            order=(max(orders) + 1) if orders else 0,
        )
        data["spaces"].append(space.to_dict())
        _write(data)
    return space


def update_space(space_id: str, title: str) -> Space:
    title = _clean_title(title)
    with _lock:
        data = _read()
        for entry in data["spaces"]:
            if entry.get("id") == space_id:
                entry["title"] = title
                _write(data)
                return Space(
                    id=space_id, title=title, order=entry.get("order", 0)
                )
    raise SpaceError("err.space_not_found", {"id": space_id})


def delete_space(space_id: str) -> None:
    """Borra el espacio y devuelve sus sesiones a "Sin asignar".

    Nunca toca las sesiones de tmux: borrar una carpeta no destruye lo que
    hay dentro.
    """
    with _lock:
        data = _read()
        remaining = [s for s in data["spaces"] if s.get("id") != space_id]
        if len(remaining) == len(data["spaces"]):
            raise SpaceError("err.space_not_found", {"id": space_id})
        data["spaces"] = remaining
        data["assignments"] = {
            name: sid
            for name, sid in data["assignments"].items()
            if sid != space_id
        }
        _write(data)


def assignments() -> dict[str, str]:
    """Mapa `nombre de sesión -> id de espacio` de las sesiones asignadas."""
    with _lock:
        return dict(_read()["assignments"])


def assign(session_name: str, space_id: str | None) -> None:
    """Mueve una sesión a un espacio. `None` o UNASSIGNED la deja sin asignar."""
    with _lock:
        data = _read()
        if space_id in (None, "", UNASSIGNED):
            data["assignments"].pop(session_name, None)
        else:
            if not any(s.get("id") == space_id for s in data["spaces"]):
                raise SpaceError("err.space_not_found", {"id": space_id})
            data["assignments"][session_name] = space_id
        _write(data)


def rename_session(old: str, new: str) -> None:
    """Arrastra la asignación al nuevo nombre tras renombrar en tmux."""
    if old == new:
        return
    with _lock:
        data = _read()
        space_id = data["assignments"].pop(old, None)
        if space_id is not None:
            data["assignments"][new] = space_id
            _write(data)


def forget_session(session_name: str) -> None:
    """Olvida la asignación de una sesión destruida (kill-session)."""
    with _lock:
        data = _read()
        if data["assignments"].pop(session_name, None) is not None:
            _write(data)
