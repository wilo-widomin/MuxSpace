"""Dónde está trabajando cada terminal, en el listado de sesiones.

El panel enseña el directorio del panel activo en el tooltip del nombre del
tile. Lo que hay que demostrar aquí es lo del backend: que el dato viaja en
`/api/sessions` (o sea, en el mismo sondeo que ya existía) y que sale
abreviado con `~`, porque el navegador no sabe cuál es el home del usuario
que corre el backend y sin eso pintaría la ruta larga entera.

tmux no participa: `list_sessions` se sustituye por sesiones ya construidas.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import main
from tmux_service import TmuxSession


def _con_sesiones(monkeypatch: pytest.MonkeyPatch, *sesiones: TmuxSession) -> None:
    monkeypatch.setattr(main, "list_sessions", lambda: list(sesiones))


def test_el_listado_dice_el_directorio_y_el_programa_de_cada_sesion(
    client_no_auth, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sale del `list-sessions` del sondeo, sin una llamada extra por sesión."""
    home = str(Path.home())
    _con_sesiones(
        monkeypatch,
        TmuxSession(
            name="panel",
            windows=1,
            attached=False,
            cwd=f"{home}/proyectos/muxspace",
            command="claude",
        ),
    )

    sesiones = client_no_auth.get("/api/sessions").json()

    assert sesiones[0]["cwd"] == "~/proyectos/muxspace"
    assert sesiones[0]["command"] == "claude"


def test_una_ruta_fuera_del_home_viaja_entera(
    client_no_auth, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`~` es una abreviatura, no un recorte: lo de fuera no se toca.

    Y un prefijo que solo COINCIDE con el home (`/home/willyx`) no es el home:
    abreviarlo daría una ruta que no existe.
    """
    home = str(Path.home())
    _con_sesiones(
        monkeypatch,
        TmuxSession(name="raiz", windows=1, attached=False, cwd="/etc"),
        TmuxSession(name="justo", windows=1, attached=False, cwd=home),
        TmuxSession(name="parecido", windows=1, attached=False, cwd=home + "x/cosas"),
        TmuxSession(name="sin-dato", windows=1, attached=False),
    )

    por_nombre = {s["name"]: s for s in client_no_auth.get("/api/sessions").json()}

    assert por_nombre["raiz"]["cwd"] == "/etc"
    assert por_nombre["justo"]["cwd"] == "~"
    assert por_nombre["parecido"]["cwd"] == home + "x/cosas"
    assert por_nombre["sin-dato"]["cwd"] is None
