"""Apagar el host desde el panel: nunca se apaga nada y nunca se sale a la red.

`host_poweroff.send` es lo único que habla con el agente, y los tests lo
sustituyen por un registro. El cliente real (`send`) se prueba solo contra un
servidor en 127.0.0.1 con la orden de apagado también sustituida.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
import host_poweroff
import script_token
from errors import AppError

URL = "/api/host/poweroff"
PALABRA = host_poweroff.CONFIRMATION_WORD


@pytest.fixture
def habilitado(monkeypatch):
    monkeypatch.setattr(config, "HOST_POWEROFF_URL", "http://agente.invalid/poweroff")
    monkeypatch.setattr(config, "HOST_POWEROFF_TOKEN", "t" * 40)


@pytest.fixture
def envios(monkeypatch):
    """Registro de pedidos de apagado: lo que habría salido hacia el host."""
    registro: list[str] = []
    monkeypatch.setattr(host_poweroff, "send", lambda: registro.append("poweroff"))
    return registro


@pytest.fixture
def cabecera() -> dict[str, str]:
    return {"X-Muxspace-Script-Token": script_token.generate()[0]}


def _auditoria(data_dir: Path) -> list[dict]:
    ruta = data_dir / "audit.log"
    if not ruta.exists():
        return []
    todas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]
    return [e for e in todas if e["action"] == "host-poweroff"]


def test_sin_sesion_es_401_y_no_se_envia_nada(client, habilitado, envios):
    r = client.post(URL, json={"confirmation": PALABRA})
    assert r.status_code == 401
    assert envios == []


def test_capacidades_sin_sesion_es_401(client):
    assert client.get("/api/capabilities").status_code == 401


def test_capacidad_ausente_responde_que_no_esta_habilitado(
    client_auth, envios, data_dir
):
    assert client_auth.get("/api/capabilities").json() == {
        "host_poweroff": False,
        "host_poweroff_word": None,
    }
    r = client_auth.post(URL, json={"confirmation": PALABRA})
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "err.host_poweroff_disabled"
    assert envios == []
    assert _auditoria(data_dir)[0]["detail"] == {"result": "disabled"}


def test_una_sola_variable_no_basta(client_auth, monkeypatch, envios):
    monkeypatch.setattr(config, "HOST_POWEROFF_URL", "http://agente.invalid/poweroff")
    assert client_auth.get("/api/capabilities").json()["host_poweroff"] is False


def test_capacidad_presente_anuncia_la_palabra(client_auth, habilitado):
    assert client_auth.get("/api/capabilities").json() == {
        "host_poweroff": True,
        "host_poweroff_word": PALABRA,
    }


@pytest.mark.parametrize("cuerpo", [{}, {"confirmation": ""}, {"confirmation": "si"}])
def test_con_cookie_pero_sin_confirmacion_no_se_envia(
    client_auth, habilitado, envios, data_dir, cuerpo
):
    r = client_auth.post(URL, json=cuerpo)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "err.host_poweroff_confirmation"
    assert envios == []
    assert _auditoria(data_dir)[-1]["detail"] == {"result": "bad-confirmation"}


def test_confirmado_envia_una_vez_y_audita(client_auth, habilitado, envios, data_dir):
    r = client_auth.post(URL, json={"confirmation": f"  {PALABRA.lower()} "})
    assert r.status_code == 200
    assert envios == ["poweroff"]
    (entrada,) = _auditoria(data_dir)
    assert entrada["user"] == "usuario-de-prueba"
    assert entrada["ip"] and entrada["ts"]
    assert entrada["detail"] == {"result": "accepted"}
    assert "t" * 40 not in json.dumps(entrada)


@pytest.mark.parametrize(
    ("fallo", "estado", "codigo", "resultado"),
    [
        (AppError("err.host_poweroff_unreachable"), 502,
         "err.host_poweroff_unreachable", "unreachable"),
        (AppError("err.host_poweroff_rejected", {"status": 401}), 502,
         "err.host_poweroff_rejected", "rejected"),
    ],
)
def test_si_el_host_falla_el_error_es_claro_y_queda_auditado(
    client_auth, habilitado, monkeypatch, data_dir, fallo, estado, codigo, resultado
):
    def falla():
        raise fallo

    monkeypatch.setattr(host_poweroff, "send", falla)
    r = client_auth.post(URL, json={"confirmation": PALABRA})
    assert r.status_code == estado
    assert r.json()["detail"]["code"] == codigo
    assert _auditoria(data_dir)[-1]["detail"] == {"result": resultado}


def test_el_token_de_scripts_no_abre_esta_ruta(
    client_local, habilitado, envios, cabecera
):
    """Solo sesión de persona: ni siquiera con un token de scripts válido."""
    r = client_local.post(URL, headers=cabecera, json={"confirmation": PALABRA})
    assert r.status_code == 401
    assert envios == []


# ----------------------------------------------------------------------
# El cliente real, contra un agente local con el apagado sustituido
# ----------------------------------------------------------------------
@pytest.fixture
def agente(tmp_path, monkeypatch):
    import threading

    from test_host_agent import cargar_agente

    token = tmp_path / "token"
    token.write_text("s" * 40 + "\n")
    token.chmod(0o600)
    apagados: list[int] = []
    servidor = cargar_agente().make_server(
        "127.0.0.1", 0, str(token), poweroff=lambda: apagados.append(1), delay=0
    )
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    monkeypatch.setattr(
        config, "HOST_POWEROFF_URL",
        f"http://127.0.0.1:{servidor.server_address[1]}/poweroff",
    )
    yield apagados
    servidor.shutdown()
    servidor.server_close()


def test_send_con_el_token_bueno_llega_al_agente(agente, monkeypatch):
    import time

    monkeypatch.setattr(config, "HOST_POWEROFF_TOKEN", "s" * 40)
    host_poweroff.send()
    time.sleep(0.3)
    assert agente == [1]


def test_send_con_token_malo_es_rechazado(agente, monkeypatch):
    monkeypatch.setattr(config, "HOST_POWEROFF_TOKEN", "x" * 40)
    with pytest.raises(AppError) as exc:
        host_poweroff.send()
    assert exc.value.code == "err.host_poweroff_rejected"
    assert agente == []


def test_send_sin_agente_escuchando_es_inalcanzable(monkeypatch):
    monkeypatch.setattr(config, "HOST_POWEROFF_URL", "http://127.0.0.1:9/poweroff")
    monkeypatch.setattr(config, "HOST_POWEROFF_TOKEN", "s" * 40)
    with pytest.raises(AppError) as exc:
        host_poweroff.send()
    assert exc.value.code == "err.host_poweroff_unreachable"


def test_send_rechaza_una_url_que_no_es_http(monkeypatch):
    monkeypatch.setattr(config, "HOST_POWEROFF_URL", "file:///etc/passwd")
    monkeypatch.setattr(config, "HOST_POWEROFF_TOKEN", "s" * 40)
    with pytest.raises(AppError) as exc:
        host_poweroff.send()
    assert exc.value.code == "err.host_poweroff_unreachable"
