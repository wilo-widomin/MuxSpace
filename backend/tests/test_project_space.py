"""El espacio de un proyecto: del formulario a la sesión lanzada.

Un proyecto guarda a qué espacio van sus sesiones. Ese id es lo que la
extensión del navegador mete en `?space=` al abrir el grupo de pestañas, así
que tiene que llegar entero por la API y tiene que ser el espacio en el que
de verdad aparece la sesión al lanzar el proyecto.

El tmux de verdad no participa: aquí se verifica el vínculo, no tmux.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import main
from tmux_service import TmuxSession


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Sustituye tmux por un conjunto de nombres de sesión vivos."""
    vivas: set[str] = set()

    def crear(name, command=None, cwd=None):
        if name in vivas:
            return False
        vivas.add(name)
        return True

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "session_exists", lambda name: name in vivas)
    monkeypatch.setattr(main, "send_command", lambda name, cmd: None)
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda: [TmuxSession(name=n, windows=1, attached=False) for n in sorted(vivas)],
    )
    return vivas


def crear_proyecto(client, **extra) -> dict:
    cuerpo = {"title": "Panel", "cwd": None, "commands": ["bun dev"]}
    cuerpo.update(extra)
    respuesta = client.post("/api/projects", json=cuerpo)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_sin_espacio_el_alta_crea_uno_con_el_nombre_del_proyecto(
    client_no_auth, data_dir: Path
) -> None:
    """Es lo que anuncia el formulario de alta."""
    proyecto = crear_proyecto(client_no_auth)

    espacios = client_no_auth.get("/api/spaces").json()

    assert [(e["id"], e["title"]) for e in espacios] == [
        (proyecto["space"], "Panel")
    ]


def test_el_espacio_elegido_se_respeta_y_no_crea_otro(
    client_no_auth, data_dir: Path
) -> None:
    """El control negativo del anterior: elegir uno no inventa un segundo."""
    existente = client_no_auth.post("/api/spaces", json={"title": "Clientes"}).json()

    proyecto = crear_proyecto(client_no_auth, space=existente["id"])

    assert proyecto["space"] == existente["id"]
    assert [e["title"] for e in client_no_auth.get("/api/spaces").json()] == [
        "Clientes"
    ]


def test_un_proyecto_invalido_no_deja_el_espacio_huerfano(
    client_no_auth, data_dir: Path
) -> None:
    """El espacio se crea antes que el proyecto; si este falla, se deshace."""
    respuesta = client_no_auth.post(
        "/api/projects",
        json={"title": "Panel", "cwd": None, "commands": []},
    )

    assert respuesta.status_code == 400
    assert client_no_auth.get("/api/spaces").json() == []


def test_el_espacio_se_puede_cambiar_desde_la_edicion(
    client_no_auth, data_dir: Path
) -> None:
    proyecto = crear_proyecto(client_no_auth)
    otro = client_no_auth.post("/api/spaces", json={"title": "Otro"}).json()

    actualizado = client_no_auth.put(
        f"/api/projects/{proyecto['id']}",
        json={
            "title": "Panel",
            "cwd": None,
            "commands": ["bun dev"],
            "space": otro["id"],
        },
    )

    assert actualizado.status_code == 200, actualizado.text
    assert actualizado.json()["space"] == otro["id"]


def test_la_sesion_lanzada_nace_en_el_espacio_del_proyecto(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """Sin esto, abrir `?space=<id>` enseñaría un espacio vacío."""
    proyecto = crear_proyecto(client_no_auth)

    creada = client_no_auth.post(f"/api/projects/{proyecto['id']}/run")
    assert creada.status_code == 200, creada.text
    nombre = creada.json()["name"]

    sesiones = client_no_auth.get("/api/sessions").json()

    assert [(s["name"], s["space"]) for s in sesiones] == [
        (nombre, proyecto["space"])
    ]


def test_un_espacio_borrado_deja_el_proyecto_sin_espacio(
    client_no_auth, data_dir: Path
) -> None:
    """Un id muerto abriría un espacio fantasma: se devuelve null."""
    proyecto = crear_proyecto(client_no_auth)

    client_no_auth.delete(f"/api/spaces/{proyecto['space']}")

    assert client_no_auth.get("/api/projects").json()[0]["space"] is None
