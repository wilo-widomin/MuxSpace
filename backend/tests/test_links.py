"""Enlaces generales: los del panel, que no pertenecen a ningún proyecto.

Validan igual que los de un proyecto (`_normalize_link`), y eso es lo que
más importa aquí: acaban en un `<a href>` del panel, así que un
`javascript:` guardado sería ejecución de código en la página.
"""
from __future__ import annotations


def test_el_ciclo_completo_por_la_api(client_auth) -> None:
    creado = client_auth.post(
        "/api/links", json={"title": "Forgejo", "url": "https://git.example/muxspace"}
    )
    assert creado.status_code == 201
    lid = creado.json()["id"]

    assert client_auth.get("/api/links").json() == [
        {"id": lid, "title": "Forgejo", "url": "https://git.example/muxspace"}
    ]

    actualizado = client_auth.put(
        f"/api/links/{lid}", json={"title": "Repo", "url": "https://git.example/otro"}
    )
    assert actualizado.status_code == 200
    assert actualizado.json()["title"] == "Repo"

    assert client_auth.delete(f"/api/links/{lid}").status_code == 200
    assert client_auth.get("/api/links").json() == []


def test_sin_esquema_se_asume_https(client_auth) -> None:
    creado = client_auth.post("/api/links", json={"title": "", "url": "github.com/foo"})

    assert creado.json()["url"] == "https://github.com/foo"
    # Sin título se usa el host: es lo que el usuario reconoce de un vistazo.
    assert creado.json()["title"] == "github.com"


def test_un_esquema_peligroso_se_rechaza(client_auth) -> None:
    """Prefijarle https a `javascript:alert(1)` lo convertiría en una URL
    válida; el store mira si ya hay `esquema:` antes de decidir."""
    r = client_auth.post(
        "/api/links", json={"title": "x", "url": "javascript:alert(1)"}
    )

    assert r.status_code == 400
    assert client_auth.get("/api/links").json() == []


def test_un_enlace_que_no_existe_da_404(client_auth) -> None:
    assert client_auth.put(
        "/api/links/nada", json={"title": "x", "url": "https://a.example"}
    ).status_code == 404
    assert client_auth.delete("/api/links/nada").status_code == 404


def test_los_enlaces_generales_no_son_los_del_proyecto(client_auth) -> None:
    """Comparten archivo y validación, pero son listas distintas: dar de alta
    uno general no puede aparecer como badge de un proyecto."""
    client_auth.post("/api/links", json={"title": "General", "url": "https://a.example"})
    proyecto = client_auth.post(
        "/api/projects",
        json={
            "title": "Panel",
            "cwd": "/srv",
            "commands": ["bun dev"],
            "links": [{"url": "https://b.example", "title": "Del proyecto"}],
        },
    ).json()

    assert [x["title"] for x in client_auth.get("/api/links").json()] == ["General"]
    assert [x["title"] for x in proyecto["links"]] == ["Del proyecto"]


def test_sin_cookie_no_se_ven_los_enlaces(client) -> None:
    assert client.get("/api/links").status_code == 401
