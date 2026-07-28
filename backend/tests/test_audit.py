"""El registro de auditoría (US-018, hallazgo S8).

Este panel ejecuta comandos como el usuario que lo arranca, y hasta ahora no
quedaba traza de cuál. Lo que se prueba aquí no es que el módulo escriba: es
que **cada acción con efecto deja exactamente una línea**, que la línea lleva
lo necesario para reconstruir qué pasó, y —lo más importante— que el log
**nunca** tumba la acción que está auditando.

Los tests van por los endpoints HTTP y no llamando a `audit.record` a mano:
un `record` perfecto al que nadie llama no audita nada, y ese es justo el modo
de fallo que hay que cazar.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from conftest import PASSWORD, USERNAME

import audit
import main
from auth import SESSION_COOKIE


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dobla las funciones de tmux que usan los endpoints.

    NO es opcional ni una comodidad: sin esto, `create_session` hablaría con
    el servidor de tmux REAL del usuario, donde tiene su trabajo abierto. Se
    parchean los nombres tal y como los importó `main` (`from tmux_service
    import create_session`), que es lo que ese módulo ejecuta de verdad —
    parchear `tmux_service` no cambiaría nada, la misma trampa que documenta
    el conftest para `AUTH_ENABLED`.
    """
    vivas: set[str] = set()

    def crear(name, command=None, cwd=None):
        if name in vivas:
            return False
        vivas.add(name)
        return True

    def existe(name):
        return name in vivas

    def renombrar(name, new_name):
        if name not in vivas:
            return False
        vivas.discard(name)
        vivas.add(new_name)
        return True

    def matar(name):
        habia = name in vivas
        vivas.discard(name)
        return habia

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "session_exists", existe)
    monkeypatch.setattr(main, "rename_session", renombrar)
    monkeypatch.setattr(main, "kill_session", matar)
    monkeypatch.setattr(main, "send_command", lambda name, cmd: None)
    monkeypatch.setattr(main, "list_sessions", lambda: [])


@pytest.fixture
def biblioteca(client_no_auth) -> dict[str, str]:
    """Un comando y un proyecto en la biblioteca, con sus identificadores.

    `launch` y `run-project` necesitan algo que lanzar. Se crean por la API
    y no escribiendo el JSON a mano para que los ids sean los que genera el
    store de verdad.
    """
    cmd = client_no_auth.post(
        "/api/commands", json={"label": "eco", "command": "echo hola"}
    )
    assert cmd.status_code == 201, cmd.text
    proy = client_no_auth.post(
        "/api/projects",
        json={"title": "proyecto", "cwd": None, "commands": ["echo uno"]},
    )
    assert proy.status_code == 201, proy.text
    return {"comando": cmd.json()["id"], "proyecto": proy.json()["id"]}


def lineas(data_dir: Path) -> list[dict]:
    """El log completo, ya parseado. Lista vacía si aún no existe."""
    ruta = audit._LOG_PATH
    if not ruta.is_file():
        return []
    return [
        json.loads(linea)
        for linea in ruta.read_text(encoding="utf-8").splitlines()
        if linea.strip()
    ]


# ----------------------------------------------------------------------
# El formato
# ----------------------------------------------------------------------


def test_una_anotacion_es_una_linea_de_json_con_los_campos_del_contrato(
    data_dir: Path,
) -> None:
    audit.record("prueba", user="willy", target="sesion-1", detail={"x": 1})

    (entrada,) = lineas(data_dir)
    assert set(entrada) == {"ts", "ip", "user", "action", "target", "detail"}
    assert entrada["action"] == "prueba"
    assert entrada["user"] == "willy"
    assert entrada["target"] == "sesion-1"
    assert entrada["detail"] == {"x": 1}


def test_la_marca_de_tiempo_es_iso_8601_con_zona(data_dir: Path) -> None:
    """Nada de epoch pelado: el log se lee a ojo cuando algo ha pasado."""
    from datetime import datetime

    audit.record("prueba")

    ts = lineas(data_dir)[0]["ts"]
    momento = datetime.fromisoformat(ts)  # lanza si no es ISO 8601
    assert momento.tzinfo is not None, f"{ts} no lleva zona horaria"


