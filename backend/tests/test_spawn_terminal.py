"""Otra terminal en el mismo directorio: el icono de la cabecera del tile.

Lo que hay que demostrar son tres cosas, y ninguna es que tmux funcione:

1. El **directorio** de la sesión nueva sale del panel de la vieja, no del
   cliente. Es lo que hace que el icono signifique "aquí mismo" y, de paso,
   lo que impide que el navegador pida una sesión en un directorio arbitrario.
2. El **nombre** se autoincrementa: `Terminal`, `Terminal (2)`… Sin esto el
   segundo clic chocaría contra el nombre del primero.
3. Una sesión que ya no existe da **404**, no una terminal suelta en el
   directorio equivocado.

tmux de verdad no participa: se sustituye por un conjunto de nombres vivos
que apunta el `cwd` con el que se creó cada uno.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import main
from tmux_service import TmuxError, TmuxSession


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """tmux sustituido por `nombre de sesión -> cwd con el que se creó`."""
    vivas: dict[str, str | None] = {}

    def crear(name, command=None, cwd=None):
        if name in vivas:
            return False
        vivas[name] = cwd
        return True

    def panel(name):
        if name not in vivas:
            raise TmuxError("err.session_not_found", {"name": name})
        # `path` es lo único que mira el endpoint; el resto va por completar
        # el contrato de `pane_info`.
        return {"path": vivas[name] or "", "command": "zsh", "alternate": "0"}

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "tmux_pane_info", panel)
    monkeypatch.setattr(main, "session_exists", lambda name: name in vivas)
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda: [
            TmuxSession(name=n, windows=1, attached=False) for n in sorted(vivas)
        ],
    )
    return vivas


def test_la_terminal_nueva_nace_en_el_directorio_de_la_vieja(
    client_no_auth, data_dir: Path, tmux_falso: dict[str, str | None]
) -> None:
    """El directorio no viaja desde el cliente: lo lee el servidor del panel."""
    tmux_falso["panel"] = "/home/usuario/proyectos/muxspace"

    respuesta = client_no_auth.post("/api/sessions/panel/spawn")

    assert respuesta.status_code == 200, respuesta.text
    nueva = respuesta.json()["name"]
    assert nueva == "Terminal"
    assert tmux_falso[nueva] == "/home/usuario/proyectos/muxspace"


def test_el_segundo_clic_no_choca_con_el_primero(
    client_no_auth, data_dir: Path, tmux_falso: dict[str, str | None]
) -> None:
    """El nombre se autoincrementa con el mismo sufijo que el resto del panel."""
    tmux_falso["panel"] = "/tmp/proyecto"

    nombres = [
        client_no_auth.post("/api/sessions/panel/spawn").json()["name"]
        for _ in range(3)
    ]

    assert nombres == ["Terminal", "Terminal (2)", "Terminal (3)"]
    assert all(tmux_falso[n] == "/tmp/proyecto" for n in nombres)


def test_una_sesion_que_ya_no_existe_da_404(
    client_no_auth, data_dir: Path, tmux_falso: dict[str, str | None]
) -> None:
    """El tile pudo quedarse pintado después de que la sesión muriera."""
    respuesta = client_no_auth.post("/api/sessions/fantasma/spawn")

    assert respuesta.status_code == 404, respuesta.text
    assert tmux_falso == {}


def test_sin_directorio_conocido_la_terminal_se_crea_igual(
    client_no_auth, data_dir: Path, tmux_falso: dict[str, str | None]
) -> None:
    """Quedarse sin terminal es peor que quedarse sin el `cd`."""
    tmux_falso["panel"] = None

    respuesta = client_no_auth.post("/api/sessions/panel/spawn")

    assert respuesta.status_code == 200, respuesta.text
    assert tmux_falso[respuesta.json()["name"]] is None
