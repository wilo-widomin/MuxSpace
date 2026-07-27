"""Escritura de los ficheros de `backend/data/` con permisos privados.

Todo lo que vive ahí es del usuario y solo suyo: la biblioteca de comandos
(que son literalmente órdenes que el panel ejecuta), el historial de
subidas, el registro de intentos de login y las capturas pegadas. Con el
umask por defecto salían a 0644, legibles por cualquier usuario local de
una máquina en la que el panel ya da una shell.

Aquí se centraliza ese 0700/0600 y, de paso, la escritura atómica: los
cuatro stores hacían lo mismo con pequeñas diferencias (uno de ellos, sin
tmp + replace).
"""
from __future__ import annotations

import os
from pathlib import Path

# Solo el dueño. El panel es de un único usuario por definición: sirve las
# sesiones de tmux de quien ejecuta el backend.
DIR_MODE = 0o700
FILE_MODE = 0o600


def ensure_dir(path: Path) -> Path:
    """Crea `path` (con sus padres) y le fija 0700. Idempotente."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(DIR_MODE)
    except OSError:
        # Un montaje que no admite chmod no es motivo para tumbar el panel:
        # el directorio existe, que es lo que hacía falta.
        pass
    return path


def write_private(path: Path, data: bytes | str) -> None:
    """Escribe `path` de forma atómica y con permisos 0600.

    tmp + replace: si el proceso muere a media escritura, queda el
    contenido anterior intacto en vez de un fichero truncado. El temporal
    se crea ya con 0600 (`os.open` con el modo), así que los datos nunca
    llegan a existir en disco con permisos laxos.
    """
    ensure_dir(path.parent)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        # El modo de os.open lo recorta el umask (0600 & ~0022 sigue siendo
        # 0600, pero un umask exótico no); con el chmod explícito no depende
        # del entorno desde el que se arrancó el backend.
        os.chmod(tmp, FILE_MODE)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)


def harden_tree(root: Path) -> None:
    """Cierra a 0700/0600 todo lo que ya existe bajo `root`.

    `write_private` solo arregla lo que se vuelve a escribir; una
    instalación con historia tiene ficheros creados antes con el umask por
    defecto. Esto se llama al arrancar para ponerlos al día de una vez.
    """
    if not root.is_dir():
        return
    ensure_dir(root)
    for path in root.rglob("*"):
        # Un symlink se saltaría: chmod sigue el enlace y acabaríamos
        # tocando permisos de un fichero de fuera de `root`.
        if path.is_symlink():
            continue
        try:
            path.chmod(DIR_MODE if path.is_dir() else FILE_MODE)
        except OSError:
            pass