def test_cada_anotacion_va_en_su_linea(data_dir: Path) -> None:
    """JSONL de verdad: una línea corrupta no puede arrastrar a las demás."""
    for i in range(5):
        audit.record("prueba", target=f"s{i}")

    crudo = audit._LOG_PATH.read_text(encoding="utf-8")
    assert crudo.count("\n") == 5
    assert [e["target"] for e in lineas(data_dir)] == ["s0", "s1", "s2", "s3", "s4"]


def test_el_log_se_crea_a_0600(data_dir: Path) -> None:
    """Registra qué comandos ejecuta el usuario: no puede quedar legible."""
    audit.record("prueba")

    modo = stat.S_IMODE(audit._LOG_PATH.stat().st_mode)
    assert modo == 0o600, f"el log salió a {oct(modo)}"


def test_los_acentos_no_se_escapan(data_dir: Path) -> None:
    """`ensure_ascii=False`: un log que hay que leer a ojo se lee a ojo."""
    audit.record("prueba", target="sesión-ñ", detail={"cmd": "echo café"})

    crudo = audit._LOG_PATH.read_text(encoding="utf-8")
    assert "sesión-ñ" in crudo
    assert "\\u" not in crudo


# ----------------------------------------------------------------------
# La regla que no se negocia: escribir el log NUNCA tumba la petición
# ----------------------------------------------------------------------


