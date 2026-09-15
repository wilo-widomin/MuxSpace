"""La lupa del tile: qué nombres de sesión acepta la ruta del transcript.

El fallo que esto fija: la ruta filtraba el nombre con `_SESSION_NAME_RE`, el
filtro estricto de `/api/create-session` (solo letras, números, `-` y `_`).
Pero las terminales que nace de un tile se llaman `Terminal (2)`, con espacio
y paréntesis, así que la lupa devolvía 400 "nombre inválido" justo en las
sesiones más comunes del panel.
"""
from __future__ import annotations

import pytest

import main
from tmux_service import TmuxError


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """tmux sustituido por `nombre de sesión -> cwd del panel`."""
    vivas: dict[str, str] = {"Terminal (2)": "", "claude-uno": ""}

    def panel(name):
        if name not in vivas:
            raise TmuxError("err.session_not_found", {"name": name})
        return {"path": vivas[name], "command": "zsh", "alternate": "0"}

    monkeypatch.setattr(main, "tmux_pane_info", panel)
    return vivas


def test_la_lupa_funciona_en_una_terminal_desduplicada(client_auth, tmux_falso) -> None:
    """`Terminal (2)` es un nombre legítimo: lo pone el propio panel."""
    resp = client_auth.get("/api/terminal/Terminal%20(2)/transcript")

    assert resp.status_code == 200, resp.text
    # Sin proyecto en el panel no hay transcript, pero la respuesta es la del
    # caso normal, no un error de validación.
    assert resp.json() == {"available": False, "reason": "no_project", "messages": []}


def test_una_sesion_que_no_existe_da_404(client_auth, tmux_falso) -> None:
    """El nombre pasa el filtro y es tmux quien dice que no está."""
    resp = client_auth.get("/api/terminal/fantasma/transcript")

    assert resp.status_code == 404


def test_un_nombre_desmesurado_se_rechaza(client_auth, tmux_falso) -> None:
    """Lo que sí se acota es lo que puede crecer sin límite."""
    largo = "s" * (main._MAX_ATTENTION_NAME + 1)

    resp = client_auth.get(f"/api/terminal/{largo}/transcript")

    assert resp.status_code == 400
    detalle = resp.json()["detail"]
    assert detalle["code"] == "err.session_name_invalid"
    # El nombre viaja como parámetro a interpolar, no como texto técnico: si se
    # cuela en `technical` el panel pinta "([object Object])" detrás del error.
    assert detalle["params"]["name"] == largo[:80]
    assert "technical" not in detalle
