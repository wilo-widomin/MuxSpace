"""Cliente del agente del host: pide el apagado del ordenador donde corre la VM.

El agente (`host-agent/host_agent.py`) acepta una sola orden. Aquí solo se
manda esa orden con el token; no se interpreta nada de lo que conteste, salvo
el código HTTP. Los tests sustituyen `send` entero: nunca sale a la red.
"""
from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

import config
from errors import AppError

# La palabra que hay que escribir para confirmar. Vive aquí y el frontend la
# recibe por `/api/capabilities`: dos copias acabarían no coincidiendo.
CONFIRMATION_WORD = "APAGAR"

# Corto a propósito: el agente responde antes de apagar, y un host caído no
# debe dejar la petición del panel colgada.
TIMEOUT_SECONDS = 5


def enabled() -> bool:
    return bool(config.HOST_POWEROFF_URL and config.HOST_POWEROFF_TOKEN)


def confirmation_ok(text: str | None) -> bool:
    """Sin distinguir mayúsculas: un teclado de tablet las pone solo."""
    return (text or "").strip().casefold() == CONFIRMATION_WORD.casefold()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # una redirección llevaría el token a otro sitio


def send() -> None:
    """Manda `POST` al agente. Lanza `AppError` si no se acepta."""
    url = config.HOST_POWEROFF_URL
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise AppError("err.host_poweroff_unreachable", technical="URL no válida")
    req = urllib.request.Request(  # noqa: S310 — esquema comprobado arriba
        url,
        method="POST",
        headers={"Authorization": f"Bearer {config.HOST_POWEROFF_TOKEN}"},
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            if resp.status == 202:
                return
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        raise AppError(
            "err.host_poweroff_unreachable", technical=type(exc).__name__
        ) from exc
    raise AppError("err.host_poweroff_rejected", {"status": status})
