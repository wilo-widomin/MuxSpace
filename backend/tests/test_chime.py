"""Campanilla configurable: qué se puede guardar, qué se rechaza y por qué.

Lo que se protege aquí es que el ajuste sea DURADERO (sobrevive al reinicio,
a diferencia del aviso, que es un hecho del momento), que sea COMPARTIDO
—vive en el servidor, así que se elige una vez y no tres— y que un fichero
editado a mano o una petición torcida no puedan dejar el panel sin aviso
audible ni reventarle los oídos a nadie.
"""
from __future__ import annotations

import json

import pytest

import chime_store


def _preset(**cambios) -> dict:
    base = {
        "mode": "preset",
        "preset": "bell",
        "volume": 0.3,
        "muted": False,
        "notes": [],
        "timbre": "bell",
        "file": None,
    }
    base.update(cambios)
    return base


def _nota(freq=880.0, delay=0.0, duration=0.4) -> dict:
    return {"freq": freq, "delay": delay, "duration": duration}


# ----------------------------------------------------------------------
# Lo que el usuario nota
# ----------------------------------------------------------------------
def test_de_fabrica_suena_el_preset_por_defecto(client_auth):
    """Sin haber elegido nada, hay campanilla: el panel no nace mudo."""
    cfg = client_auth.get("/api/chime").json()
    assert cfg["mode"] == "preset"
    assert cfg["preset"] == chime_store.DEFAULT_PRESET
    assert cfg["muted"] is False


def test_el_ajuste_sobrevive_al_reinicio(client_auth, data_dir):
    """Es una preferencia, no un estado del momento: va a disco.

    Un ajuste que se borra al reiniciar el backend no es un ajuste; esta es
    justo la diferencia con los avisos, que sí viven solo en memoria.
    """
    client_auth.put("/api/chime", json=_preset(preset="marimba", volume=0.8))
    # Se lee el disco directamente: si esto solo estuviera en memoria, el
    # fichero no existiría y el siguiente arranque empezaría de cero.
    guardado = json.loads((data_dir / "chime.json").read_text(encoding="utf-8"))
    assert guardado["preset"] == "marimba"
    assert guardado["volume"] == 0.8


def test_lo_que_se_guarda_es_lo_que_se_lee(client_auth):
    client_auth.put("/api/chime", json=_preset(mode="custom", notes=[_nota(freq=440.0)]))
    cfg = client_auth.get("/api/chime").json()
    assert cfg["mode"] == "custom"
    assert cfg["notes"] == [{"freq": 440.0, "delay": 0.0, "duration": 0.4}]


def test_silenciar_es_un_ajuste_aparte_del_sonido(client_auth):
    """Silenciar no borra lo elegido: al volver a activarlo suena lo de antes."""
    client_auth.put("/api/chime", json=_preset(preset="marimba", muted=True))
    cfg = client_auth.get("/api/chime").json()
    assert cfg["muted"] is True
    assert cfg["preset"] == "marimba"


# ----------------------------------------------------------------------
# Validación
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "cambio",
    [
        {"volume": 40},  # reventaría los oídos
        {"volume": -1},
        {"mode": "telepatia"},
        {"timbre": "gaita"},
        {"preset": "../../etc/passwd"},
        {"mode": "custom", "notes": []},  # un aviso mudo parece uno roto
        {"mode": "custom", "notes": [_nota(freq=99999)]},
        {"mode": "custom", "notes": [_nota(duration=0)]},
        {"mode": "custom", "notes": [_nota(delay=60)]},
    ],
)
def test_un_ajuste_imposible_se_rechaza(client_auth, cambio):
    resp = client_auth.put("/api/chime", json=_preset(**cambio))
    assert resp.status_code in (400, 422), resp.text


def test_demasiadas_notas_ya_no_son_un_aviso(client_auth):
    notas = [_nota(delay=i * 0.1) for i in range(chime_store.MAX_NOTES + 1)]
    resp = client_auth.put("/api/chime", json=_preset(mode="custom", notes=notas))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "err.chime_too_many_notes"


