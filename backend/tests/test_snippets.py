"""Textos rápidos: lo que se escribe en la terminal sin ejecutarlo.

La API es un CRUD y nada más. No hay endpoint de "enviar" a propósito: el
texto lo escribe el navegador en la terminal con foco, porque mandarlo por
el backend obligaría a decidir aquí si lleva Enter, y todo el sentido de
esto es que no lo lleve.
"""
from __future__ import annotations


def test_el_ciclo_completo_por_la_api(client_auth) -> None:
    creado = client_auth.post(
        "/api/snippets", json={"label": "Revisar", "text": "/code-review high"}
    )
    assert creado.status_code == 201
    sid = creado.json()["id"]

    assert client_auth.get("/api/snippets").json() == [
        {"id": sid, "label": "Revisar", "text": "/code-review high"}
    ]

    actualizado = client_auth.put(
        f"/api/snippets/{sid}",
        json={"label": "Revisar a fondo", "text": "/code-review max"},
    )
    assert actualizado.status_code == 200
    assert actualizado.json()["label"] == "Revisar a fondo"

    assert client_auth.delete(f"/api/snippets/{sid}").status_code == 200
    assert client_auth.get("/api/snippets").json() == []


def test_un_texto_rapido_que_no_existe_da_404(client_auth) -> None:
    assert client_auth.put(
        "/api/snippets/nada", json={"label": "x", "text": "y"}
    ).status_code == 404
    assert client_auth.delete("/api/snippets/nada").status_code == 404


def test_un_texto_vacio_se_rechaza_con_el_error_traducible(client_auth) -> None:
    r = client_auth.post("/api/snippets", json={"label": "x", "text": "  "})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "err.snippet_empty"


def test_los_saltos_de_linea_llegan_intactos(client_auth) -> None:
    """Un texto rápido de varias líneas es el caso que justifica la feature:
    lo que se teclea a mano en una tableta y no cabe en un comando."""
    texto = "primera línea\nsegunda línea"
    creado = client_auth.post("/api/snippets", json={"label": "", "text": texto})

    assert creado.json()["text"] == texto
    assert creado.json()["label"] == "primera línea", "la etiqueta es solo la primera"


def test_sin_cookie_no_se_ven_los_textos_rapidos(client) -> None:
    assert client.get("/api/snippets").status_code == 401
