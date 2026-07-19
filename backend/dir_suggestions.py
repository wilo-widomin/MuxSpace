"""Sugerencias de directorios para el autocompletado del frontend.

Dado lo que el usuario va escribiendo en el campo "directorio", devuelve
los subdirectorios inmediatos que coinciden con el prefijo tecleado, pero
**solo** si el directorio a listar cae bajo una de las raíces configuradas
(`config.DIR_SUGGESTION_ROOTS`, con `~` expandido al home del usuario que
ejecuta el backend). Así las sugerencias "siempre arrancan a partir de mi
usuario" y no se exponen zonas arbitrarias del sistema de ficheros.
"""
from __future__ import annotations

import os
from pathlib import Path

import config


def _expand(p: str) -> str:
    """Expande `~` y variables de entorno; cadena vacía si `p` es vacío."""
    if not p:
        return ""
    return os.path.expanduser(os.path.expandvars(p))


def _resolve_roots() -> list[Path]:
    resolved: list[Path] = []
    for r in config.DIR_SUGGESTION_ROOTS:
        path = Path(_expand(r)).expanduser()
        try:
            resolved.append(path.resolve())
        except OSError:
            resolved.append(path)
    # Deduplica manteniendo el orden.
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in resolved:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _is_within(path: Path, roots: list[Path]) -> bool:
    """¿`path` es igual a una raíz o está contenido en alguna de ellas?"""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for root in roots:
        if resolved == root:
            return True
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _abbreviate(path: Path, roots: list[Path]) -> str:
    """Devuelve la forma abreviada con `~` si está bajo el home del usuario."""
    home = Path.home()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    if resolved == home:
        return "~"
    try:
        rel = resolved.relative_to(home)
        return "~/" + str(rel).replace(os.sep, "/")
    except (ValueError, OSError):
        return str(resolved)


def suggest(q: str, limit: int = 50) -> list[str]:
    """Lista de subdirectorios sugeridos para el prefijo `q`.

    - Si `q` está vacío: devuelve las propias raíces (en forma abreviada).
    - Si `q` es una raíz en forma "pura" (`~`, `~/`, `/home/usuario`, o una
      raíz absoluta sin más) o termina en `/`: lista ese directorio.
    - En otro caso: lista el directorio padre y filtra por el último
      segmento como prefijo (autocompletado del nombre en curso).
    Solo se ofrecen resultados cuando el directorio a listar cae bajo una
    raíz configurada.
    """
    roots = _resolve_roots()
    raw = (q or "").strip()

    if not raw:
        return [_abbreviate(r, roots) for r in roots if r.exists()]

    expanded = _expand(raw)
    expanded_path = Path(expanded)

    # ¿Es el propio token raíz (p. ej. "~") o una raíz absoluta sin hijos
    # escritos todavía? Lo tratamos como "lista este directorio".
    is_bare_root = raw in ("~", "~/") or expanded_path in roots

    if raw.endswith("/") or is_bare_root:
        list_dir = expanded_path
        prefix = ""
    else:
        list_dir = expanded_path.parent
        prefix = expanded_path.name

    if not _is_within(list_dir, roots):
        # Si lo tecleado es ya un directorio existente bajo una raíz
        # (caso "escribí el nombre completo sin barra final"), listamos
        # ese directorio en vez de su padre.
        if expanded_path.is_dir() and _is_within(expanded_path, roots):
            list_dir = expanded_path
            prefix = ""
        else:
            return []

    items: list[str] = []
    try:
        children = sorted(list_dir.iterdir(), key=lambda c: c.name)
    except (OSError, PermissionError):
        return []

    for child in children:
        if not child.is_dir():
            continue
        if prefix and not child.name.startswith(prefix):
            continue
        # Oculta directorios ocultos salvo que el usuario esté escribiendo
        # un nombre que empieza por punto.
        if child.name.startswith(".") and not prefix.startswith("."):
            continue
        items.append(_abbreviate(child, roots))
        if len(items) >= limit:
            break
    return items