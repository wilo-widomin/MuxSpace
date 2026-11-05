"""Cambiar proyectos o espacios avisa a las pestañas, por la vía que sea.

El panel solo carga esas listas al montar o tras una acción en esa pestaña: sin
aviso, lo que crea un script o lo que se edita en otro aparato no aparecería
hasta recargar. El aviso sale de los stores y no de las rutas para que ninguna
vía se lo salte.
"""
from __future__ import annotations

import json

import pytest

import events
import library_store
import space_store


@pytest.fixture
def publicados(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    tipos: list[str] = []
    monkeypatch.setattr(events, "publish", lambda evento: tipos.append(evento["type"]))
    return tipos


def test_cada_cambio_de_proyecto_avisa(publicados: list[str]) -> None:
    proyecto = library_store.add_project("Panel", "/srv", ["ls"])
    library_store.update_project(proyecto.id, "Otro", "/srv", ["ls"])
    library_store.delete_project(proyecto.id)

    assert publicados == ["projects-changed"] * 3


def test_lo_que_no_cambia_nada_no_avisa(publicados: list[str]) -> None:
    assert library_store.update_project("nada", "Otro", "/srv", ["ls"]) is None
    assert library_store.delete_project("nada") is False
    library_store.list_projects()

    assert publicados == []


def test_cada_cambio_de_espacio_avisa(publicados: list[str]) -> None:
    espacio = space_store.create_space("Clientes")
    space_store.update_space(espacio.id, "Otros")
    space_store.delete_space(espacio.id)

    assert publicados == ["spaces-changed"] * 3


def test_un_espacio_inexistente_no_avisa(publicados: list[str]) -> None:
    with pytest.raises(space_store.SpaceError):
        space_store.update_space("nada", "Otros")
    with pytest.raises(space_store.SpaceError):
        space_store.delete_space("nada")

    assert publicados == []


def test_buscar_un_espacio_que_ya_existe_no_avisa(publicados: list[str]) -> None:
    primero = space_store.get_or_create_space("Entrevistas")
    assert space_store.get_or_create_space(" entrevistas ") == primero

    assert publicados == ["spaces-changed"]
    assert len(space_store.list_spaces()) == 1


def test_el_aviso_llega_a_la_pestana_por_el_bus(client_auth) -> None:
    with client_auth.websocket_connect("/api/events") as ws:
        client_auth.post("/api/spaces", json={"title": "Clientes"})
        assert ws.receive_json() == {"type": "spaces-changed"}

        creado = client_auth.post(
            "/api/projects",
            json={"title": "Panel", "commands": ["ls"], "space": None},
        ).json()
        # Sin espacio elegido, el alta crea uno con el título del proyecto.
        assert ws.receive_json() == {"type": "spaces-changed"}
        assert ws.receive_json() == {"type": "projects-changed"}

        client_auth.delete(f"/api/projects/{creado['id']}")
        assert ws.receive_json() == {"type": "projects-changed"}


def test_un_proyecto_viejo_del_disco_no_es_del_token(data_dir) -> None:
    (data_dir / "library.json").write_text(
        json.dumps({
            "projects": [
                {"id": "a", "title": "Viejo", "commands": ["ls"]},
                # Un valor raro no puede dar permisos.
                {"id": "b", "title": "Raro", "commands": ["ls"], "script_owned": "si"},
                {"id": "c", "title": "Suyo", "commands": ["ls"], "script_owned": True},
            ]
        }),
        encoding="utf-8",
    )

    assert [p.script_owned for p in library_store.list_projects()] == [
        False, False, True,
    ]
