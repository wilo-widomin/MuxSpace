"""Secreto con el que un script de esta máquina usa la biblioteca del panel.

Un proceso programado (el receptor de entrevistas) tiene que crear un
proyecto, lanzarlo y borrarlo al terminar. No tiene cookie, y con el panel en
modo `pam` la alternativa sería dejar en un fichero la contraseña del sistema.
Este secreto es menos que eso: solo vale para las rutas que declaran
`main._script_auth`, enumeradas en `test_auth_contract.py`, y se rota borrando
el fichero y reiniciando el panel.

**No es inocuo:** lanzar un proyecto ejecuta shell, así que quien lo tenga
ejecuta órdenes como el usuario del panel. Lo que se ahorra es exponer la
contraseña del sistema, no el poder de lanzar.

Es un secreto aparte del de `attention_store` a propósito: aquel lo leen los
hooks de todas las sesiones y solo marca avisos; este no debe llegarles.
"""
from __future__ import annotations

import secrets
from pathlib import Path
from threading import Lock

from datafiles import write_private

_TOKEN_PATH = Path(__file__).resolve().parent / "data" / "script_token"

_lock = Lock()
_token: str | None = None


def script_token() -> str:
    """Devuelve el secreto; lo genera con 0600 si todavía no existe."""
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
    """Compara en tiempo constante el secreto recibido con el del host."""
    if not candidato:
        return False
    return secrets.compare_digest(candidato, script_token())
