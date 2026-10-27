"""Al crear o renombrar una sesión, lo que tmux no admite pasa a '-'.

El fallo que esto fija: renombrar una terminal a «mi terminal» devolvía 400
«nombre inválido» porque el espacio no casa `_SESSION_NAME_RE`. Ahora cada
tramo de caracteres prohibidos se convierte en un solo '-'.
"""
from __future__ import annotations

import pytest

import main


@pytest.mark.parametrize(
    ("tecleado", "esperado"),
    [
        ("mi terminal", "mi-terminal"),
        ("Terminal (2)", "Terminal-2"),
        ("a/b\\c", "a-b-c"),
        ("diseño web", "dise-o-web"),
        ("v1.2:prod$", "v1-2-prod"),
        ("ya_valido-1", "ya_valido-1"),
    ],
)
def test_los_caracteres_prohibidos_pasan_a_guion(tecleado: str, esperado: str) -> None:
    assert main._slug_session_name(tecleado) == esperado


def test_renombrar_con_espacios_ya_no_da_400(client_auth, monkeypatch) -> None:
    renombradas: list[tuple[str, str]] = []
    monkeypatch.setattr(main, "session_exists", lambda name: name == "vieja")
    monkeypatch.setattr(
        main, "rename_session", lambda old, new: renombradas.append((old, new))
    )

    resp = client_auth.post(
        "/api/rename-session/vieja", json={"new_name": "  mi terminal nueva "}
    )

    assert resp.status_code == 200, resp.text
    assert renombradas == [("vieja", "mi-terminal-nueva")]


def test_un_nombre_solo_de_prohibidos_sigue_siendo_invalido(client_auth) -> None:
    resp = client_auth.post("/api/rename-session/vieja", json={"new_name": " ()  "})

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "err.session_name_invalid"
