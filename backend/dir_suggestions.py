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


def _resolve(path: Path) -> Path | None:
    """`path.resolve()`, o `None` si el sistema de ficheros no puede resolverlo.

    `Path.resolve()` no traduce todos sus fallos a `OSError`: un bucle de
    symlinks (ELOOP) sale como **`RuntimeError`**, que no es subclase suya
    (Python <= 3.12). Capturar solo `OSError` dejaba que esa excepción subiera
    hasta el endpoint — 500 en vez del rechazo limpio que promete el contrato,
    y con una raíz configurada que fuera un bucle se caían a la vez el
    navegador, las sugerencias y la subida (S14).

    Existe como función y no como cinco `try/except` repartidos porque el
    módulo llama a `resolve()` en cinco sitios y basta con que a uno se le
    olvide un tipo de excepción para reabrir el agujero.
    """
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return None


def _resolve_or_same(path: Path) -> Path:
    """Como `_resolve`, pero cae al `path` sin resolver si no se puede.

    Es el comportamiento que ya tenían los sitios que solo comparan o
    imprimen: un enlace irresoluble no debe hacerlos desaparecer. Los que
    deciden si algo es accesible (`resolve_within_roots`) usan `_resolve` y
    rechazan.
    """
    resolved = _resolve(path)
    return path if resolved is None else resolved


def _resolve_roots() -> list[Path]:
    resolved: list[Path] = []
    for r in config.DIR_SUGGESTION_ROOTS:
        path = Path(_expand(r)).expanduser()
        resolved.append(_resolve_or_same(path))
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
    resolved = _resolve_or_same(path)
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
    resolved = _resolve_or_same(path)
    if resolved == home:
        return "~"
    try:
        rel = resolved.relative_to(home)
        return "~/" + str(rel).replace(os.sep, "/")
    except ValueError:
        # Solo `ValueError`: el `OSError` que se capturaba aquí era del
        # `resolve()` que ahora vive en `_resolve_or_same`; `relative_to` no
        # toca el disco y no puede lanzarlo.
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


# ----------------------------------------------------------------------
# Navegación de carpetas para el modal "subir archivo" (elegir destino).
# Mismo criterio de seguridad que `suggest`: solo se opera dentro de las
# raíces configuradas, con `~` anclado al home del backend.
# ----------------------------------------------------------------------
def resolve_within_roots(q: str) -> Path | None:
    """Devuelve el `Path` real de `q` solo si es un directorio bajo una raíz.

    `None` si queda fuera de las raíces, no existe o no es un directorio.
    Es la puerta de seguridad que usan tanto el navegador como la subida:
    ninguna escritura toca disco sin pasar antes por aquí.
    """
    roots = _resolve_roots()
    raw = (q or "").strip()
    if not raw:
        # Sin ruta: arrancamos en la primera raíz existente.
        return next((r for r in roots if r.is_dir()), None)
    resolved_target = _resolve(Path(_expand(raw)))
    if resolved_target is None:
        return None
    target = resolved_target
    if _is_within(target, roots) and target.is_dir():
        return target
    return None


def browse(q: str = "") -> dict | None:
    """Contenido navegable de una carpeta destino (subdirectorios).

    Devuelve `{path, parent, dirs}` en forma abreviada (con `~`), donde
    `parent` es `None` cuando subir un nivel se saldría de las raíces. Los
    directorios ocultos (empiezan por `.`) no se listan. `None` si `q` no
    es una carpeta válida dentro de las raíces.
    """
    target = resolve_within_roots(q)
    if target is None:
        return None
    roots = _resolve_roots()
    try:
        children = sorted(target.iterdir(), key=lambda c: c.name.lower())
    except (OSError, PermissionError):
        children = []
    dirs = [
        _abbreviate(c, roots)
        for c in children
        if c.is_dir() and not c.name.startswith(".")
    ]
    parent = target.parent
    parent_abbr = (
        _abbreviate(parent, roots)
        if parent != target and _is_within(parent, roots)
        else None
    )
    return {"path": _abbreviate(target, roots), "parent": parent_abbr, "dirs": dirs}


def create_dir(parent_q: str, name: str) -> str | None:
    """Crea la subcarpeta `name` dentro de `parent_q` (ambos bajo una raíz).

    Devuelve la ruta abreviada de la carpeta creada, o `None` si el padre
    queda fuera de las raíces o la creación falla. El nombre ya debe venir
    validado (sin separadores) por quien llama.
    """
    parent = resolve_within_roots(parent_q)
    if parent is None:
        return None
    target = parent / name
    roots = _resolve_roots()
    resolved = _resolve_or_same(target)
    # Tras resolver enlaces/".." el destino debe seguir dentro de las raíces.
    if not _is_within(resolved, roots):
        return None
    try:
        target.mkdir(parents=False, exist_ok=True)
    except OSError:
        return None
    return _abbreviate(target, roots)