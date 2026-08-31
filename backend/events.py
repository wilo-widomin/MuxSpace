"""Bus de eventos del panel: empuja avisos a las pestañas abiertas.

El listado de sesiones ya se sondea cada pocos segundos, pero ese sondeo no
sirve para avisar: **se para cuando la pestaña está oculta**, que es justo
cuando el usuario necesita enterarse de que una sesión le reclama. De ahí un
WebSocket propio, uno por pestaña, independiente de los terminales: llega el
evento aunque el tile de esa sesión esté cerrado y aunque el panel esté en
segundo plano.

Es un bus **sin memoria**: quien no está suscrito en el instante del evento no
lo recibe. No es un agujero porque el estado de verdad está en
`attention_store` y viaja en `GET /api/sessions`; esto solo adelanta la
noticia. Un cliente que se reconecta se pone al día con el listado.

**En proceso y con un solo worker**, como el resto del estado vivo.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# Tope de eventos encolados por suscriptor. Si una pestaña deja de leer (una
# tablet suspendida, una conexión que se congeló), se descartan los suyos en
# vez de crecer sin fin: el precio de perderlos es que ese cliente se entere
# con el siguiente sondeo, y a cambio un cliente atascado no infla la memoria
# del servidor.
_MAX_QUEUE = 64

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Registra el loop del servidor para poder publicar desde otro hilo."""
    global _loop
    _loop = loop


def subscribers() -> int:
    """Cuántas pestañas hay escuchando. Para diagnóstico."""
    return len(_subscribers)


@asynccontextmanager
async def subscribe() -> AsyncIterator[asyncio.Queue]:
    """Cola propia de eventos mientras dure el `with`."""
    cola: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.add(cola)
    try:
        yield cola
    finally:
        _subscribers.discard(cola)


def publish(event: dict[str, Any]) -> None:
    """Reparte un evento a todas las pestañas suscritas.

    Se puede llamar desde el loop (endpoints `async def`) o desde el
    threadpool en el que FastAPI ejecuta los endpoints `def`; en el segundo
    caso el reparto se agenda en el loop, que es el único hilo que puede
    tocar las colas de asyncio. Sin loop registrado (tests que importan el
    módulo suelto) no hace nada.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(_fanout, event)
        return
    _fanout(event)


def _fanout(event: dict[str, Any]) -> None:
    for cola in list(_subscribers):
        try:
            cola.put_nowait(event)
        except asyncio.QueueFull:
            # Cliente que no lee: se pierde el evento, nunca el servidor.
            pass
