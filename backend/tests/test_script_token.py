"""El token de scripts: qué abre, qué puede lanzar y qué deja registrado.

El contrato de sus rutas está en `test_auth_contract.py`. Aquí se prueba el
resto: que en disco solo hay huellas, que un comando fuera de las reglas no
llega a guardarse ni a ejecutarse, que solo toca lo suyo y que solo vale desde
la propia máquina.

Nada habla con tmux: `tmux_falso` lo sustituye por un mapa de sesiones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import PASSWORD, USERNAME
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import auth
import config
import main
import script_policy
import script_token
import space_store

PREFIJO = "CLAUDIFY_PROJECT=mvp-lab-skills claude"
# El comando que usará el receptor de entrevistas, literal.
COMANDO_REAL = (
    f'{PREFIJO} --permission-mode auto -n "entrevista 1f1d6a7d" '
    '"arranca un proyecto nuevo con esta entrevista"'
)
CABECERA = main._SCRIPT_TOKEN_HEADER
# Con `chr` para que el propio archivo no lleve caracteres invisibles.
ESPACIO_DE_ANCHO_CERO = chr(0x200B)
ESPACIO_DURO = chr(0xA0)


@pytest.fixture
def tmux_falso(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict]:
    """Sustituye el tmux real por un mapa `sesión -> cómo se creó`."""
    vivas: dict[str, dict] = {}

    def crear(name, command=None, cwd=None):
        vivas[name] = {"command": command, "cwd": cwd}
        return True

    def matar(name):
        return vivas.pop(name, None) is not None

    monkeypatch.setattr(main, "create_session", crear)
    monkeypatch.setattr(main, "kill_session", matar)
    monkeypatch.setattr(main, "list_sessions", list)
    return vivas


@pytest.fixture
def raiz(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Prefijo y raíz configurados, y la raíz ya creada."""
    carpeta = tmp_path / "proyectos-del-receptor"
    (carpeta / "entrevista").mkdir(parents=True)
    monkeypatch.setattr(config, "SCRIPT_COMMAND_PREFIX", PREFIJO)
    monkeypatch.setattr(config, "SCRIPT_CWD_ROOT", str(carpeta))
    return carpeta


@pytest.fixture
def cabecera() -> dict[str, str]:
    return {CABECERA: script_token.generate()[0]}


def _alta(client, cabecera, raiz, **campos):
    cuerpo = {
        "title": "MVPL-0411-1f1d6a7d",
        "cwd": str(raiz / "entrevista"),
        "commands": [COMANDO_REAL],
        **campos,
    }
    return client.post("/api/projects", headers=cabecera, json=cuerpo)


def _proyecto_del_panel(client_auth) -> dict:
    return client_auth.post(
        "/api/projects",
        json={"title": "Del panel", "cwd": "/srv", "commands": ["ls"]},
    ).json()


def _auditoria(data_dir: Path, accion: str = "script-token") -> list[dict]:
    ruta = data_dir / "audit.log"
    if not ruta.exists():
        return []
    entradas = [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]
    return [e for e in entradas if e["action"] == accion]


# ----------------------------------------------------------------------
# El token: huellas, rotación y comandos
# ----------------------------------------------------------------------
def test_en_disco_solo_queda_la_huella_a_0600(data_dir: Path) -> None:
    token, _ = script_token.generate()

    ruta = data_dir / "script_token_hashes.json"
    assert token not in ruta.read_text(encoding="utf-8")
    assert oct(ruta.stat().st_mode)[-3:] == "600"
    assert script_token.match(token) is not None


def test_el_arranque_no_genera_nada_y_sin_token_no_se_abre(
    client_local, data_dir: Path
) -> None:
    resp = client_local.get("/api/projects", headers={CABECERA: "cualquiera"})

    assert resp.status_code == 401
    assert not (data_dir / "script_token_hashes.json").exists()


def test_rotar_conserva_el_anterior_y_retirarlo_lo_anula(client_local) -> None:
    """El panel lee los cambios sin reiniciarse: es el mismo proceso en marcha."""
    viejo, _ = script_token.generate()
    assert client_local.get(
        "/api/projects", headers={CABECERA: viejo}
    ).status_code == 200

    nuevo, descartado = script_token.generate()
    assert descartado is None
    for token in (viejo, nuevo):
        assert client_local.get(
            "/api/projects", headers={CABECERA: token}
        ).status_code == 200

    assert script_token.retire_previous() is True
    assert client_local.get(
        "/api/projects", headers={CABECERA: viejo}
    ).status_code == 401
    assert client_local.get(
        "/api/projects", headers={CABECERA: nuevo}
    ).status_code == 200
    assert script_token.retire_previous() is False


