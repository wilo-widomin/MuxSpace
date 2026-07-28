"""Historial de los últimos archivos subidos desde el panel.

A diferencia de las capturas pegadas (que viven todas en `data/pastes/` y se
recortan por retención), los archivos subidos van a carpetas **reales** que
elige el usuario: nunca los borramos. Lo único que guardamos aquí es un
pequeño historial —las últimas N subidas— para poder volver a copiar su ruta
sin tener que recordar dónde quedaron.

El historial se persiste en un único JSON (`data/upload_history.json`) para
que sobreviva a reinicios del backend. Cada entrada es `{name, path, dir}`
(nombre final del archivo, ruta absoluta y carpeta destino, ambas en el
host). "Quitar del historial" borra solo el registro, jamás el archivo.
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from datafiles import write_private

# Cuántas subidas recientes conservamos en el historial.
KEEP = 5

_STORE_PATH = Path(__file__).resolve().parent / "data" / "upload_history.json"
_lock = Lock()


def _load() -> list[dict]:
    """Lee el historial de disco. Ausente o corrupto => historial vacío."""
    if not _STORE_PATH.is_file():
        return []
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    # `ValueError` y no `json.JSONDecodeError`: el archivo se serializa con
    # `ensure_ascii=False`, así que uno cortado en medio de un carácter
    # multibyte hace lanzar al `read_text` un `UnicodeDecodeError` — hermano
    # de `JSONDecodeError` bajo `ValueError`, y no subclase suya. Capturar
    # solo el segundo rompía el contrato "leer nunca lanza" (S15).
    except (ValueError, OSError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for item in data:
        if (
            isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("path"), str)
        ):
            out.append(
                {
                    "name": item["name"],
                    "path": item["path"],
                    "dir": item.get("dir") or "",
                }
            )
    return out


def _save(items: list[dict]) -> None:
    # tmp + replace y 0600 (ver `datafiles`): antes se reescribía en sitio
    # —el único de los cuatro stores que no era atómico— y una caída a
    # media escritura corrompía el historial.
    write_private(_STORE_PATH, json.dumps(items, ensure_ascii=False, indent=2))


def list_recent() -> list[dict]:
    """Historial actual (la subida más reciente primero, máx. `KEEP`)."""
    with _lock:
        return _load()[:KEEP]


def add(name: str, path: str, directory: str) -> list[dict]:
    """Registra una subida al frente del historial y recorta a `KEEP`.

    Si ya había un registro para la misma ruta, se sustituye (no se duplica).
    Devuelve el historial resultante.
    """
    with _lock:
        items = [i for i in _load() if i["path"] != path]
        items.insert(0, {"name": name, "path": path, "dir": directory})
        items = items[:KEEP]
        _save(items)
        return items


def remove(path: str) -> list[dict]:
    """Quita del historial el registro de `path` (NO borra el archivo)."""
    with _lock:
        items = [i for i in _load() if i["path"] != path]
        _save(items)
        return items
