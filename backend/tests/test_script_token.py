"""El ciclo que hace un script del host con su secreto, sin sesión del panel.

El contrato de qué rutas abre está en `test_auth_contract.py`. Aquí se prueba
que esas rutas bastan para el trabajo real: crear un proyecto, lanzarlo y
borrarlo junto con su sesión y su espacio.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import main
import script_token
from tmux_service import TmuxSession


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Sustituye el tmux real del usuario por un conjunto de sesiones vivas."""
    vivas: set[str] = set()

    def crear(name, command=None, cwd=None):
        vivas.add(name)
        return True

    def matar(name):
        vivas.discard(name)
        return True

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "kill_session", matar)
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda: [TmuxSession(name=n, windows=1, attached=False) for n in sorted(vivas)],
    )
    return vivas


def _cabecera() -> dict[str, str]:
    return {main._SCRIPT_TOKEN_HEADER: script_token.script_token()}


def test_el_secreto_se_guarda_a_0600(client, data_dir: Path) -> None:
    """Lo crea el arranque: quien lo necesita es un script que lo lee."""
    ruta = data_dir / "script_token"
    assert ruta.read_text(encoding="utf-8").strip() == script_token.script_token()
    assert oct(ruta.stat().st_mode)[-3:] == "600"


def test_un_secreto_equivocado_no_autentica_ni_penaliza(
    client, data_dir: Path
) -> None:
    """No es un intento de contraseña: no debe bloquear el login de esa IP."""
    resp = client.get(
        "/api/projects", headers={main._SCRIPT_TOKEN_HEADER: "equivocado"}
    )

    assert resp.status_code == 401
    assert not (data_dir / "login_failures.json").exists()


def test_el_ciclo_completo_de_un_script(
    client, data_dir: Path, tmux_falso: set[str]
) -> None:
    """Crea, lanza y borra sin dejar proyecto, sesión ni espacio."""
    cabecera = _cabecera()
    proyecto = client.post(
        "/api/projects",
        headers=cabecera,
        json={
            "title": "MVPL-0411-1f1d6a7d",
            "cwd": "/tmp/entrevista",
            "commands": ["CLAUDIFY_PROJECT=mvp-lab-skills claude"],
        },
    ).json()

    sesion = client.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).json()["name"]

    assert sesion == "MVPL-0411-1f1d6a7d"
    vivas = client.get("/api/sessions", headers=cabecera).json()
    assert [(s["name"], s["project"]) for s in vivas] == [(sesion, proyecto["id"])]

    assert client.post(
        f"/api/kill-session/{sesion}", headers=cabecera
    ).json()["killed"] is True
    assert client.delete(
        f"/api/projects/{proyecto['id']}", headers=cabecera
    ).status_code == 200
    assert client.delete(
        f"/api/spaces/{proyecto['space']}", headers=cabecera
    ).status_code == 200

    assert client.get("/api/sessions", headers=cabecera).json() == []
    assert client.get("/api/projects", headers=cabecera).json() == []
    assert client.get("/api/spaces", headers=cabecera).json() == []


def test_lo_que_lanza_un_script_queda_auditado_como_script(
    client, data_dir: Path, tmux_falso: set[str]
) -> None:
    """Separa en el registro lo lanzado por un script de lo lanzado a mano."""
    cabecera = _cabecera()
    proyecto = client.post(
        "/api/projects",
        headers=cabecera,
        json={"title": "Auditado", "commands": ["true"]},
    ).json()
    client.post(f"/api/projects/{proyecto['id']}/run", headers=cabecera)

    entradas = [
        json.loads(linea)
        for linea in (data_dir / "audit.log").read_text(encoding="utf-8").splitlines()
    ]

    assert [e["user"] for e in entradas if e["action"] == "run-project"] == ["script"]
