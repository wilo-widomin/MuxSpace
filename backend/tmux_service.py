"""Servicio de interacción con tmux.

Encapsula las llamadas a `tmux` para listar las sesiones activas del
servidor. No mantiene estado: simplemente consulta el sistema.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

from config import TMUX_BINARY
from errors import AppError


class TmuxError(AppError):
    """Error al ejecutar un comando de tmux.

    Lleva un `code` traducible y, cuando tmux dice algo por stderr, ese texto
    crudo en `technical`: sale en el idioma del sistema, así que acompaña al
    mensaje localizado en vez de sustituirlo (ver `errors.AppError`).
    """


@dataclass
class TmuxSession:
    name: str
    windows: int
    attached: bool
    created: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "windows": self.windows,
            "attached": self.attached,
            "created": self.created,
        }


# Formato controlado para parsear de forma fiable la salida de `tmux ls`.
_FORMAT = "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}"


def _ensure_tmux_server() -> None:
    """Asegura que el servidor de tmux esté iniciado."""
    subprocess.run(
        [TMUX_BINARY, "start-server"],
        capture_output=True,
        timeout=5,
    )


def list_sessions() -> list[TmuxSession]:
    """Devuelve la lista de sesiones de tmux activas.

    Si el servidor de tmux no está arrancado (no hay sesiones), tmux
    devuelve un código de error y el texto "no server running"; en ese
    caso devolvemos una lista vacía en lugar de propagar el error.
    """
    _ensure_tmux_server()
    
    try:
        result = subprocess.run(
            [TMUX_BINARY, "list-sessions", "-F", _FORMAT],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:  # tmux no instalado
        raise TmuxError("err.tmux_not_found", {"binary": TMUX_BINARY}) from exc
    except subprocess.TimeoutExpired as exc:
        raise TmuxError("err.tmux_timeout") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if "no server running" in stderr or "no sessions" in stderr:
            return []
        raise TmuxError("err.tmux_unknown", technical=result.stderr)

    sessions: list[TmuxSession] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        # Tolerante a campos faltantes.
        name = parts[0] if len(parts) > 0 else ""
        windows = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        attached = parts[2] == "1" if len(parts) > 2 else False
        created = parts[3] if len(parts) > 3 and parts[3] else None
        if name:
            sessions.append(
                TmuxSession(
                    name=name,
                    windows=windows,
                    attached=attached,
                    created=created,
                )
            )
    return sessions


def session_exists(name: str) -> bool:
    """Comprueba si existe una sesión de tmux con el nombre dado."""
    return any(s.name == name for s in list_sessions())


def _run_tmux(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Ejecuta un comando de tmux y devuelve el resultado en crudo."""
    try:
        return subprocess.run(
            [TMUX_BINARY, *args],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise TmuxError("err.tmux_not_found", {"binary": TMUX_BINARY}) from exc
    except subprocess.TimeoutExpired as exc:
        raise TmuxError("err.tmux_timeout") from exc


def create_session(
    name: str,
    command: str | None = None,
    cwd: str | None = None,
) -> bool:
    """Crea una nueva sesión de tmux desacoplada (`new-session -d`).

    Devuelve True si se creó. Si ya existía una sesión con ese nombre
    devuelve False. Otros errores de tmux se propagan como TmuxError.

    Si se indica `command`, se ejecuta dentro del shell de la nueva
    sesión mediante `send-keys`: cuando el comando termina (p. ej. al
    cerrar nvim) el control vuelve al prompt y la sesión permanece viva.

    Cuando hay además `cwd`, en lugar de fijar el directorio con
    `new-session -c` construimos un único comando `cd <cwd> && <command>`.
    Así el cambio de directorio ocurre en el mismo shell que ejecuta el
    comando, de forma predecible y consistente con el resto del panel.
    """
    new_args = ["new-session", "-d", "-s", name]
    result = _run_tmux(new_args)
    if result.returncode != 0:
        stderr = (result.stderr or "").lower()
        if "duplicate session" in stderr:
            return False
        raise TmuxError("err.session_create_failed", technical=result.stderr)

    command = (command or "").strip()
    cwd = (cwd or "").strip()
    if command:
        # Si hay directorio, lo plegamos en el propio comando en lugar de
        # usar `new-session -c`, de modo que el cd y el comando corren en
        # el mismo shell.
        full = f"cd {cwd} && {command}" if cwd else command
        # send-keys interpreta el último argumento como tecla; "Enter" es
        # el nombre legible de tmux para C-m.
        send = _run_tmux(["send-keys", "-t", name, full, "Enter"])
        if send.returncode != 0:
            # La sesión ya existe; no la dejamos huérfana por un fallo
            # (poco probable) al inyectar el comando.
            raise TmuxError(
                "err.session_command_inject_failed", technical=send.stderr
            )
    elif cwd:
        # Solo directorio, sin comando: un cd simple para dejar la sesión
        # posicionada donde el usuario espera.
        send = _run_tmux(["send-keys", "-t", name, f"cd {cwd}", "Enter"])
        if send.returncode != 0:
            raise TmuxError("err.session_cwd_failed", technical=send.stderr)
    return True


def rename_session(name: str, new_name: str) -> bool:
    """Renombra una sesión de tmux (`rename-session`).

    Devuelve True si se renombró, False si la sesión origen no existe.
    Si ya existe una sesión con `new_name`, tmux lo rechaza y se eleva
    como TmuxError. Otros errores de tmux se propagan como TmuxError.
    """
    result = _run_tmux(["rename-session", "-t", name, new_name])
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").lower()
    if "can't find session" in stderr or "no server running" in stderr:
        return False
    if "duplicate session" in stderr:
        raise TmuxError("err.session_exists", {"name": new_name})
    raise TmuxError("err.session_rename_failed", technical=result.stderr)


def kill_session(name: str) -> bool:
    """Termina por completo la sesión de tmux indicada.

    Devuelve True si la sesión se eliminó, False si ya no existía. Otros
    errores de tmux se propagan como TmuxError.
    """
    result = _run_tmux(["kill-session", "-t", name])
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").lower()
    # Si la sesión ya no existe, lo tratamos como éxito idempotente.
    if "can't find session" in stderr or "no server running" in stderr:
        return False
    raise TmuxError("err.session_kill_failed", technical=result.stderr)


def detach_session(name: str) -> bool:
    """Separa (detach) a todos los clientes conectados a la sesión.

    No destruye la sesión: solo desconecta a quien esté adjunto. Útil
    cuando se quiere liberar la sesión sin perder su estado.
    """
    result = _run_tmux(["detach-client", "-s", name])
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").lower()
    if "can't find session" in stderr or "no server running" in stderr:
        return False
    raise TmuxError("err.session_detach_failed", technical=result.stderr)


def send_command(name: str, command: str) -> None:
    """Envía un comando a la sesión de tmux indicada y pulsa Enter.

    Equivalente a escribir el comando en la terminal y presionar Enter.
    """
    if not command.strip():
        return
    send = _run_tmux(["send-keys", "-t", name, command, "Enter"])
    if send.returncode != 0:
        raise TmuxError(
            "err.send_command_failed", {"name": name}, technical=send.stderr
        )
