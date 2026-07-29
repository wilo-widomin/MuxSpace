"""Logging de la aplicación (Q6 · observabilidad).

Qué problema resuelve: hasta ahora, cuando algo iba mal por dentro, no
quedaba **nada**. El panel se traga varias excepciones a propósito —un tmux
viejo que no conoce una opción, un WebSocket que se cae, un log de auditoría
que no se puede escribir— y todas esas decisiones son correctas: ninguna debe
tumbar una petición. Pero tragarse el error **y además callarlo** deja el
diagnóstico en "pues a mí no me va", que es donde estaba el proyecto.

Qué NO es: el registro de auditoría. Son dos cosas distintas y conviene no
mezclarlas nunca:

| | `audit.py` | este módulo |
|---|---|---|
| Qué registra | Acciones **del usuario** con efecto | Qué le pasa **al proceso** |
| Dónde | `data/audit.log` (JSONL, 0600) | La consola / journald |
| Se pierde al reiniciar | No | Sí, y da igual |
| Se puede desactivar | No | Sí, subiendo el nivel |

## Por qué se propaga en vez de tener su propio manejador

Los registradores de aquí van con `propagate=True` y **sin manejador propio**.
En producción, el proceso lo levanta uvicorn, que ya ha configurado los
manejadores de la raíz: si este módulo añadiera el suyo, cada línea saldría
**dos veces**. Propagando, los mensajes salen por donde ya salen los de
uvicorn, con su mismo destino, y `MUXSPACE_LOG_LEVEL` decide cuáles.

`configurar()` solo instala un manejador cuando la raíz no tiene ninguno, que
es el caso de ejecutar el backend a mano o desde un test.
"""
from __future__ import annotations

import logging
import os

# Prefijo común. Se elige uno propio para que subir o bajar el detalle del
# panel no toque el de uvicorn (que es quien avisa de qué peticiones entran) ni
# el de las bibliotecas de terceros.
_RAIZ = "muxspace"

# Nivel por entorno. INFO por defecto: lo que se quiere ver sin pedirlo es el
# arranque y los avisos, no cada detalle.
_NIVEL_POR_DEFECTO = "INFO"

_FORMATO = "%(levelname)-8s %(name)s: %(message)s"


def nivel_configurado(entorno: dict[str, str] | None = None) -> int:
    """El nivel pedido en `MUXSPACE_LOG_LEVEL`, o INFO si no vale.

    Un nivel mal escrito **no** tumba el arranque: se cae a INFO. Quedarse sin
    panel porque alguien puso `LOG_LEVEL=verbose` sería un precio absurdo por
    una errata en una variable de diagnóstico.
    """
    entorno = os.environ if entorno is None else entorno
    crudo = (entorno.get("MUXSPACE_LOG_LEVEL") or _NIVEL_POR_DEFECTO).strip().upper()
    nivel = logging.getLevelName(crudo)
    # `getLevelName` con un nombre desconocido devuelve la cadena
    # "Level <lo que sea>", no un entero: es la forma de detectar la errata.
    return nivel if isinstance(nivel, int) else logging.INFO


def configurar(entorno: dict[str, str] | None = None) -> None:
    """Deja el logging del panel listo. Idempotente."""
    logging.getLogger(_RAIZ).setLevel(nivel_configurado(entorno))
    # Solo si nadie ha configurado la raíz. Bajo uvicorn ya lo está, y añadir
    # otro manejador duplicaría cada línea. Ver el docstring del módulo.
    if not logging.getLogger().handlers:
        manejador = logging.StreamHandler()
        manejador.setFormatter(logging.Formatter(_FORMATO))
        logging.getLogger().addHandler(manejador)
        logging.getLogger().setLevel(logging.WARNING)


def obtener(nombre: str) -> logging.Logger:
    """El registrador de un módulo del panel: `obtener(__name__)`."""
    return logging.getLogger(f"{_RAIZ}.{nombre}")
