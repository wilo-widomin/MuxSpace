#!/usr/bin/env python3
"""Agente mínimo del host: acepta UNA orden, apagar el ordenador.

Solo librería estándar de Python 3. Escucha HTTP y responde a una sola cosa,
`POST /poweroff` con `Authorization: Bearer <token>`. No ejecuta nada que venga
en la petición (ni cuerpo, ni cabeceras, ni parámetros, ni shell): la orden de
apagado es fija y la única entrada que cuenta es el token.

Configuración, por variables de entorno (las pone la unidad de systemd):

  MUXSPACE_AGENT_BIND         dirección donde escuchar. Obligatoria.
  MUXSPACE_AGENT_PORT         puerto. Obligatorio.
  MUXSPACE_AGENT_TOKEN_FILE   archivo con el token (modo 600). Obligatorio.
  MUXSPACE_AGENT_ALLOWED_IPS  direcciones o redes de origen permitidas,
                              separadas por comas. Opcional; vacío = cualquiera
                              (el token sigue mandando).

Respuestas, sin pistas de por qué: 202 apagando; 401 token ausente o malo; 403
origen no permitido; 404 otra ruta; 405 otro método.
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import ipaddress
import logging
import os
import stat
import subprocess
import sys
import threading

# Margen para que la respuesta llegue antes de que la máquina caiga.
POWEROFF_DELAY_SECONDS = 2.0
# Una petición que no acaba de llegar no retiene un hilo para siempre.
REQUEST_TIMEOUT_SECONDS = 5

_log = logging.getLogger("muxspace-host-agent")


def real_poweroff() -> None:
    """La orden de apagado. Es lo único que este programa ejecuta."""
    subprocess.run(["systemctl", "poweroff"], check=False)  # noqa: S603,S607


def parse_allowed(raw: str) -> list:
    """`"10.0.0.1, 10.1.0.0/24"` -> lista de redes. Un valor roto es un error."""
    return [
        ipaddress.ip_network(item.strip(), strict=False)
        for item in raw.split(",")
        if item.strip()
    ]


def read_token(path: str) -> str:
    """Lee el token y se niega si el archivo lo puede leer otro usuario."""
    info = os.stat(path)
    if info.st_uid != os.geteuid() or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise PermissionError("el archivo del token debe ser del propietario y 600")
    token = open(path, encoding="utf-8").read().strip()  # noqa: SIM115
    if len(token) < 24:
        raise ValueError("el token es demasiado corto")
    return token


def _digest(value: str) -> bytes:
    # Comparar huellas de igual longitud: la comparación no depende de cuánto
    # se parezca lo recibido al token ni de su longitud.
    return hashlib.sha256(value.encode("utf-8")).digest()


class _State:
    """Lo que comparte el servidor con sus manejadores."""

    def __init__(self, token_file, allowed, poweroff, delay):
        self.token_file = token_file
        self.allowed = allowed
        self.poweroff = poweroff
        self.delay = delay
        self.lock = threading.Lock()
        self.scheduled = False


class _Handler(http.server.BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT_SECONDS
    protocol_version = "HTTP/1.0"  # una respuesta y se cierra

    # No anunciar servidor ni versión de Python.
    def version_string(self) -> str:
        return "-"

    def log_message(self, format, *args):  # noqa: A002
        pass  # el registro propio de abajo dice más y sin ruido

    @property
    def _state(self) -> _State:
        return self.server.state  # type: ignore[attr-defined]

    def _reply(self, status: int, outcome: str, headers: dict | None = None) -> None:
        _log.info(
            "origen=%s metodo=%s ruta=%s resultado=%s",
            self.client_address[0],
            self.command,
            self.path[:64].replace("\n", " "),
            outcome,
        )
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()

    def _origin_allowed(self) -> bool:
        allowed = self._state.allowed
        if not allowed:
            return True
        try:
            ip = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return any(ip in net for net in allowed)

    def _token_ok(self) -> bool:
        header = self.headers.get("Authorization", "")
        scheme, _, candidate = header.partition(" ")
        try:
            expected = read_token(self._state.token_file)
        except (OSError, ValueError) as exc:
            _log.error("no se puede leer el token: %s", exc)
            return False
        good = hmac.compare_digest(_digest(candidate.strip()), _digest(expected))
        return scheme.lower() == "bearer" and good

    def _handle(self) -> None:
        if not self._origin_allowed():
            return self._reply(403, "origen-no-permitido")
        if self.command != "POST":
            return self._reply(405, "metodo-no-permitido", {"Allow": "POST"})
        if self.path != "/poweroff":
            return self._reply(404, "ruta-desconocida")
        if not self._token_ok():
            return self._reply(401, "token-rechazado")
        state = self._state
        with state.lock:
            first = not state.scheduled
            state.scheduled = True
        self._reply(202, "apagando" if first else "apagado-ya-en-marcha")
        if first:
            timer = threading.Timer(state.delay, state.poweroff)
            timer.daemon = False  # que el apagado ocurra aunque el servidor cierre
            timer.start()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _handle
    do_OPTIONS = _handle


def make_server(
    bind: str,
    port: int,
    token_file: str,
    allowed: list | None = None,
    poweroff=real_poweroff,
    delay: float = POWEROFF_DELAY_SECONDS,
) -> http.server.ThreadingHTTPServer:
    """Monta el servidor. `poweroff` y `delay` se inyectan solo en las pruebas."""
    read_token(token_file)  # si no es válido, que falle al arrancar
    server = http.server.ThreadingHTTPServer((bind, port), _Handler)
    server.daemon_threads = True
    server.state = _State(token_file, allowed or [], poweroff, delay)  # type: ignore[attr-defined]
    return server


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    try:
        server = make_server(
            os.environ["MUXSPACE_AGENT_BIND"],
            int(os.environ["MUXSPACE_AGENT_PORT"]),
            os.environ["MUXSPACE_AGENT_TOKEN_FILE"],
            parse_allowed(os.environ.get("MUXSPACE_AGENT_ALLOWED_IPS", "")),
        )
    except (KeyError, ValueError, OSError) as exc:
        _log.error("no arranca: %s", exc)
        return 1
    _log.info("escuchando; solo acepta POST /poweroff")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
