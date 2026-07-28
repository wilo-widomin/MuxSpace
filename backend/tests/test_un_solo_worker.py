"""El aviso de "más de un worker" (US-023).

El panel solo puede correr con un worker: los stores usan `threading.Lock`,
que no cruza procesos, y reescriben su JSON entero en cada mutación. Con dos
workers se pierden datos **en silencio**, que es el peor modo de fallo que
hay: sin excepción, sin log y sin 500.

Lo que se prueba aquí es el detector. No es una comprobación de adorno: la
tabla del final de `docs/un-solo-worker.md` se midió arrancando uvicorn de
verdad en los cuatro modos, y estos tests congelan ese resultado para que
nadie lo "simplifique" a `multiprocessing.parent_process()` —que es lo obvio
y da un falso positivo con `--reload`— sin que se ponga rojo algo.

Los `argv` de abajo son los que se observaron **en el proceso hijo** de
uvicorn, no los que se teclean: `multiprocessing.spawn` restaura el `sys.argv`
del padre en el hijo, y por eso la bandera llega hasta aquí.
"""
from __future__ import annotations

import logging

import pytest

import main

# Prefijo real de un worker de uvicorn arrancado con `python -m uvicorn`.
_UVICORN = [
    "/opt/muxspace/backend/venv/lib/python3.11/site-packages/uvicorn/__main__.py",
    "main:app",
    "--app-dir",
    "backend",
    "--host",
    "127.0.0.1",
    "--port",
    "8000",
]


# ----------------------------------------------------------------------
# El detector
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra, entorno, esperado, motivo",
    [
        ([], {}, 1, "arranque limpio: nadie pidió workers"),
        (["--workers", "1"], {}, 1, "el explícito de start.sh"),
        (["--workers", "4"], {}, 4, "la bandera larga separada"),
        (["--workers=4"], {}, 4, "la bandera larga con ="),
        (["-w", "3"], {}, 3, "la corta (gunicorn y uvicorn)"),
        ([], {"WEB_CONCURRENCY": "8"}, 8, "sin bandera: uvicorn usa el entorno"),
        (
            ["--workers", "1"],
            {"WEB_CONCURRENCY": "8"},
            1,
            "la bandera gana al entorno, igual que en uvicorn",
        ),
        (["--reload"], {}, 1, "desarrollo: subproceso, pero UN worker"),
    ],
)
def test_cuantos_workers_se_pidieron(
    extra: list[str], entorno: dict[str, str], esperado: int, motivo: str
) -> None:
    assert main._workers_configurados(_UVICORN + extra, entorno) == esperado, motivo


@pytest.mark.parametrize("basura", ["hola", "", "-1x", "2.5"])
def test_un_valor_que_no_es_un_numero_no_tumba_el_arranque(basura: str) -> None:
    """Quejarse de `--workers hola` es trabajo de uvicorn, no nuestro.

    Lo que no puede pasar es que el panel reviente en el `lifespan` por un
    argumento que además va a rechazar el propio uvicorn un instante después.
    """
    assert main._workers_configurados(_UVICORN + ["--workers", basura], {}) == 1
    assert main._workers_configurados(_UVICORN, {"WEB_CONCURRENCY": basura}) == 1


def test_una_bandera_sin_valor_al_final_no_revienta() -> None:
    """`--workers` como último argumento: no hay `argv[i+1]` que leer."""
    assert main._workers_configurados(_UVICORN + ["--workers"], {}) == 1


def test_reload_no_se_confunde_con_varios_workers() -> None:
    """El falso positivo que descarta `multiprocessing.parent_process()`.

    `--reload` levanta el servidor en un subproceso con UN worker, así que
    `parent_process()` devuelve algo. Si el detector se apoyara en eso,
    avisaría de una corrupción inexistente cada vez que alguien desarrolla, y
    un aviso que salta siempre deja de leerse. Está en su propio test, y no
    solo en el `parametrize`, porque es la razón de que el detector mire
    `argv` y no lo evidente.
    """
    assert main._workers_configurados(_UVICORN + ["--reload"], {}) == 1


# ----------------------------------------------------------------------
# El aviso
# ----------------------------------------------------------------------


@pytest.fixture
def app_arrancada(data_dir, monkeypatch: pytest.MonkeyPatch):
    """Arranca la app (ejecuta el `lifespan`) con el argv/entorno que se pida.

    Depende de `data_dir` porque el `lifespan` hace `harden_tree` sobre el
    directorio de datos: sin el aislamiento, abrir el TestClient cambiaría
    los permisos de los ficheros reales del usuario.
    """
    from fastapi.testclient import TestClient

    def arrancar(extra: list[str], entorno: dict[str, str] | None = None):
        monkeypatch.setattr(main.sys, "argv", _UVICORN + extra)
        # Se limpia siempre antes de poner lo que pida el test: si quien corre
        # la suite tiene `WEB_CONCURRENCY` exportado, los tests del caso "un
        # solo worker" fallarían por su entorno y no por el código.
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
        for k, v in (entorno or {}).items():
            monkeypatch.setenv(k, v)
        with TestClient(main.app):
            pass

    return arrancar


def test_con_un_worker_no_se_avisa_de_nada(
    app_arrancada, caplog: pytest.LogCaptureFixture
) -> None:
    """Un aviso que sale siempre no es un aviso, es ruido de arranque."""
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        app_arrancada(["--workers", "1"])

    assert "workers" not in caplog.text.lower()


def test_con_varios_workers_se_avisa_y_se_dice_que_se_corrompe(
    app_arrancada, caplog: pytest.LogCaptureFixture
) -> None:
    """El criterio de la historia: no puede pasar en silencio.

    Y el aviso tiene que decir QUÉ se rompe. "Puede haber problemas" se
    ignora; "se corrompe la biblioteca de comandos" se lee.
    """
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        app_arrancada(["--workers", "4"])

    (aviso,) = [r for r in caplog.records if r.levelno >= logging.WARNING]
    texto = aviso.getMessage()
    assert "4" in texto, "el aviso no dice cuántos workers detectó"
    assert "corrompe" in texto, "el aviso no dice qué se rompe"
    assert "docs/un-solo-worker.md" in texto, "el aviso no lleva a la explicación"


def test_web_concurrency_en_el_entorno_tambien_dispara_el_aviso(
    app_arrancada, caplog: pytest.LogCaptureFixture
) -> None:
    """La forma silenciosa de romperlo: un `export` heredado, sin banderas.

    Es el caso que de verdad justifica el aviso. Nadie escribe `--workers 4`
    sin querer; `WEB_CONCURRENCY` sí se hereda de un `.bashrc` o de un
    contenedor y arranca cuatro workers sin que se haya tocado `start.sh`.
    """
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        app_arrancada([], {"WEB_CONCURRENCY": "4"})

    assert any(r.levelno >= logging.WARNING for r in caplog.records)
