"""Avisos de atención: quién puede marcar, qué se ve y cuándo se apaga.

Lo que aquí se protege es el comportamiento que el usuario nota: que el aviso
sobreviva a cerrar el tile o recargar la página (por eso está en el servidor y
sale en el listado), que apagarlo en un sitio lo apague en todos (por eso hay
un solo pendiente por sesión), y que el secreto del hook autorice a marcar
pero no a nada más.

El tmux de verdad no participa: se sustituye por un conjunto de nombres.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest

import attention_store
import main
from tmux_service import TmuxSession


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Sustituye tmux por un conjunto de nombres de sesión vivos."""
    vivas: set[str] = {"claude-uno", "claude-dos"}
    monkeypatch.setattr(main, "session_exists", lambda name: name in vivas)
    monkeypatch.setattr(main, "kill_session", lambda name: vivas.discard(name) is None)
    monkeypatch.setattr(main, "rename_session", lambda old, new: None)
    monkeypatch.setattr(
        main,
        "list_sessions",
        lambda: [TmuxSession(name=n, windows=1, attached=False) for n in sorted(vivas)],
    )
    return vivas


def _cabecera_hook() -> dict[str, str]:
    return {main._HOOK_TOKEN_HEADER: attention_store.hook_token()}


def test_el_hook_marca_con_el_secreto_del_host(client, tmux_falso):
    """El que marca no tiene cookie: se identifica con el secreto del host."""
    resp = client.post(
        "/api/attention/claude-uno",
        json={"label": "espera tu respuesta"},
        headers=_cabecera_hook(),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["label"] == "espera tu respuesta"
    assert resp.json()["at"] > 0


def test_sin_secreto_ni_sesion_no_se_puede_marcar(client, tmux_falso):
    """Marcar es escribir en el panel: no está abierto a cualquiera."""
    resp = client.post("/api/attention/claude-uno")
    assert resp.status_code == 401
    assert attention_store.get("claude-uno") is None


def test_un_secreto_equivocado_no_vale(client, tmux_falso):
    resp = client.post(
        "/api/attention/claude-uno", headers={main._HOOK_TOKEN_HEADER: "no-es"}
    )
    assert resp.status_code == 401


def test_el_aviso_sale_en_el_listado_de_sesiones(client_auth, tmux_falso):
    """Es lo que hace que el aviso sobreviva a recargar la página.

    Una pestaña que se abre media hora después no vio pasar ningún evento:
    todo lo que sabe lo saca de aquí.
    """
    client_auth.post("/api/attention/claude-uno", headers=_cabecera_hook())

    sesiones = {s["name"]: s for s in client_auth.get("/api/sessions").json()}
    assert sesiones["claude-uno"]["attention"] is not None
    assert sesiones["claude-dos"]["attention"] is None


def test_marcar_dos_veces_no_acumula_avisos(client_auth, tmux_falso):
    """La marca es un estado, no una cola: se refresca, no se apila."""
    client_auth.post(
        "/api/attention/claude-uno", json={"label": "uno"}, headers=_cabecera_hook()
    )
    primero = attention_store.get("claude-uno")
    client_auth.post(
        "/api/attention/claude-uno", json={"label": "dos"}, headers=_cabecera_hook()
    )
    segundo = attention_store.get("claude-uno")

    assert segundo.label == "dos"
    assert segundo.at >= primero.at

    client_auth.delete("/api/attention/claude-uno")
    assert attention_store.get("claude-uno") is None


def test_apagar_una_marca_que_no_existe_no_es_un_error(client_auth, tmux_falso):
    """Lo llama cada tecleo en un tile: un 404 aquí sería ruido constante."""
    resp = client_auth.delete("/api/attention/claude-dos")
    assert resp.status_code == 200


def test_apagar_todas(client_auth, tmux_falso):
    for nombre in ("claude-uno", "claude-dos"):
        client_auth.post(f"/api/attention/{nombre}", headers=_cabecera_hook())

    assert client_auth.delete("/api/attention").status_code == 200
    assert attention_store.pending() == {}


def test_el_hook_no_puede_apagar_ni_listar(client, tmux_falso):
    """El secreto autoriza a marcar y nada más.

    Si además apagara, un hook con el secreto filtrado podría silenciar los
    avisos de los demás; y el listado de sesiones es información del panel.
    """
    assert client.delete(
        "/api/attention/claude-uno", headers=_cabecera_hook()
    ).status_code == 401
    assert client.get("/api/sessions", headers=_cabecera_hook()).status_code == 401


def test_matar_la_sesion_olvida_su_aviso(client_auth, tmux_falso):
    """Un nombre reutilizado no nace reclamando lo de la sesión anterior."""
    client_auth.post("/api/attention/claude-uno", headers=_cabecera_hook())
    client_auth.post("/api/kill-session/claude-uno")

    assert attention_store.get("claude-uno") is None


def test_renombrar_arrastra_el_aviso(client_auth, tmux_falso):
    """Renombrar no es atender: la marca sigue, con el nombre nuevo."""
    client_auth.post("/api/attention/claude-uno", headers=_cabecera_hook())
    resp = client_auth.post(
        "/api/rename-session/claude-uno", json={"new_name": "claude-tres"}
    )
    assert resp.status_code == 200, resp.text

    assert attention_store.get("claude-uno") is None
    assert attention_store.get("claude-tres") is not None


def test_la_etiqueta_larga_se_recorta_en_vez_de_fallar(client_auth, tmux_falso):
    """Un hook no debe romperse por pasarse de largo en un texto."""
    resp = client_auth.post(
        "/api/attention/claude-uno",
        json={"label": "x" * 500},
        headers=_cabecera_hook(),
    )
    assert resp.status_code == 200
    assert len(resp.json()["label"]) == attention_store.MAX_LABEL


def test_un_nombre_con_espacios_y_acentos_llega_entero(client, tmux_falso):
    """Los nombres de sesión NO son slugs.

    Los que nacen de un proyecto o de un comando llevan espacios, paréntesis
    y acentos («Terminal (2)»), y el aviso tiene que quedar apuntado a ese
    nombre exacto: si se guardara por una versión codificada, el listado
    nunca casaría y la marca no aparecería en ninguna parte.
    """
    nombre = "Prueba ñandú (2)"
    resp = client.post(
        f"/api/attention/{quote(nombre)}", headers=_cabecera_hook()
    )
    assert resp.status_code == 200, resp.text
    assert attention_store.get(nombre) is not None


def test_el_secreto_se_guarda_a_0600(client, data_dir):
    """Lo lee el hook, que corre como el usuario; nadie más en la máquina."""
    attention_store.hook_token()
    ruta = data_dir / "attention_token"
    assert ruta.exists()
    assert oct(ruta.stat().st_mode)[-3:] == "600"


def test_el_bus_empuja_el_aviso_a_las_pestanas(client_auth, tmux_falso):
    """El WebSocket de eventos es lo que avisa con la pestaña oculta.

    El sondeo del listado se para cuando el navegador esconde la pestaña, así
    que sin esto el aviso llegaría justo cuando ya no hace falta.
    """
    with client_auth.websocket_connect("/api/events") as ws:
        client_auth.post(
            "/api/attention/claude-uno",
            json={"label": "te espera"},
            headers=_cabecera_hook(),
        )
        evento = ws.receive_json()
        assert evento["type"] == "attention"
        assert evento["session"] == "claude-uno"
        assert evento["attention"]["label"] == "te espera"

        client_auth.delete("/api/attention/claude-uno")
        apagado = ws.receive_json()
        assert apagado["session"] == "claude-uno"
        assert apagado["attention"] is None


def test_el_bus_no_acepta_a_quien_no_ha_entrado(client):
    """Los eventos dicen qué sesiones existen: es información del panel."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/events") as ws:
            ws.receive_json()