def test_un_tercero_expulsa_al_mas_antiguo() -> None:
    primero, _ = script_token.generate()
    segundo, _ = script_token.generate()
    tercero, descartado = script_token.generate()

    assert descartado is not None
    assert script_token.match(primero) is None
    assert script_token.match(segundo) != script_token.match(tercero)


def test_cada_token_tiene_su_identificador_y_no_es_el_token() -> None:
    uno, _ = script_token.generate()
    dos, _ = script_token.generate()

    id_uno, id_dos = script_token.match(uno), script_token.match(dos)
    assert id_uno != id_dos
    assert len(id_uno) == 8
    assert id_uno not in uno


@pytest.mark.parametrize("contenido", ["no es json", "[]", '{"current": "abc"}'])
def test_un_archivo_danado_no_abre_nada(data_dir: Path, contenido: str) -> None:
    token, _ = script_token.generate()
    (data_dir / "script_token_hashes.json").write_text(contenido, encoding="utf-8")

    assert script_token.match(token) is None


def test_borrar_el_archivo_lo_cierra_todo(data_dir: Path) -> None:
    token, _ = script_token.generate()
    (data_dir / "script_token_hashes.json").unlink()

    assert script_token.match(token) is None


def test_el_comando_imprime_el_token_una_vez_y_solo_por_la_salida_estandar(
    capsys: pytest.CaptureFixture,
) -> None:
    assert script_token.main(["generate"]) == 0
    salida = capsys.readouterr()
    token = salida.out.strip()

    assert script_token.match(token) is not None
    assert token not in salida.err

    assert script_token.main(["status"]) == 0
    estado = capsys.readouterr().out
    assert token not in estado
    assert f"current: {script_token.match(token)}" in estado
    assert "previous: -" in estado


def test_el_comando_retira_el_anterior(capsys: pytest.CaptureFixture) -> None:
    script_token.main(["generate"])
    viejo = capsys.readouterr().out.strip()
    script_token.main(["generate"])
    nuevo = capsys.readouterr().out.strip()

    script_token.main(["retire-previous"])
    assert "retirado" in capsys.readouterr().out
    assert script_token.match(viejo) is None
    assert script_token.match(nuevo) is not None

    script_token.main(["retire-previous"])
    assert "No había" in capsys.readouterr().out


def test_al_expulsar_uno_el_comando_lo_dice(capsys: pytest.CaptureFixture) -> None:
    for _ in range(3):
        script_token.main(["generate"])
    assert "ha dejado de valer" in capsys.readouterr().err


# ----------------------------------------------------------------------
# Solo desde la propia máquina
# ----------------------------------------------------------------------
def test_fuera_de_loopback_el_token_no_autentica(client, cabecera) -> None:
    """`client` entra con una IP que no es loopback."""
    assert client.get("/api/projects", headers=cabecera).status_code == 401


@pytest.mark.parametrize(
    "cabecera_de_proxy",
    [
        "X-Forwarded-For",
        "X-Forwarded-Host",
        "X-Forwarded-Proto",
        "X-Real-IP",
        "Forwarded",
    ],
)
def test_con_cabeceras_de_proxy_no_autentica(
    client_local, cabecera, cabecera_de_proxy: str
) -> None:
    """Un proxy local que no reescribe la IP sigue sin colar como la máquina."""
    resp = client_local.get(
        "/api/projects", headers={**cabecera, cabecera_de_proxy: "127.0.0.1"}
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ("ip", "esperado"),
    [
        ("127.0.0.1", 200),
        ("127.5.5.5", 200),
        ("::1", 200),
        ("::ffff:127.0.0.1", 200),
        ("192.168.1.13", 401),
        ("::ffff:192.168.1.13", 401),
        ("no-es-una-ip", 401),
    ],
)
def test_que_cuenta_como_la_propia_maquina(cabecera, ip: str, esperado: int) -> None:
    with TestClient(main.app, client=(ip, 50000)) as c:
        assert c.get("/api/projects", headers=cabecera).status_code == esperado


