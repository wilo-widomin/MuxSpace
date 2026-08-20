"""Enlaces de un proyecto: del modal a la cabecera de la terminal.

Un proyecto puede llevar una lista de enlaces (URL + título) que el panel
pinta como badges en la cabecera de sus terminales. Para saber QUÉ badges
tocan en cada terminal hace falta el vínculo `sesión -> proyecto`, y estos
tests recorren ese camino entero por la API: guardar los enlaces, lanzar el
proyecto y comprobar que el listado de sesiones dice de qué proyecto salió
cada una.

El tmux de verdad no participa: se sustituye por un conjunto de nombres en
memoria, porque lo que se verifica aquí es el vínculo, no tmux.
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

    def renombrar(old, new):
        vivas.discard(old)
        vivas.add(new)

    def matar(name):
        habia = name in vivas
        vivas.discard(name)
        return habia

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "session_exists", lambda name: name in vivas)
    monkeypatch.setattr(main, "rename_session", renombrar)
    monkeypatch.setattr(main, "kill_session", matar)
    monkeypatch.setattr(main, "send_command", lambda name, cmd: None)
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda: [TmuxSession(name=n, windows=1, attached=False) for n in sorted(vivas)],
    )
    return vivas


def crear_proyecto(client, links: list[dict]) -> str:
    respuesta = client.post(
        "/api/projects",
        json={"title": "Panel", "cwd": None, "commands": ["bun dev"], "links": links},
    )
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["id"]


def test_los_enlaces_van_y_vuelven_por_la_api(client_no_auth, data_dir: Path) -> None:
    """El control positivo: lo que guarda el modal es lo que lee el panel."""
    crear_proyecto(client_no_auth, [{"url": "https://ok.example", "title": "Panel"}])

    proyectos = client_no_auth.get("/api/projects").json()

    assert proyectos[0]["links"] == [{"url": "https://ok.example", "title": "Panel"}]


def test_un_enlace_peligroso_devuelve_400_y_no_guarda_nada(
    client_no_auth, data_dir: Path
) -> None:
    """Y el proyecto entero se rechaza: no se guarda a medias sin el enlace."""
    respuesta = client_no_auth.post(
        "/api/projects",
        json={
            "title": "Panel",
            "cwd": None,
            "commands": ["bun dev"],
            "links": [{"url": "javascript:alert(1)", "title": "Malo"}],
        },
    )

    assert respuesta.status_code == 400
    assert respuesta.json()["detail"]["code"] == "err.project_link_invalid"
    assert client_no_auth.get("/api/projects").json() == []


def test_la_sesion_lanzada_dice_de_que_proyecto_salio(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """Sin este id, la cabecera no sabría qué badges pintar en cada tile."""
    project_id = crear_proyecto(client_no_auth, [{"url": "https://ok.example"}])

    creada = client_no_auth.post(f"/api/projects/{project_id}/run")
    assert creada.status_code == 200, creada.text
    nombre = creada.json()["name"]

    sesiones = client_no_auth.get("/api/sessions").json()

    assert [(s["name"], s["project"]) for s in sesiones] == [(nombre, project_id)]


def test_una_sesion_creada_a_mano_no_tiene_proyecto(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """El control negativo: `project` es None, no el de la última lanzada."""
    creada = client_no_auth.post("/api/create-session/suelta")
    assert creada.status_code == 200, creada.text

    sesiones = client_no_auth.get("/api/sessions").json()

    assert [(s["name"], s["project"]) for s in sesiones] == [("suelta", None)]


def test_una_sesion_vieja_se_reconoce_por_el_nombre(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """El plan B: sin vínculo guardado, se casa el nombre con el título.

    Las sesiones que ya existían antes de esta función no tienen entrada en
    `session_projects`, y sin este apaño sus terminales no enseñarían nunca
    los enlaces de su proyecto. El sufijo ` (N)` de las repetidas se ignora,
    que es justo lo que las hace del mismo proyecto.
    """
    project_id = crear_proyecto(client_no_auth, [{"url": "https://ok.example"}])
    tmux_falso.update({"Panel", "Panel (2)", "Otra cosa"})

    sesiones = client_no_auth.get("/api/sessions").json()

    assert {s["name"]: s["project"] for s in sesiones} == {
        "Panel": project_id,
        "Panel (2)": project_id,
        "Otra cosa": None,
    }


def test_el_vinculo_guardado_manda_sobre_el_nombre(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """Si no, renombrar una sesión lanzada la devolvería al proyecto viejo.

    `Panel` renombrada a `Otro nombre` conserva su proyecto por el vínculo,
    y la `Panel` nueva que alguien cree a mano no lo hereda por el nombre...
    salvo que el plan B diga lo contrario, que es exactamente lo que aquí se
    fija: el vínculo explícito se consulta primero.
    """
    project_id = crear_proyecto(client_no_auth, [{"url": "https://ok.example"}])
    nombre = client_no_auth.post(f"/api/projects/{project_id}/run").json()["name"]
    client_no_auth.post(
        f"/api/rename-session/{nombre}", json={"new_name": "otro-nombre"}
    )

    sesiones = {s["name"]: s["project"] for s in client_no_auth.get("/api/sessions").json()}

    assert sesiones == {"otro-nombre": project_id}


def test_renombrar_la_sesion_no_le_quita_los_enlaces(
    client_no_auth, data_dir: Path, tmux_falso: set[str]
) -> None:
    """El motivo de guardar el vínculo en vez de deducirlo del nombre."""
    project_id = crear_proyecto(client_no_auth, [{"url": "https://ok.example"}])
    nombre = client_no_auth.post(f"/api/projects/{project_id}/run").json()["name"]

    renombrada = client_no_auth.post(
        f"/api/rename-session/{nombre}", json={"new_name": "otra-cosa"}
    )
    assert renombrada.status_code == 200, renombrada.text

    sesiones = client_no_auth.get("/api/sessions").json()

    assert [(s["name"], s["project"]) for s in sesiones] == [("otra-cosa", project_id)]