def test_un_fichero_editado_a_mano_no_deja_el_panel_sin_sonido(client_auth, data_dir):
    """Leer nunca lanza: un JSON corrupto cae al ajuste de fábrica.

    El fichero se puede editar a mano, y un `volume: 40` escrito ahí no puede
    llegar al navegador ni tumbar el arranque.
    """
    (data_dir / "chime.json").write_text('{"volume": 40, "mode": "brujeria"}')
    cfg = client_auth.get("/api/chime").json()
    assert cfg["volume"] == 0.3
    assert cfg["mode"] == "preset"


def test_un_json_ilegible_tambien_cae_al_de_fabrica(client_auth, data_dir):
    (data_dir / "chime.json").write_text("{no es json")
    assert client_auth.get("/api/chime").json()["preset"] == chime_store.DEFAULT_PRESET


# ----------------------------------------------------------------------
# Campanilla propia (audio subido)
# ----------------------------------------------------------------------
def test_subir_un_audio_lo_deja_sonando_sin_un_paso_mas(client_auth):
    """Subir y que no suene sería una trampa: el modo cambia en el mismo gesto."""
    resp = client_auth.post(
        "/api/chime/audio",
        content=b"ID3 bytes de prueba",
        headers={"Content-Type": "audio/mpeg"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mode"] == "file"
    assert resp.json()["file"] == "custom.mp3"
    assert client_auth.get("/api/chime/audio").content == b"ID3 bytes de prueba"


def test_subir_otro_audio_sustituye_al_anterior(client_auth, data_dir):
    """Solo hay UNA campanilla propia: nadie colecciona campanillas."""
    client_auth.post(
        "/api/chime/audio", content=b"primero", headers={"Content-Type": "audio/mpeg"}
    )
    client_auth.post(
        "/api/chime/audio", content=b"segundo", headers={"Content-Type": "audio/wav"}
    )
    assert sorted(p.name for p in (data_dir / "chime").iterdir()) == ["custom.wav"]
    assert client_auth.get("/api/chime/audio").content == b"segundo"


def test_un_formato_que_no_es_audio_se_rechaza(client_auth):
    resp = client_auth.post(
        "/api/chime/audio",
        content=b"<html>",
        headers={"Content-Type": "text/html"},
    )
    assert resp.status_code == 415
    assert resp.json()["detail"]["code"] == "err.chime_audio_format"


def test_un_audio_enorme_se_corta_antes_de_leerlo_entero(client_auth):
    grande = b"x" * (chime_store.AUDIO_MAX_BYTES + 1)
    resp = client_auth.post(
        "/api/chime/audio", content=grande, headers={"Content-Type": "audio/mpeg"}
    )
    assert resp.status_code == 413


def test_elegir_un_audio_que_no_existe_se_rechaza(client_auth):
    """El ajuste no puede apuntar a un fichero que no está."""
    resp = client_auth.put("/api/chime", json=_preset(mode="file"))
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "err.chime_no_audio"


def test_borrar_el_audio_devuelve_el_sonido_del_panel(client_auth):
    """Quitar la campanilla propia no puede dejar el aviso sin sonido."""
    client_auth.post(
        "/api/chime/audio", content=b"bytes", headers={"Content-Type": "audio/mpeg"}
    )
    cfg = client_auth.delete("/api/chime/audio").json()
    assert cfg["mode"] == "preset"
    assert cfg["file"] is None
    assert client_auth.get("/api/chime/audio").status_code == 404


def test_el_nombre_del_audio_lo_decide_el_servidor(client_auth):
    """Da igual lo que mande el cliente en `file`: se mira qué hay en disco."""
    cfg = client_auth.put("/api/chime", json=_preset(file="../../etc/passwd")).json()
    assert cfg["file"] is None


# ----------------------------------------------------------------------
# Acceso
# ----------------------------------------------------------------------
def test_el_secreto_del_hook_no_sirve_para_cambiar_la_campanilla(client):
    """Quien puede avisar no tiene por qué poder subir ficheros ni cambiar ajustes."""
    import attention_store
    import main

    cabecera = {main._HOOK_TOKEN_HEADER: attention_store.hook_token()}
    assert client.get("/api/chime", headers=cabecera).status_code == 401
    assert client.put("/api/chime", json=_preset(), headers=cabecera).status_code == 401
    assert (
        client.post(
            "/api/chime/audio",
            content=b"x",
            headers={**cabecera, "Content-Type": "audio/mpeg"},
        ).status_code
        == 401
    )
