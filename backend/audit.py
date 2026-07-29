"""Registro de auditoría de las acciones que ejecutan algo.

Este panel corre comandos como el usuario que lo arranca. Hasta ahora no
quedaba traza de **qué** comando se ejecutó, en qué sesión, cuándo ni desde
qué IP: precisamente el log que se necesita el día que pase algo (hallazgo S8
de `docs/auditoria-2026-07.md`).

Formato: **JSONL**, un objeto por línea, en `data/audit.log`. Se elige por lo
aburrido que es: se lee con `tail`, se filtra con `grep`, se procesa con `jq`
y una línea corrupta no arrastra a las demás. Un JSON array habría que
reescribirlo entero en cada anotación.

Qué NO es: el logging de la aplicación (Q6 del análisis). Aquí solo entran
acciones con efecto, no el flujo interno del proceso.

Dos reglas que no se negocian:

1. **Escribir aquí nunca tumba una petición.** Si el disco está lleno o los
   permisos cambiaron, se traga el error y la acción sigue. Un panel que deja
   de funcionar porque no puede escribir su propio log de auditoría es peor
   que un panel sin log.
2. **Nunca se registran credenciales.** Ni contraseñas ni tokens de sesión;
   del login solo interesa si hubo éxito y desde dónde.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import logs
from datafiles import FILE_MODE, ensure_dir

_log = logs.obtener(__name__)

_LOG_PATH = Path(__file__).resolve().parent / "data" / "audit.log"

# Tope antes de rotar. 5 MB son del orden de 30.000 acciones: meses de uso de
# un panel personal, y sigue siendo un fichero que `grep` recorre al instante.
_MAX_BYTES = 5 * 1024 * 1024

# Se conserva UNA rotación (`audit.log.1`) y la anterior se pierde. Es una
# decisión, no un olvido: sin ella el log crece sin techo en un disco que
# también guarda las sesiones del usuario. Quien necesite histórico completo,
# que se lleve el fichero fuera.
_lock = threading.Lock()


def _client_ip(request) -> str:
    """IP del cliente, con el mismo criterio que el rate limit del login.

    uvicorn ya resuelve `X-Forwarded-For` cuando se arranca con
    `--forwarded-allow-ips` (ver `config.py`), así que aquí basta con leer
    `request.client`: si se hiciera a mano, un proxy no configurado dejaría
    que cualquiera se inventara su IP en el log de auditoría.
    """
    try:
        return request.client.host if request and request.client else "?"
    except Exception:
        return "?"


def _rotate_locked() -> None:
    """Si el log superó el tope, lo mueve a `.1` y deja sitio para uno nuevo."""
    try:
        if _LOG_PATH.stat().st_size < _MAX_BYTES:
            return
    except OSError:
        return  # aún no existe: nada que rotar
    try:
        _LOG_PATH.replace(_LOG_PATH.with_name(_LOG_PATH.name + ".1"))
    except OSError:
        pass


def record(
    action: str,
    *,
    request=None,
    user: str | None = None,
    target: str | None = None,
    detail: dict | None = None,
) -> None:
    """Anota una acción. No lanza nunca.

    `action` es el verbo (`send-command`, `kill-session`…), `target` el objeto
    sobre el que actúa (normalmente el nombre de la sesión) y `detail` lo que
    haga falta para reconstruir qué pasó: el comando enviado, la ruta subida,
    el nombre nuevo al renombrar.
    """
    try:
        entrada = {
            # ISO 8601 con zona, no epoch: el log se lee a ojo cuando algo ha
            # pasado, y un número de diez cifras no se lee a ojo.
            "ts": datetime.now(timezone.utc).isoformat(),
            "ip": _client_ip(request),
            "user": user,
            "action": action,
            "target": target,
            "detail": detail or {},
        }
        linea = json.dumps(entrada, ensure_ascii=False) + "\n"
        with _lock:
            ensure_dir(_LOG_PATH.parent)
            _rotate_locked()
            # O_APPEND para que la escritura sea atómica frente a otros
            # escritores, y el modo en el `os.open` para que el fichero nunca
            # llegue a existir con permisos laxos (los stores hacen lo mismo).
            fd = os.open(
                _LOG_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, FILE_MODE
            )
            try:
                os.write(fd, linea.encode("utf-8"))
            finally:
                os.close(fd)
    except Exception:
        # Ver la regla 1 del docstring del módulo: el log de auditoría no puede
        # tumbar la acción que está auditando. Pero callarlo del todo dejaba el
        # peor de los mundos —un panel que cree estar auditando y no audita—,
        # así que desde Q6 se avisa por el log de la aplicación.
        try:
            _log.warning(
                "no se pudo registrar la acción %r en %s", action, _LOG_PATH,
                exc_info=True,
            )
        except Exception:  # noqa: S110 — si hasta el logging falla (disco
            # lleno, stderr cerrado), no queda nada más que hacer: lo que NO
            # puede es propagar y tumbar la petición.
            pass