def test_por_el_proxy_de_confianza_llega_la_ip_real_y_no_autentica(
    cabecera, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el mismo procesado que `uvicorn --proxy-headers`.

    Se apaga la comprobación de cabeceras para probar la otra mitad por sí
    sola: uvicorn sustituye la IP del proxy por la real antes de llegar aquí.
    """
    monkeypatch.setattr(main, "_PROXY_HEADERS", ())
    app = ProxyHeadersMiddleware(main.app, trusted_hosts="127.0.0.1")

    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        directa = c.get("/api/projects", headers=cabecera)
        por_proxy = c.get(
            "/api/projects",
            headers={**cabecera, "X-Forwarded-For": "203.0.113.9"},
        )

    assert directa.status_code == 200
    assert por_proxy.status_code == 401


def test_si_el_proxy_afirma_ser_loopback_tampoco_autentica(cabecera) -> None:
    app = ProxyHeadersMiddleware(main.app, trusted_hosts="127.0.0.1")

    with TestClient(app, client=("127.0.0.1", 50000)) as c:
        resp = c.get(
            "/api/projects", headers={**cabecera, "X-Forwarded-For": "127.0.0.1"}
        )

    assert resp.status_code == 401


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------
def test_el_ciclo_completo_de_un_script(
    client_local, cabecera, raiz: Path, tmux_falso, data_dir: Path
) -> None:
    """Crea, lanza, mata y borra con el comando real del receptor."""
    proyecto = _alta(client_local, cabecera, raiz).json()
    assert proyecto["script_owned"] is True
    assert proyecto["cwd"] == str((raiz / "entrevista").resolve())

    sesion = client_local.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).json()["name"]

    assert sesion == "MVPL-0411-1f1d6a7d"
    assert tmux_falso[sesion]["command"] == COMANDO_REAL
    assert [p["id"] for p in client_local.get(
        "/api/projects", headers=cabecera
    ).json()] == [proyecto["id"]]

    assert client_local.post(
        f"/api/kill-session/{sesion}", headers=cabecera
    ).json()["killed"] is True
    assert client_local.delete(
        f"/api/projects/{proyecto['id']}", headers=cabecera
    ).status_code == 200

    assert tmux_falso == {}
    assert client_local.get("/api/projects", headers=cabecera).json() == []
    assert _auditoria(data_dir, "run-project")[0]["user"] == "script"


@pytest.mark.parametrize(
    "comando",
    [
        PREFIJO,
        f"{PREFIJO} --permission-mode auto",
        f'{PREFIJO} -n "uno dos"',
        f'{PREFIJO} "un mensaje"',
        f'{PREFIJO}  -n x   "con espacios de más"',
    ],
)
def test_lo_que_se_acepta(comando: str) -> None:
    script_policy.check_command(comando, PREFIJO)


@pytest.mark.parametrize(
    "comando",
    [
        # El prefijo tiene que ir seguido de espacio o de fin.
        f"{PREFIJO}-otro",
        "claude",
        f"CLAUDIFY_PROJECT=otro {PREFIJO}",
        f"true; {PREFIJO}",
        # Encadenar o incrustar, también entre comillas dobles.
        f"{PREFIJO}; rm -rf ~",
        f"{PREFIJO} && rm -rf ~",
        f"{PREFIJO} | sh",
        f"{PREFIJO} & sh",
        f'{PREFIJO} "$(rm -rf ~)"',
        f'{PREFIJO} "`rm -rf ~`"',
        f'{PREFIJO} "${{HOME}} x"',
        f'{PREFIJO} "a \\" ; rm -rf ~ ; \\" b"',
        f"{PREFIJO} > /tmp/x",
        f"{PREFIJO} < /etc/passwd",
        f'{PREFIJO} "linea uno\nrm -rf ~"',
        f'{PREFIJO} "tabulador\tpor medio"',
        f'{PREFIJO} "paréntesis (x) y"',
        # Lo que `shlex` ve como una palabra y el shell convierte en varias.
        f"{PREFIJO} {{--settings,x}}",
        f"{PREFIJO} *",
        f"{PREFIJO} ?",
        f"{PREFIJO} [a]",
        f"{PREFIJO} ~",
        # Historial del shell interactivo y comentarios.
        f'{PREFIJO} "!! dos"',
        f'{PREFIJO} "^a^b dos"',
        f"{PREFIJO} # comentario",
        # Comillas sin cerrar o que no están en la lista.
        f'{PREFIJO} "sin cerrar',
        f"{PREFIJO} 'comillas simples'",
        # Caracteres invisibles.
        f'{PREFIJO} "dos{ESPACIO_DE_ANCHO_CERO}palabras x"',
        f'{PREFIJO} "dos{ESPACIO_DURO}palabras x"',
        # Opciones fuera de la lista blanca.
        f"{PREFIJO} --dangerously-skip-permissions",
        f"{PREFIJO} --allow-dangerously-skip-permissions",
        f"{PREFIJO} --permission-mode bypassPermissions",
        f"{PREFIJO} --permission-mode=auto",
        f"{PREFIJO} --permission-mode",
        f"{PREFIJO} --settings /tmp/x",
        f"{PREFIJO} --mcp-config /tmp/x",
        f"{PREFIJO} --add-dir /",
        f"{PREFIJO} --name x",
        f"{PREFIJO} --print",
        f"{PREFIJO} -p",
        f"{PREFIJO} --",
        # Una opción disfrazada de valor o de mensaje entre comillas.
        f'{PREFIJO} "--dangerously-skip-permissions"',
        f'{PREFIJO} -n "--settings"',
        f"{PREFIJO} -n",
        # Repetidas, o más de un mensaje.
        f"{PREFIJO} -n x -n y",
        f"{PREFIJO} --permission-mode auto --permission-mode auto",
        f'{PREFIJO} "un mensaje" "otro mensaje"',
        f"{PREFIJO} dos palabras",
        # Una palabra suelta sería un subcomando de `claude`.
        f"{PREFIJO} update",
        f'{PREFIJO} "install"',
    ],
)
def test_lo_que_se_rechaza_da_403_y_no_se_guarda(
    client_local, cabecera, raiz: Path, comando: str
) -> None:
    resp = _alta(client_local, cabecera, raiz, commands=[comando])

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "err.script_command_rejected"
    assert client_local.get("/api/projects", headers=cabecera).json() == []


def test_sin_prefijo_configurado_no_se_crea_nada(
    client_local, cabecera, raiz: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "SCRIPT_COMMAND_PREFIX", "")

    assert _alta(client_local, cabecera, raiz).status_code == 403


@pytest.mark.parametrize(
    "comandos",
    [[], [COMANDO_REAL, COMANDO_REAL], [COMANDO_REAL, "ls"], ["", " "]],
)
def test_un_solo_comando_por_proyecto(
    client_local, cabecera, raiz: Path, comandos: list[str]
) -> None:
    assert _alta(client_local, cabecera, raiz, commands=comandos).status_code == 403


def test_los_vacios_y_espacios_no_cuentan_como_comando(
    client_local, cabecera, raiz: Path
) -> None:
    resp = _alta(client_local, cabecera, raiz, commands=["", f"  {COMANDO_REAL}  "])

    assert resp.status_code == 201
    assert resp.json()["commands"] == [COMANDO_REAL]


# ----------------------------------------------------------------------
# La carpeta
# ----------------------------------------------------------------------
def test_una_carpeta_fuera_de_la_raiz_da_403(
    client_local, cabecera, raiz: Path, tmp_path: Path
) -> None:
    fuera = tmp_path / "fuera"
    fuera.mkdir()

    for cwd in (str(fuera), f"{raiz}/entrevista/../../fuera", str(raiz), "", None, "x"):
        resp = _alta(client_local, cabecera, raiz, cwd=cwd)
        assert resp.status_code == 403, cwd
        assert resp.json()["detail"]["code"] == "err.script_cwd_rejected"


def test_un_enlace_simbolico_no_escapa_de_la_raiz(
    client_local, cabecera, raiz: Path, tmp_path: Path
) -> None:
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (raiz / "atajo").symlink_to(fuera)

    assert _alta(
        client_local, cabecera, raiz, cwd=str(raiz / "atajo")
    ).status_code == 403


def test_un_enlace_dentro_de_la_raiz_se_guarda_ya_resuelto(
    client_local, cabecera, raiz: Path
) -> None:
    (raiz / "atajo").symlink_to(raiz / "entrevista")

    resp = _alta(client_local, cabecera, raiz, cwd=str(raiz / "atajo"))

    assert resp.json()["cwd"] == str((raiz / "entrevista").resolve())


def test_una_carpeta_que_no_existe_dentro_de_la_raiz_da_400(
    client_local, cabecera, raiz: Path
) -> None:
    resp = _alta(client_local, cabecera, raiz, cwd=str(raiz / "falta"))

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "err.script_cwd_missing"


def test_un_archivo_no_vale_como_carpeta(
    client_local, cabecera, raiz: Path
) -> None:
    (raiz / "archivo").write_text("x", encoding="utf-8")

    assert _alta(
        client_local, cabecera, raiz, cwd=str(raiz / "archivo")
    ).status_code == 400


@pytest.mark.parametrize("cwd", ["~usuario-que-no-existe-jamas/x", "/a\x00b"])
def test_una_ruta_que_ni_se_puede_resolver_da_403(cwd: str, tmp_path: Path) -> None:
    with pytest.raises(script_policy.ScriptPolicyError) as exc:
        script_policy.resolve_cwd(cwd, str(tmp_path))
    assert exc.value.status == 403


def test_la_raiz_admite_la_tilde_del_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "raiz" / "uno").mkdir(parents=True)

    assert script_policy.resolve_cwd("~/raiz/uno", "~/raiz") == str(
        (tmp_path / "raiz" / "uno").resolve()
    )


# ----------------------------------------------------------------------
# Lo que el servidor decide por el script
# ----------------------------------------------------------------------
def test_enlaces_y_espacio_del_cuerpo_se_ignoran(
    client_local, cabecera, raiz: Path, client_auth
) -> None:
    otro = client_auth.post("/api/spaces", json={"title": "Otro"}).json()

    proyecto = _alta(
        client_local, cabecera, raiz,
        links=[{"url": "https://malo.example"}],
        space=otro["id"],
    ).json()

    assert proyecto["links"] == []
    assert proyecto["space"] != otro["id"]


def test_todos_van_a_un_mismo_espacio_entrevistas(
    client_local, cabecera, raiz: Path
) -> None:
    uno = _alta(client_local, cabecera, raiz).json()
    dos = _alta(client_local, cabecera, raiz, title="Otro").json()

    assert uno["space"] == dos["space"]
    assert [s.title for s in space_store.list_spaces()] == ["Entrevistas"]


def test_aprovecha_el_espacio_que_ya_exista_por_titulo(
    client_local, cabecera, raiz: Path
) -> None:
    existente = space_store.create_space("ENTREVISTAS")

    assert _alta(client_local, cabecera, raiz).json()["space"] == existente.id


def test_si_borran_el_espacio_al_lanzar_se_vuelve_a_crear(
    client_local, cabecera, raiz: Path, tmux_falso, client_auth
) -> None:
    proyecto = _alta(client_local, cabecera, raiz).json()
    client_auth.delete(f"/api/spaces/{proyecto['space']}")

    sesion = client_local.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).json()["name"]

    nuevo = space_store.list_spaces()[0]
    assert nuevo.title == "Entrevistas"
    assert space_store.assignments() == {sesion: nuevo.id}


def test_el_titulo_se_reduce_a_lo_que_admite_una_sesion(
    client_local, cabecera, raiz: Path
) -> None:
    proyecto = _alta(client_local, cabecera, raiz, title="a b/c " + "x" * 80).json()

    assert proyecto["title"] == "a-b-c-" + "x" * 58


def test_un_titulo_que_se_queda_en_nada_da_400(
    client_local, cabecera, raiz: Path
) -> None:
    assert _alta(client_local, cabecera, raiz, title=" () ").status_code == 400


# ----------------------------------------------------------------------
# La marca de propiedad
# ----------------------------------------------------------------------
def test_la_marca_no_se_puede_fijar_desde_el_cuerpo(client_auth) -> None:
    proyecto = client_auth.post(
        "/api/projects",
        json={"title": "Listo", "commands": ["ls"], "script_owned": True},
    ).json()

    assert proyecto["script_owned"] is False


def test_el_token_solo_ve_y_toca_lo_suyo(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso
) -> None:
    ajeno = _proyecto_del_panel(client_auth)
    suyo = _alta(client_local, cabecera, raiz).json()

    assert [p["id"] for p in client_local.get(
        "/api/projects", headers=cabecera
    ).json()] == [suyo["id"]]

    for metodo, ruta in (
        ("POST", f"/api/projects/{ajeno['id']}/run"),
        ("DELETE", f"/api/projects/{ajeno['id']}"),
    ):
        resp = client_local.request(metodo, ruta, headers=cabecera)
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "err.script_project_foreign"

    assert tmux_falso == {}
    assert ajeno["id"] in {p["id"] for p in client_auth.get("/api/projects").json()}


def test_un_proyecto_que_no_existe_da_404(client_local, cabecera) -> None:
    for metodo, ruta in (
        ("POST", "/api/projects/nada/run"),
        ("DELETE", "/api/projects/nada"),
    ):
        assert client_local.request(metodo, ruta, headers=cabecera).status_code == 404


def test_solo_mata_sesiones_de_sus_proyectos(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso
) -> None:
    ajeno = _proyecto_del_panel(client_auth)
    sesion_ajena = client_auth.post(f"/api/projects/{ajeno['id']}/run").json()["name"]
    tmux_falso["a-mano"] = {}

    for nombre in (sesion_ajena, "a-mano", "no-existe"):
        resp = client_local.post(f"/api/kill-session/{nombre}", headers=cabecera)
        assert resp.status_code == 403, nombre
        assert resp.json()["detail"]["code"] == "err.script_session_foreign"

    assert set(tmux_falso) == {sesion_ajena, "a-mano"}


def test_al_borrar_el_proyecto_su_sesion_deja_de_ser_suya(
    client_local, cabecera, raiz: Path, tmux_falso
) -> None:
    """Por eso el receptor mata antes de borrar; está en la documentación."""
    proyecto = _alta(client_local, cabecera, raiz).json()
    sesion = client_local.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).json()["name"]
    client_local.delete(f"/api/projects/{proyecto['id']}", headers=cabecera)

    assert client_local.post(
        f"/api/kill-session/{sesion}", headers=cabecera
    ).status_code == 403


def test_una_sesion_renombrada_sigue_siendo_suya(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proyecto = _alta(client_local, cabecera, raiz).json()
    sesion = client_local.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).json()["name"]
    monkeypatch.setattr(main, "session_exists", lambda n: n == sesion)
    monkeypatch.setattr(
        main, "rename_session",
        lambda old, new: tmux_falso.__setitem__(new, tmux_falso.pop(old)),
    )
    client_auth.post(f"/api/rename-session/{sesion}", json={"new_name": "renombrada"})

    assert client_local.post(
        "/api/kill-session/renombrada", headers=cabecera
    ).status_code == 200


def test_si_willy_edita_el_proyecto_el_token_no_lanza_lo_editado(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso
) -> None:
    """El panel no aplica estas reglas, así que hay que volver a mirar al lanzar."""
    proyecto = _alta(client_local, cabecera, raiz).json()
    edicion = {
        "title": proyecto["title"],
        "cwd": proyecto["cwd"],
        "commands": ["rm -rf ~"],
        "space": proyecto["space"],
    }

    editado = client_auth.put(f"/api/projects/{proyecto['id']}", json=edicion).json()
    assert editado["script_owned"] is True, "editar no quita la marca"

    resp = client_local.post(f"/api/projects/{proyecto['id']}/run", headers=cabecera)
    assert resp.status_code == 403
    assert tmux_falso == {}

    # Con un segundo comando tampoco, aunque el primero siga siendo válido.
    client_auth.put(
        f"/api/projects/{proyecto['id']}",
        json={**edicion, "commands": [COMANDO_REAL, "rm -rf ~"]},
    )
    assert client_local.post(
        f"/api/projects/{proyecto['id']}/run", headers=cabecera
    ).status_code == 403

    # Y Willy sí puede lanzarlo: las reglas son del token, no del proyecto.
    client_auth.put(f"/api/projects/{proyecto['id']}", json=edicion)
    assert client_auth.post(f"/api/projects/{proyecto['id']}/run").status_code == 200


def test_si_willy_saca_la_carpeta_de_la_raiz_el_token_no_lo_lanza(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso
) -> None:
    proyecto = _alta(client_local, cabecera, raiz).json()
    client_auth.put(
        f"/api/projects/{proyecto['id']}",
        json={
            "title": proyecto["title"],
            "cwd": "/",
            "commands": proyecto["commands"],
            "space": proyecto["space"],
        },
    )

    resp = client_local.post(f"/api/projects/{proyecto['id']}/run", headers=cabecera)

    assert resp.status_code == 403
    assert tmux_falso == {}


def test_si_una_carpeta_pasa_a_ser_un_enlace_el_token_no_lo_sigue(
    client_local, cabecera, raiz: Path, tmp_path: Path, tmux_falso
) -> None:
    """La ruta se guarda resuelta, pero se vuelve a resolver al lanzar."""
    carpeta = raiz / "movida"
    carpeta.mkdir()
    proyecto = _alta(client_local, cabecera, raiz, cwd=str(carpeta)).json()
    carpeta.rmdir()
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    carpeta.symlink_to(fuera)

    resp = client_local.post(f"/api/projects/{proyecto['id']}/run", headers=cabecera)

    assert resp.status_code == 403
    assert tmux_falso == {}


# ----------------------------------------------------------------------
# Intentos fallidos
# ----------------------------------------------------------------------
def _falla(client, veces: int = 5) -> list[int]:
    return [
        client.get("/api/projects", headers={CABECERA: "equivocado"}).status_code
        for _ in range(veces)
    ]


def test_tras_cinco_fallos_ni_el_token_bueno_entra(client_local, cabecera) -> None:
    assert _falla(client_local) == [401] * 5

    assert client_local.get("/api/projects", headers=cabecera).status_code == 429
    assert client_local.get(
        "/api/projects", headers={CABECERA: "equivocado"}
    ).status_code == 429


def test_un_token_malo_no_toca_el_contador_del_login(
    client_local, data_dir: Path
) -> None:
    _falla(client_local, 7)

    assert not (data_dir / "login_failures.json").exists()
    assert auth._login_failures == {}
    assert client_local.post(
        "/api/login", json={"username": USERNAME, "password": PASSWORD}
    ).status_code == 200


def test_el_bloqueo_se_levanta_solo_y_no_se_alarga_con_mas_fallos(
    client_local, cabecera, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = [1000.0]
    monkeypatch.setattr(script_token, "_now", lambda: ahora[0])
    _falla(client_local)

    ahora[0] += script_token._BLOCK_SECONDS - 1
    assert _falla(client_local, 1) == [429]
    assert client_local.get("/api/projects", headers=cabecera).status_code == 429

    ahora[0] += 1
    assert client_local.get("/api/projects", headers=cabecera).status_code == 200
    assert script_token._failures == {}


def test_los_fallos_espaciados_no_bloquean(
    client_local, cabecera, monkeypatch: pytest.MonkeyPatch
) -> None:
    ahora = [1000.0]
    monkeypatch.setattr(script_token, "_now", lambda: ahora[0])
    for _ in range(12):
        ahora[0] += script_token._WINDOW_SECONDS + 1
        assert _falla(client_local, 1) == [401]

    assert client_local.get("/api/projects", headers=cabecera).status_code == 200


def test_toda_la_red_de_loopback_cuenta_como_una(cabecera) -> None:
    """Cambiar de 127.0.0.2 a 127.0.0.3 no regala intentos."""
    for host in ("127.0.0.2", "127.0.0.3", "127.0.0.4", "127.0.0.5", "::1"):
        with TestClient(main.app, client=(host, 50000)) as c:
            assert _falla(c, 1) == [401]

    with TestClient(main.app, client=("127.0.0.6", 50000)) as c:
        assert c.get("/api/projects", headers=cabecera).status_code == 429


def test_fuera_de_la_maquina_no_se_compara_ni_se_cuenta(client) -> None:
    """Ahí el token no sirve de nada: no hay nada que adivinar ni que frenar."""
    assert _falla(client, 8) == [401] * 8
    assert script_token._failures == {}


def test_el_contador_no_crece_sin_tope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script_token, "_MAX_TRACKED", 3)
    for numero in range(10):
        script_token.register_failure(f"clave-{numero}")

    assert len(script_token._failures) == 3


# ----------------------------------------------------------------------
# Registro
# ----------------------------------------------------------------------
def test_cada_uso_queda_registrado_con_su_resultado(
    client_local, cabecera, raiz: Path, client_auth, tmux_falso, data_dir: Path
) -> None:
    token_id = script_token.match(cabecera[CABECERA])
    ajeno = _proyecto_del_panel(client_auth)

    client_local.get("/api/projects", headers=cabecera)
    proyecto = _alta(client_local, cabecera, raiz).json()
    client_local.post(f"/api/projects/{proyecto['id']}/run", headers=cabecera)
    _alta(client_local, cabecera, raiz, commands=["rm -rf ~"])
    _alta(client_local, cabecera, raiz, cwd="/")
    client_local.post(f"/api/projects/{ajeno['id']}/run", headers=cabecera)
    client_local.post("/api/kill-session/ajena", headers=cabecera)
    client_local.delete(f"/api/projects/{proyecto['id']}", headers=cabecera)
    client_local.get("/api/sessions", headers=cabecera)
    client_local.get("/api/projects", headers={CABECERA: "equivocado"})

    entradas = _auditoria(data_dir)
    assert [(e["detail"]["result"], e["detail"]["status"]) for e in entradas] == [
        ("accepted", 200),
        ("accepted", 201),
        ("accepted", 200),
        ("command-rejected", 403),
        ("cwd-rejected", 403),
        ("foreign-project", 403),
        ("foreign-session", 403),
        ("accepted", 200),
        ("not-evaluated", 401),
        ("invalid-token", 401),
    ]
    assert {e["user"] for e in entradas} == {"script"}
    assert entradas[3]["detail"]["command"] == "rm -rf ~"
    assert entradas[3]["detail"]["reason"]
    assert entradas[0]["target"] == "GET /api/projects"
    assert entradas[0]["detail"]["token_id"] == token_id
    assert entradas[1]["detail"]["project_id"] == proyecto["id"]
    assert entradas[2]["detail"]["session"] == proyecto["title"]
    assert entradas[0]["ip"] == "127.0.0.1"


def test_el_bloqueo_y_el_acceso_de_fuera_tambien_se_registran(
    client_local, client, cabecera, data_dir: Path
) -> None:
    client.get("/api/projects", headers=cabecera)
    _falla(client_local)
    client_local.get("/api/projects", headers=cabecera)

    resultados = [e["detail"]["result"] for e in _auditoria(data_dir)]
    assert resultados == ["not-local", *["invalid-token"] * 5, "rate-limited"]


def test_el_registro_no_contiene_el_token(
    client_local, cabecera, raiz: Path, data_dir: Path
) -> None:
    falso = "token-equivocado-que-no-debe-quedar-escrito"
    client_local.get("/api/projects", headers=cabecera)
    _alta(client_local, cabecera, raiz)
    client_local.get("/api/projects", headers={CABECERA: falso})

    registro = (data_dir / "audit.log").read_text(encoding="utf-8")
    assert cabecera[CABECERA] not in registro
    assert falso not in registro


def test_el_panel_sin_token_no_deja_lineas_de_token(
    client_auth, data_dir: Path
) -> None:
    client_auth.get("/api/projects")

    assert _auditoria(data_dir) == []


def test_una_excepcion_en_la_ruta_tambien_queda_registrada(
    cabecera, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rompe():
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(main, "list_projects", rompe)
    with TestClient(
        main.app, client=("127.0.0.1", 50000), raise_server_exceptions=False
    ) as c:
        assert c.get("/api/projects", headers=cabecera).status_code == 500

    assert _auditoria(data_dir)[0]["detail"]["status"] == 500


# ----------------------------------------------------------------------
# Las pestañas se enteran
# ----------------------------------------------------------------------
def test_lo_creado_con_token_avisa_a_las_pestanas(
    client_local, cabecera, raiz: Path
) -> None:
    """El espacio y el proyecto, cada uno con su evento."""
    client_local.post(
        "/api/login", json={"username": USERNAME, "password": PASSWORD}
    )
    with client_local.websocket_connect("/api/events") as ws:
        _alta(client_local, cabecera, raiz)
        assert ws.receive_json() == {"type": "spaces-changed"}
        assert ws.receive_json() == {"type": "projects-changed"}
