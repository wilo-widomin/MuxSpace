"""El agente del host (`host-agent/host_agent.py`) contra un servidor local.

La orden de apagado se inyecta como un registro: nada se apaga nunca.
"""
from __future__ import annotations

import http.client
import importlib.util
import threading
import time
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parents[2] / "host-agent" / "host_agent.py"
TOKEN = "k" * 40


def cargar_agente():
    spec = importlib.util.spec_from_file_location("host_agent", RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def montar(tmp_path):
    agente = cargar_agente()
    servidores = []

    def _montar(allowed=None, modo=0o600):
        token = tmp_path / f"token{len(servidores)}"
        token.write_text(TOKEN + "\n")
        token.chmod(modo)
        apagados: list[int] = []
        servidor = agente.make_server(
            "127.0.0.1", 0, str(token),
            allowed=agente.parse_allowed(allowed or ""),
            poweroff=lambda: apagados.append(1), delay=0,
        )
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        servidores.append(servidor)
        return servidor.server_address[1], apagados

    yield _montar
    for s in servidores:
        s.shutdown()
        s.server_close()


def pedir(puerto, metodo="POST", ruta="/poweroff", token=TOKEN, cabecera=None):
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=3)
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    if cabecera is not None:
        headers = {"Authorization": cabecera}
    c.request(metodo, ruta, headers=headers)
    r = c.getresponse()
    cuerpo = r.read()
    c.close()
    return r.status, cuerpo


def test_token_bueno_responde_202_y_apaga_una_vez(montar):
    puerto, apagados = montar()
    assert pedir(puerto)[0] == 202
    assert pedir(puerto)[0] == 202  # el segundo no programa otro apagado
    time.sleep(0.3)
    assert apagados == [1]


def test_sin_token_es_401_sin_cuerpo_y_no_apaga(montar):
    puerto, apagados = montar()
    assert pedir(puerto, token=None) == (401, b"")
    time.sleep(0.2)
    assert apagados == []


@pytest.mark.parametrize("malo", ["x" * 40, TOKEN[:-1], TOKEN + "x", "", "k"])
def test_token_malo_es_401_y_no_apaga(montar, malo):
    puerto, apagados = montar()
    assert pedir(puerto, token=malo) == (401, b"")
    time.sleep(0.2)
    assert apagados == []


def test_otro_esquema_de_autorizacion_es_401(montar):
    puerto, apagados = montar()
    assert pedir(puerto, cabecera=f"Basic {TOKEN}")[0] == 401
    assert apagados == []


@pytest.mark.parametrize("ruta", ["/", "/poweroff/", "/reboot", "/poweroff?x=1"])
def test_otra_ruta_es_404(montar, ruta):
    puerto, apagados = montar()
    assert pedir(puerto, ruta=ruta)[0] == 404
    assert apagados == []


@pytest.mark.parametrize("metodo", ["GET", "PUT", "DELETE", "PATCH", "HEAD"])
def test_otro_metodo_es_405(montar, metodo):
    puerto, apagados = montar()
    assert pedir(puerto, metodo=metodo)[0] == 405
    time.sleep(0.2)
    assert apagados == []


def test_ip_no_permitida_es_403_aunque_el_token_sea_bueno(montar):
    puerto, apagados = montar(allowed="192.0.2.1")
    assert pedir(puerto)[0] == 403
    time.sleep(0.2)
    assert apagados == []


def test_ip_permitida_por_red_pasa(montar):
    puerto, _ = montar(allowed="198.51.100.7, 127.0.0.0/8")
    assert pedir(puerto)[0] == 202


def test_un_token_con_permisos_laxos_impide_arrancar(montar):
    with pytest.raises(PermissionError):
        montar(modo=0o644)


def test_un_token_corto_impide_arrancar(tmp_path):
    token = tmp_path / "t"
    token.write_text("corto\n")
    token.chmod(0o600)
    with pytest.raises(ValueError):
        cargar_agente().make_server("127.0.0.1", 0, str(token))


def test_no_acepta_parametros_ni_cuerpo(montar):
    """Un cuerpo cualquiera se ignora: la orden es fija."""
    puerto, apagados = montar()
    c = http.client.HTTPConnection("127.0.0.1", puerto, timeout=3)
    c.request(
        "POST", "/poweroff", body='{"cmd":"rm -rf /"}',
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    assert c.getresponse().status == 202
    time.sleep(0.3)
    assert apagados == [1]
