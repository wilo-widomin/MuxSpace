"""El logging de la aplicación (Q6 · observabilidad).

Dos cosas que este módulo tiene que hacer bien y que son fáciles de romper sin
enterarse:

1. **Obedecer a `MUXSPACE_LOG_LEVEL`**, incluida una errata: un nivel mal
   escrito no puede tumbar el arranque del panel.
2. **No duplicar líneas bajo uvicorn.** Es el fallo clásico de añadir un
   `logging.basicConfig` en una app que ya corre dentro de un servidor que
   configuró los manejadores: todo sale por partida doble y nadie relaciona el
   ruido con el commit que lo trajo.

Y lo que motivó el módulo entero: que las excepciones que el panel se traga a
propósito **dejen rastro**. Se comprueba en el caso más importante, el del
registro de auditoría, porque ahí la regla "no tumbar la petición" y la regla
"no callar el fallo" tiran en direcciones opuestas.
"""
from __future__ import annotations

import logging

import pytest

import audit
import logs

# ----------------------------------------------------------------------
# El nivel
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "valor, esperado",
    [
        (None, logging.INFO),
        ("DEBUG", logging.DEBUG),
        ("debug", logging.DEBUG),
        ("  WARNING  ", logging.WARNING),
        ("ERROR", logging.ERROR),
        ("CRITICAL", logging.CRITICAL),
    ],
)
def test_el_nivel_sale_del_entorno(valor, esperado: int) -> None:
    entorno = {} if valor is None else {"MUXSPACE_LOG_LEVEL": valor}
    assert logs.nivel_configurado(entorno) == esperado


@pytest.mark.parametrize("basura", ["verbose", "", "17bis", "sí"])
def test_un_nivel_mal_escrito_cae_a_info_y_no_revienta(basura: str) -> None:
    """Quedarse sin panel por una errata en una variable de diagnóstico sería
    un precio absurdo. Se cae a INFO, que es el valor por defecto."""
    assert logs.nivel_configurado({"MUXSPACE_LOG_LEVEL": basura}) == logging.INFO


def test_configurar_aplica_el_nivel_al_registrador_del_panel() -> None:
    logs.configurar({"MUXSPACE_LOG_LEVEL": "ERROR"})
    assert logging.getLogger("muxspace").level == logging.ERROR

    # Y es idempotente: volver a llamar no acumula estado raro.
    logs.configurar({"MUXSPACE_LOG_LEVEL": "DEBUG"})
    assert logging.getLogger("muxspace").level == logging.DEBUG


def test_los_registradores_del_panel_cuelgan_del_mismo_prefijo() -> None:
    """El prefijo es lo que permite subir el detalle del panel sin subir el de
    uvicorn ni el de las bibliotecas de terceros."""
    assert logs.obtener("audit").name == "muxspace.audit"
    assert logs.obtener("pty_bridge").name == "muxspace.pty_bridge"
    assert logs.obtener("audit").parent.name == "muxspace"


# ----------------------------------------------------------------------
# No duplicar bajo uvicorn
# ----------------------------------------------------------------------


def test_no_se_anade_manejador_si_la_raiz_ya_tiene_uno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso de producción: uvicorn ya configuró la raíz.

    Si `configurar()` añadiera el suyo igualmente, cada línea del panel saldría
    DOS veces en la consola. Es el error más común al meter logging en una app
    que corre dentro de un servidor, y no da ningún síntoma más que ruido.
    """
    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [logging.NullHandler()])

    logs.configurar({})

    assert len(raiz.handlers) == 1, (
        "se añadió un manejador sobre los que ya había: cada mensaje del panel "
        "saldría duplicado bajo uvicorn"
    )


def test_si_nadie_configuro_la_raiz_se_instala_un_manejador(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El caso de arrancar el backend a mano: sin esto no se vería nada."""
    raiz = logging.getLogger()
    monkeypatch.setattr(raiz, "handlers", [])

    logs.configurar({})

    assert raiz.handlers, "sin manejador, los mensajes no salen a ningún sitio"


def test_los_mensajes_del_panel_llegan_a_la_raiz(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Propagan, que es lo que hace que salgan por donde salen los de uvicorn."""
    logs.configurar({"MUXSPACE_LOG_LEVEL": "INFO"})
    with caplog.at_level(logging.INFO, logger="muxspace"):
        logs.obtener("prueba").info("hola")

    assert [r.getMessage() for r in caplog.records] == ["hola"]


# ----------------------------------------------------------------------
# Lo que motivó el módulo: los errores tragados dejan rastro
# ----------------------------------------------------------------------


def test_un_fallo_del_log_de_auditoria_se_avisa_pero_no_propaga(
    data_dir, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Las dos reglas a la vez, que es donde estaba el hueco.

    US-018 fijó que escribir el log de auditoría NUNCA tumba la acción que
    audita, y para eso se traga la excepción. El efecto secundario era un panel
    que cree estar auditando, no audita, y no lo dice: el peor de los mundos.
    Ahora se traga el error **y** lo cuenta.
    """
    def revienta(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit.os, "open", revienta)

    with caplog.at_level(logging.WARNING, logger="muxspace.audit"):
        audit.record("send-command", target="una-sesion")  # no debe lanzar

    avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert avisos, "el fallo del log de auditoría se quedó en silencio"
    assert "send-command" in avisos[0].getMessage(), (
        "el aviso no dice qué acción se perdió, que es lo único que lo hace útil"
    )
    assert avisos[0].exc_info, "sin la excepción no se sabe POR QUÉ falló"


def test_si_hasta_el_logging_falla_la_accion_sigue_adelante(
    data_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disco lleno y stderr cerrado a la vez: sigue sin poder tumbar nada.

    Es el `except` de dentro del `except`. Parece paranoia y es la diferencia
    entre un panel que aguanta un disco lleno y uno que devuelve 500 a todo.
    """
    def revienta(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit.os, "open", revienta)
    monkeypatch.setattr(
        audit._log, "warning", lambda *a, **k: (_ for _ in ()).throw(OSError("stderr"))
    )

    audit.record("send-command", target="una-sesion")  # no debe lanzar