def test_un_fallo_de_escritura_no_propaga(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un panel que deja de funcionar por no poder escribir su log es peor.

    Se rompe `os.open` a bajo nivel y no `record` entero: así se prueba el
    `except` de verdad del módulo, no un mock de sí mismo.
    """
    def revienta(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit.os, "open", revienta)

    audit.record("prueba")  # no debe lanzar

    assert lineas(data_dir) == []


def test_un_detail_no_serializable_no_propaga(data_dir: Path) -> None:
    """Quien llama puede meter cualquier cosa en `detail` sin saberlo."""
    audit.record("prueba", detail={"objeto": object()})  # no debe lanzar

    assert lineas(data_dir) == []


def test_una_peticion_sobrevive_a_un_log_roto(
    client_no_auth, data_dir: Path, tmux_falso, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La prueba de la regla desde fuera: el endpoint responde igual.

    Es la que de verdad importa. Las de arriba comprueban que `record` se
    traga el error; esta comprueba que la acción del usuario llega a hacerse.
    """
    def revienta(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(audit.os, "open", revienta)

    r = client_no_auth.post("/api/create-session/sesion-con-log-roto")

    assert r.status_code == 200
    assert r.json()["created"] is True


# ----------------------------------------------------------------------
# La rotación
# ----------------------------------------------------------------------


def test_al_superar_el_tope_el_log_rota_y_se_sigue_escribiendo(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "_MAX_BYTES", 500)

    for i in range(60):
        audit.record("prueba", target=f"relleno-{i}")

    rotado = audit._LOG_PATH.with_name(audit._LOG_PATH.name + ".1")
    assert rotado.is_file(), "no se creó audit.log.1"
    assert audit._LOG_PATH.is_file(), "no se abrió un log nuevo tras rotar"
    # Y lo último escrito está en el fichero vivo, no en el rotado.
    assert lineas(data_dir)[-1]["target"] == "relleno-59"


def test_solo_se_conserva_una_rotacion(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decisión consciente: el histórico completo se lo lleva quien lo quiera.

    Sin esto el log crece sin techo en el mismo disco que guarda las sesiones
    del usuario.
    """
    monkeypatch.setattr(audit, "_MAX_BYTES", 300)

    for i in range(200):
        audit.record("prueba", target=f"relleno-{i}")

    sueltos = sorted(p.name for p in data_dir.glob("audit.log*"))
    assert sueltos == ["audit.log", "audit.log.1"], sueltos


# ----------------------------------------------------------------------
# Que los endpoints realmente auditen
# ----------------------------------------------------------------------


def _acciones(data_dir: Path) -> list[str]:
    return [e["action"] for e in lineas(data_dir)]


@pytest.mark.parametrize(
    "accion, hacer",
    [
        (
            "create-session",
            lambda c, ids: c.post("/api/create-session/otra-sesion"),
        ),
        (
            "send-command",
            lambda c, ids: c.post(
                "/api/send-command/sesion-nueva", json={"command": "ls -la"}
            ),
        ),
        (
            "rename-session",
            lambda c, ids: c.post(
                "/api/rename-session/sesion-nueva", json={"new_name": "otra"}
            ),
        ),
        ("kill-session", lambda c, ids: c.post("/api/kill-session/sesion-nueva")),
        ("launch", lambda c, ids: c.post(f"/api/commands/{ids['comando']}/launch")),
        ("run-project", lambda c, ids: c.post(f"/api/projects/{ids['proyecto']}/run")),
    ],
)
def test_cada_accion_deja_exactamente_una_linea(
    client_no_auth,
    data_dir: Path,
    tmux_falso,
    biblioteca: dict[str, str],
    accion: str,
    hacer,
) -> None:
    """Una línea por acción: ni cero (no audita) ni dos (audita de más).

    Están las siete acciones que exige el criterio de aceptación, ni una
    menos: la lista del contrato es la lista del `parametrize`.

    Cada caso arranca con `sesion-nueva` ya creada porque `send-command` y
    `rename-session` devuelven 404 si la sesión no existe: sin ese paso
    previo el test pasaría a verde el día que dejaran de auditar, que es
    justo lo contrario de lo que tiene que hacer. Por eso también se cuenta
    contra `previas` y se comprueba el 200: el montaje no puede colarse en
    la cuenta ni la acción quedar sin hacerse.
    """
    client_no_auth.post("/api/create-session/sesion-nueva")
    previas = _acciones(data_dir).count(accion)

    r = hacer(client_no_auth, biblioteca)
    assert r.status_code == 200, r.text

    assert _acciones(data_dir).count(accion) - previas == 1


def test_el_comando_enviado_queda_registrado(
    client_no_auth, data_dir: Path, tmux_falso
) -> None:
    """`detail` tiene que permitir reconstruir QUÉ se ejecutó.

    Es el punto entero de S8: en un panel que da shell, saber que hubo un
    "send-command" y no cuál sirve de poco.
    """
    client_no_auth.post("/api/create-session/sesion-x")
    client_no_auth.post(
        "/api/send-command/sesion-x", json={"command": "rm -rf /tmp/x"}
    )

    envios = [e for e in lineas(data_dir) if e["action"] == "send-command"]
    assert len(envios) == 1
    assert envios[0]["detail"]["command"] == "rm -rf /tmp/x"
    assert envios[0]["target"] == "sesion-x"


def test_la_subida_registra_la_ruta(
    client_no_auth, data_dir: Path, allowed_root: Path
) -> None:
    r = client_no_auth.post(
        f"/api/upload?dir={allowed_root}&name=notas.txt", content=b"hola"
    )
    assert r.status_code == 200

    subidas = [e for e in lineas(data_dir) if e["action"] == "upload"]
    assert len(subidas) == 1
    assert subidas[0]["target"].endswith("notas.txt")
    assert subidas[0]["detail"]["bytes"] == 4


def test_el_login_se_audita_pero_sin_la_contrasena(
    client, data_dir: Path
) -> None:
    """La otra regla que no se negocia.

    El fixture es `client` (autenticación ACTIVADA) y no `client_no_auth`
    como en los tests de arriba: aquí lo que se ejercita ES el login, y con
    la autenticación apagada `/api/login` devuelve "anonymous" sin mirar las
    credenciales, así que el test no probaría nada.

    Se hacen los dos caminos —uno correcto y uno fallido— y se comprueba que
    ambos dejan traza y que la contraseña no aparece por ningún lado del log.
    Sin auditar el login, este test pasaría con el fichero vacío: por eso
    afirma primero que las dos líneas están.
    """
    secreto = "contrasena-secretisima-1234"

    ok = client.post(
        "/api/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert ok.status_code == 200
    fallo = client.post(
        "/api/login", json={"username": USERNAME, "password": secreto}
    )
    assert fallo.status_code == 401

    assert _acciones(data_dir).count("login") == 1
    assert _acciones(data_dir).count("login-failed") == 1

    crudo = audit._LOG_PATH.read_text(encoding="utf-8")
    assert secreto not in crudo
    assert PASSWORD not in crudo
    assert "password" not in crudo
    # Ni la cookie de sesión que acaba de emitirse: un log de auditoría que
    # lleve el token es una llave, no una traza.
    token = ok.cookies.get(SESSION_COOKIE) or client.cookies.get(SESSION_COOKIE)
    assert token, "el login correcto no dejó cookie de sesión"
    assert token not in crudo
