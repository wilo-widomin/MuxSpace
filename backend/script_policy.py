"""Qué puede lanzar el token de scripts.

Lanzar un proyecto ejecuta shell: un comando sin revisar convertiría el token
en una shell completa como el usuario del panel. Aquí está la lista blanca de
lo único que un script puede dejar guardado para ejecutarse, y se comprueba al
crear **y otra vez al lanzar**, porque entre medias Willy puede editar el
proyecto desde el panel, donde estas reglas no aplican.

Son funciones puras, sin HTTP ni disco de datos: la configuración les llega
por parámetro y el resultado es un valor o un `ScriptPolicyError`.
"""
from __future__ import annotations

import shlex
import unicodedata
from pathlib import Path

from errors import AppError

# Caracteres prohibidos en cualquier sitio tras el prefijo, también dentro de
# comillas dobles. El comando llega a un shell interactivo por `send-keys`,
# así que lo que vale es cómo lo lee ese shell y no cómo lo lee `shlex`:
#
#   ; & |            encadenan órdenes.
#   $ ` ( ) \        incrustan órdenes; `$()` y las comillas invertidas se
#                    ejecutan dentro de comillas dobles, y `\` deja escapar
#                    de ellas.
#   < >              redirigen a un archivo.
#   ' " no entra     las comillas dobles hacen falta para `-n` y el mensaje;
#                    las simples no, y quitarlas deja una sola forma de citar.
#   * ? [ ] { } ~    `shlex` los ve como texto y el shell los expande en más
#                    palabras: `claude {--settings,x}` o un `*` en una carpeta
#                    con un archivo llamado `--add-dir` saltarían la lista
#                    blanca de opciones.
#   ! ^              expansión del historial en un shell interactivo, que
#                    actúa incluso entre comillas dobles.
#   #                `shlex` no lo trata como comentario y el shell sí.
_FORBIDDEN = frozenset(";&|$`()\\<>'*?[]{}~!^#")


class ScriptPolicyError(AppError):
    """El token no puede hacer esto. `result` es la etiqueta para la auditoría."""

    def __init__(self, code: str, result: str, status: int, reason: str) -> None:
        super().__init__(code, technical=reason)
        self.result = result
        self.status = status


def _reject_command(reason: str) -> ScriptPolicyError:
    return ScriptPolicyError(
        "err.script_command_rejected", "command-rejected", 403, reason
    )


def _is_forbidden(char: str) -> bool:
    if char in _FORBIDDEN:
        return True
    # Control, formato (caracteres invisibles) y cualquier separador que no
    # sea el espacio corriente, que es el único que parten igual `shlex` y el
    # shell. Incluye los saltos de línea.
    return (
        unicodedata.category(char).startswith("C")
        or (char.isspace() and char != " ")
    )


def check_command(command: str, prefix: str) -> None:
    """Exige `<prefijo> [--permission-mode auto] [-n <texto>] ["mensaje"]`.

    El prefijo es la configuración de Willy y no se analiza; todo lo demás
    pasa por la lista blanca. Una opción puede repetirse cero o una veces.
    """
    if not prefix:
        raise _reject_command("no hay prefijo de comandos configurado")
    if command != prefix and not command.startswith(prefix + " "):
        raise _reject_command("no empieza por el prefijo configurado")

    rest = command[len(prefix):]
    forbidden = sorted({c for c in rest if _is_forbidden(c)})
    if forbidden:
        raise _reject_command(f"caracteres no permitidos: {forbidden!r}")
    try:
        args = shlex.split(rest)
    except ValueError as exc:
        raise _reject_command(f"no se puede analizar: {exc}") from exc

    seen: set[str] = set()
    position = 0
    while position < len(args):
        arg = args[position]
        position += 1
        if arg in ("--permission-mode", "-n"):
            if arg in seen:
                raise _reject_command(f"opción repetida: {arg}")
            seen.add(arg)
            value = args[position] if position < len(args) else ""
            position += 1
            if arg == "--permission-mode" and value != "auto":
                raise _reject_command("solo se admite --permission-mode auto")
            if not value or value.startswith("-"):
                raise _reject_command(f"valor no válido para {arg}")
        elif arg.startswith("-"):
            raise _reject_command(f"opción no permitida: {arg}")
        elif "message" in seen:
            raise _reject_command("solo se admite un mensaje")
        elif " " not in arg:
            # Una sola palabra sería un subcomando de `claude` (`update`,
            # `install`, `mcp`), no un mensaje.
            raise _reject_command("el mensaje debe tener más de una palabra")
        else:
            seen.add("message")


def check_commands(commands: list[str], prefix: str) -> None:
    """Un solo comando por proyecto, y ese debe cumplir `check_command`."""
    if len(commands) != 1:
        raise _reject_command("debe haber exactamente un comando")
    check_command(commands[0], prefix)


def resolve_cwd(cwd: str | None, root: str) -> str:
    """Carpeta real del proyecto, que debe estar dentro de `root`.

    Devuelve la ruta ya resuelta para usarla en vez de la recibida. Fuera de
    la raíz es 403 aunque no exista, para no decir qué hay fuera; dentro, una
    carpeta que falta es 400, un error del que llama y no un permiso.
    """
    outside = ScriptPolicyError(
        "err.script_cwd_rejected", "cwd-rejected", 403, "fuera de la raíz permitida"
    )
    raw = (cwd or "").strip()
    if not raw:
        raise outside
    try:
        base = Path(root).expanduser().resolve()
        target = Path(raw).expanduser()
        # `resolve` sigue los enlaces simbólicos y colapsa los `..`: lo que se
        # compara es adónde se llega de verdad, no lo que dice el texto.
        resolved = target.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise outside from exc
    inside = resolved != base and resolved.is_relative_to(base)
    if not target.is_absolute() or not inside:
        raise outside
    if not resolved.is_dir():
        raise ScriptPolicyError(
            "err.script_cwd_missing", "cwd-missing", 400, "la carpeta no existe"
        )
    return str(resolved)
