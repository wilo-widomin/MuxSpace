"""Avisos de atención: qué sesiones reclaman al usuario.

Un agente que corre dentro de una sesión de tmux (un hook de Claude Code, un
script largo que termina) marca su sesión desde el propio host. El panel lo
pinta como una señal en el tile y en el sidebar, suena una campanilla, y la
marca se apaga cuando el usuario atiende esa terminal.

**El estado vive en el servidor a propósito**, aunque el resto de "lo que se
ve en el grid" sea estado de cliente (ver `space_store`). Aquí no se guarda
una vista: se guarda un hecho del servidor —una sesión pidió atención— y de
ahí salen las dos propiedades que el usuario nota:

- Se entera quien no estaba: si el tile está cerrado, o la página se recarga,
  o abres el panel media hora después, el aviso sigue ahí.
- Se apaga en todas partes: atenderlo en el portátil quita la marca también
  en la tablet, porque el pendiente era uno solo.

**En memoria, no en disco.** Un aviso caduca por naturaleza: sobrevivir a un
reinicio del backend significaría resucitar reclamaciones de un proceso que
ya no existe. Es el mismo criterio que las sesiones de login.

**Un solo worker.** Como el resto de estado en proceso, con varios workers
cada uno tendría sus propios pendientes. Ver `docs/un-solo-worker.md`.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from datafiles import write_private

# Fichero con el secreto que autoriza a marcar. Vive en `data/` con 0600: lo
# lee el hook, que corre como el mismo usuario que el backend.
_TOKEN_PATH = Path(__file__).resolve().parent / "data" / "attention_token"

# Tope de texto del aviso. No es un mensaje: es una etiqueta de una línea
# ("espera tu respuesta"), y lo que no quepa se recorta en vez de rechazarse
# —un hook no debe fallar por pasarse de largo.
MAX_LABEL = 120

_lock = Lock()
_pending: dict[str, "Attention"] = {}
_token: str | None = None


@dataclass(frozen=True)
class Attention:
    """Una sesión reclamando atención, con el momento en que lo pidió."""

    at: float
    label: str | None = None


def mark(name: str, label: str | None = None) -> Attention:
    """Marca `name` como pendiente de atención y devuelve el aviso.

    Un segundo aviso sobre una sesión ya marcada **refresca** el momento y la
    etiqueta en vez de acumularse: la marca es un estado (esta sesión te
    espera), no una cola de mensajes. Así diez avisos seguidos siguen siendo
    una sola señal que se apaga con un solo gesto.
    """
    limpio = (label or "").strip()[:MAX_LABEL] or None
    aviso = Attention(at=time.time(), label=limpio)
    with _lock:
        _pending[name] = aviso
    return aviso


def clear(name: str) -> bool:
    """Quita la marca de `name`. Devuelve si había algo que quitar."""
    with _lock:
        return _pending.pop(name, None) is not None


def clear_all() -> list[str]:
    """Quita todas las marcas y devuelve las sesiones que las tenían."""
    with _lock:
        nombres = list(_pending)
        _pending.clear()
    return nombres


def get(name: str) -> Attention | None:
    """Aviso pendiente de `name`, o None."""
    with _lock:
        return _pending.get(name)


def pending() -> dict[str, Attention]:
    """Copia del mapa de pendientes, para pintar el listado de sesiones."""
    with _lock:
        return dict(_pending)


def forget_session(name: str) -> None:
    """Olvida el pendiente de una sesión que se mató.

    Se llama aunque no hubiera marca: un nombre reutilizado no debe nacer
    reclamando atención por lo que hizo la sesión anterior.
    """
    clear(name)


def rename_session(old: str, new: str) -> None:
    """Arrastra el pendiente al nombre nuevo al renombrar una sesión."""
    with _lock:
        aviso = _pending.pop(old, None)
        if aviso is not None:
            _pending[new] = aviso


def hook_token() -> str:
    """Secreto que autoriza a marcar desde fuera del navegador.

    El que marca es un hook en el host, sin cookie ni contraseña que ofrecer:
    pedirle las credenciales del panel obligaría a dejar la contraseña del
    sistema en un fichero de configuración. Un secreto propio, de un solo uso
    (marcar), es menos de lo que concede una sesión y se puede rotar borrando
    el fichero.

    Se genera la primera vez que hace falta y se guarda con 0600.
    """
    global _token
    if _token is not None:
        return _token
    with _lock:
        if _token is not None:  # pragma: no cover — carrera entre hilos
            return _token
        try:
            guardado = _TOKEN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            guardado = ""
        if not guardado:
            guardado = secrets.token_urlsafe(32)
            write_private(_TOKEN_PATH, guardado + "\n")
        _token = guardado
    return _token


def token_matches(candidato: str | None) -> bool:
    """Compara en tiempo constante el token recibido con el del host."""
    if not candidato:
        return False
    return secrets.compare_digest(candidato, hook_token())
