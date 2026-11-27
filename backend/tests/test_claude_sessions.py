"""Sesiones de Claude Code: cliente, filtros, secretos y endpoints.

El API real nunca se toca: un servidor HTTP local de prueba hace de API de
sesiones, con datos **sintéticos** (ninguna frase de una conversación real).
Lo que se vigila, sobre todo, son las reglas de seguridad de Willy: nada se
escribe en disco, nada de lo buscado llega a los logs y el 503 se devuelve
tal cual sin intentar encenderlo.
"""
# ruff: noqa: E501  (fixtures y llamadas largas: se leen mejor enteras)
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

import claude_sessions
import config
import library_store
import tmux_service

UUID = "11111111-2222-3333-4444-555555555555"
OTRO_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
# Lo "buscado": una contraseña de mentira. No debe aparecer en ningún log.
CONSULTA_SECRETA = "hunter2-zz-no-debe-salir"


class ApiFalsa:
    """Un API de sesiones de mentira: respuestas por ruta, y lo que recibió."""

    def __init__(self) -> None:
        self.respuestas: dict[str, tuple[int, object, float]] = {}
        self.peticiones: list[tuple[str, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                outer.peticiones.append((url.path, parse_qs(url.query)))
                estado, cuerpo, espera = outer.respuestas.get(
                    url.path, (404, {"error": "no hay"}, 0)
                )
                if espera:
                    time.sleep(espera)
                datos = (
                    cuerpo.encode() if isinstance(cuerpo, str)
                    else json.dumps(cuerpo).encode()
                )
                try:
                    self.send_response(estado)
                    self.send_header("Content-Length", str(len(datos)))
                    self.end_headers()
                    self.wfile.write(datos)
                except OSError:
                    pass

            def log_message(self, *a):  # silencio
                pass

        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}"
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def pon(self, ruta: str, cuerpo, estado: int = 200, espera: float = 0) -> None:
        self.respuestas[ruta] = (estado, cuerpo, espera)

    def cierra(self) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()


@pytest.fixture
def api(monkeypatch):
    falsa = ApiFalsa()
    monkeypatch.setattr(config, "CLAUDE_SESSIONS_URL", falsa.url)
    yield falsa
    falsa.cierra()


def _fila(sid: str, cwd: str, **extra) -> dict:
    base = {
        "id": sid, "project": cwd, "cwd": cwd, "branch": "main",
        "first_ts": "2026-11-01T10:00:00.000Z", "last_ts": "2026-11-02T10:00:00.000Z",
        "n_messages": 3, "title": "Título de prueba", "title_kind": "ai",
        "size": 999, "has_compact": 0, "empty": 0, "n_subagent": 0,
        "n_subagent_files": 0, "path": "/home/x/.claude/projects/ruta/secreta.jsonl",
    }
    base.update(extra)
    return base


# ----------------------------------------------------------------------
# Funciones puras
# ----------------------------------------------------------------------
class TestEnProyecto:
    def test_igual_hijo_y_worktree(self):
        assert claude_sessions.en_proyecto("/p/mvp-lab", "/p/mvp-lab")
        assert claude_sessions.en_proyecto("/p/mvp-lab/sub", "/p/mvp-lab")
        assert claude_sessions.en_proyecto(
            "/p/mvp-lab/.claude/worktrees/rama", "/p/mvp-lab"
        )

    def test_la_subcadena_no_basta(self):
        assert not claude_sessions.en_proyecto("/p/mvp-lab-analisis", "/p/mvp-lab")
        assert not claude_sessions.en_proyecto("/p/otro/mvp-lab", "/p/mvp-lab")
        assert not claude_sessions.en_proyecto(None, "/p/mvp-lab")
        assert not claude_sessions.en_proyecto("", "/p/mvp-lab")

    def test_barra_final_y_tilde(self, monkeypatch):
        monkeypatch.setenv("HOME", "/home/prueba")
        assert claude_sessions.en_proyecto("/home/prueba/x", "~/x/")
        assert claude_sessions.en_proyecto("/p/mvp-lab/", "/p/mvp-lab")


class TestIds:
    def test_uuid_entero(self):
        assert claude_sessions.uuid_valido(UUID)
        assert not claude_sessions.uuid_valido(UUID[:8])
        assert not claude_sessions.uuid_valido(UUID + "; rm -rf ~")
        assert not claude_sessions.uuid_valido("")

    def test_prefijo_hexadecimal(self):
        assert claude_sessions.id_valido("1111")
        assert claude_sessions.id_valido(UUID)
        for malo in ("../x", "abc", "zzzz", "1111/2222", "11 11", "1111;ls", ""):
            assert not claude_sessions.id_valido(malo), malo


class TestTrocearFragmento:
    def test_marca_lo_encontrado(self):
        trozos = claude_sessions.trocear_fragmento("antes «medio» después")
        assert trozos == [
            {"text": "antes ", "mark": False, "secret": False},
            {"text": "medio", "mark": True, "secret": False},
            {"text": " después", "mark": False, "secret": False},
        ]

    def test_html_se_deja_como_texto(self):
        trozos = claude_sessions.trocear_fragmento("«<b>hola</b>» <script>")
        assert "".join(t["text"] for t in trozos) == "<b>hola</b> <script>"

    @pytest.mark.parametrize(
        "secreto",
        [
            "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
            "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2",
            "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1",
            "xoxb-1234567890-abcdefghij",
            "AKIA" + "ABCDEFGHIJKLMNOP",
            "eyJhbGciOiJI.eyJzdWIiOiIx.abcdefghijk",
            "Zm9vYmFyMTIzNDU2Nzg5MGFiY2RlZjEyMzQ1Ng",
        ],
    )
    def test_oculta_claves_conocidas(self, secreto):
        trozos = claude_sessions.trocear_fragmento(f"usa {secreto} aquí")
        ocultos = [t["text"] for t in trozos if t["secret"]]
        assert ocultos == [secreto]

    @pytest.mark.parametrize(
        "texto,valor",
        [
            ("password=Zx9!pq", "Zx9!pq"),
            ("contraseña: miClave77", "miClave77"),
            ("La Contraseña = \"abc123\"", "abc123"),
            ("token: qwerty", "qwerty"),
        ],
    )
    def test_oculta_el_valor_y_no_la_etiqueta(self, texto, valor):
        trozos = claude_sessions.trocear_fragmento(texto)
        assert [t["text"] for t in trozos if t["secret"]] == [valor]
        assert "".join(t["text"] for t in trozos) == texto

    def test_no_oculta_lo_corriente(self):
        for texto in (
            "una frase normal con palabras largas como internacionalización",
            f"sesión {UUID} abierta",
            "/home/willy/proyectos/muxspace/frontend/src/components/Sidebar.jsx",
            "la clave es un concepto",
        ):
            trozos = claude_sessions.trocear_fragmento(texto)
            assert not any(t["secret"] for t in trozos), texto

    def test_secreto_que_cruza_la_marca(self):
        trozos = claude_sessions.trocear_fragmento("x sk-«abcdefghijklmnop»qrstuv y")
        assert "".join(t["text"] for t in trozos) == "x sk-abcdefghijklmnopqrstuv y"
        assert [t["text"] for t in trozos if t["secret"]] == [
            "sk-", "abcdefghijklmnop", "qrstuv",
        ]
        assert [t["mark"] for t in trozos if t["secret"]] == [False, True, False]

    def test_entrada_rara(self):
        assert claude_sessions.trocear_fragmento("") == []
        assert claude_sessions.trocear_fragmento(None) == []


# ----------------------------------------------------------------------
# Cliente contra el API simulado
# ----------------------------------------------------------------------
class TestListar:
    def test_200_filtra_por_carpeta_y_quita_campos(self, api):
        api.pon("/sessions", {"sessions": [
            _fila(UUID, "/p/mvp-lab"),
            _fila("2" * 8 + UUID[8:], "/p/mvp-lab-analisis"),
            _fila("3" * 8 + UUID[8:], "/p/mvp-lab/.claude/worktrees/r"),
        ]})
        filas = claude_sessions.listar("/p/mvp-lab")
        assert [f["id"][0] for f in filas] == ["1", "3"]
        for f in filas:
            assert "cwd" not in f and "size" not in f and "path" not in f
        assert api.peticiones[0][1]["project"] == ["/p/mvp-lab"]

    def test_sin_proyecto_no_filtra(self, api):
        api.pon("/sessions", {"sessions": [_fila(UUID, "/p/a"), _fila(OTRO_UUID, "/p/b")]})
        assert len(claude_sessions.listar()) == 2

    def test_fecha_mala_no_sale_al_api(self, api):
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar(since="ayer; rm")
        assert e.value.status == 400
        assert api.peticiones == []


class TestBuscar:
    def test_200_trocea_y_filtra_por_proyecto(self, api):
        api.pon("/sessions/search", {"query": CONSULTA_SECRETA, "count": 2, "hits": [
            {"session_id": UUID, "project": "/p/mvp-lab", "title": "t", "role": "user",
             "kind": "text", "ts": "2026-11-01T10:00:00Z", "agent_id": "",
             "snippet": "dijo «hola» y password=abc"},
            {"session_id": OTRO_UUID, "project": "/p/mvp-lab-analisis", "title": "t",
             "role": "user", "kind": "text", "ts": "", "agent_id": "", "snippet": "«x»"},
        ]})
        hits = claude_sessions.buscar("hola", project_cwd="/p/mvp-lab")
        assert [h["session_id"] for h in hits] == [UUID]
        assert "snippet" not in hits[0]
        assert any(t["secret"] for t in hits[0]["segments"])

    def test_pasa_los_filtros_al_api(self, api):
        api.pon("/sessions/search", {"hits": []})
        claude_sessions.buscar(
            "a.*b", role="assistant", regex=True,
            kinds=["text", "thinking", "inventado"], subagents=True, sort="relevance",
        )
        consulta = api.peticiones[0][1]
        assert consulta["role"] == ["assistant"]
        assert consulta["regex"] == ["1"] and consulta["subagents"] == ["1"]
        assert consulta["kinds"] == ["text,thinking"]
        assert consulta["sort"] == ["relevance"]

    @pytest.mark.parametrize("q", ["", "   ", "x" * 501])
    def test_consulta_invalida(self, api, q):
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.buscar(q)
        assert e.value.code == "err.claude_sessions_query_invalid"
        assert api.peticiones == []

    def test_rol_y_orden_desconocidos(self, api):
        with pytest.raises(claude_sessions.SessionsError):
            claude_sessions.buscar("x", role="system")
        with pytest.raises(claude_sessions.SessionsError):
            claude_sessions.buscar("x", sort="azar")


class TestErrores:
    def test_503_tal_cual(self, api):
        api.pon("/sessions", {"error": "Desactivadas.", "detail": "Para activarlas: touch /x"}, 503)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar()
        assert e.value.status == 503
        assert e.value.detail == {
            "code": "err.claude_sessions_disabled",
            "mensaje": "Desactivadas.",
            "detail": "Para activarlas: touch /x",
        }
        # No se intentó nada más: una sola petición y ninguna de «encender».
        assert [p for p, _ in api.peticiones] == ["/sessions"]

    def test_409_trae_las_coincidencias(self, api):
        api.pon("/sessions/1111", {"error": "x", "matches": [
            {"id": UUID, "title": "uno", "path": "/secreto"},
            {"id": OTRO_UUID, "title": "dos"},
        ]}, 409)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.leer("1111")
        assert e.value.status == 409
        assert e.value.extra["matches"] == [
            {"id": UUID, "title": "uno"}, {"id": OTRO_UUID, "title": "dos"},
        ]

    def test_404(self, api):
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.leer(UUID)
        assert e.value.code == "err.claude_session_not_found"

    def test_400_no_reenvia_el_texto_del_api(self, api):
        api.pon("/sessions/search", {"error": f"regex mala: {CONSULTA_SECRETA}"}, 400)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.buscar("(")
        assert CONSULTA_SECRETA not in json.dumps(e.value.detail)

    def test_500_y_json_ilegible(self, api):
        api.pon("/sessions", {"error": "x"}, 500)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar()
        assert e.value.code == "err.claude_sessions_upstream"
        api.pon("/sessions", "esto no es json", 200)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar()
        assert e.value.code == "err.claude_sessions_upstream"

    def test_timeout(self, api, monkeypatch):
        monkeypatch.setattr(claude_sessions, "TIMEOUT_S", 0.2)
        api.pon("/sessions", {"sessions": []}, espera=1.0)
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar()
        assert e.value.status == 504
        assert e.value.code == "err.claude_sessions_timeout"

    def test_api_caido(self, api):
        api.cierra()
        with pytest.raises(claude_sessions.SessionsError) as e:
            claude_sessions.listar()
        assert e.value.status == 502
        assert e.value.code == "err.claude_sessions_down"


class TestLeerExportarRetomar:
    def test_leer_reconstruye_con_lista_blanca(self, api):
        api.pon(f"/sessions/{UUID}", {
            "session": _fila(UUID, "/p/x"), "offset": 0, "truncated": True,
            "messages": [{"role": "user", "ts": "t", "agent": "", "ruta": "/secreto",
                          "blocks": [{"kind": "text", "text": "hola", "error": False,
                                      "extra": 1}]}],
        })
        datos = claude_sessions.leer(UUID, tools=True)
        assert datos["truncated"] is True
        assert datos["messages"][0]["blocks"] == [
            {"kind": "text", "text": "hola", "error": False}
        ]
        assert "ruta" not in datos["messages"][0]
        assert "path" not in datos["session"] and "cwd" not in datos["session"]
        assert api.peticiones[0][1]["tools"] == ["1"]

    def test_id_invalido_no_sale_al_api(self, api):
        for malo in ("../x", "zz", "1111; ls"):
            with pytest.raises(claude_sessions.SessionsError):
                claude_sessions.leer(malo)
            with pytest.raises(claude_sessions.SessionsError):
                claude_sessions.exportar(malo)
            with pytest.raises(claude_sessions.SessionsError):
                claude_sessions.destino_de_retomar(malo)
        assert api.peticiones == []

    def test_exportar(self, api):
        api.pon(f"/sessions/{UUID}/export", "# Sesión\n\nhola\n")
        texto, nombre = claude_sessions.exportar(UUID)
        assert texto.startswith("# Sesión") and nombre == "11111111.md"

    def test_retomar_rehace_el_comando(self, api, tmp_path):
        carpeta = tmp_path / "con espacio; y cosas"
        carpeta.mkdir()
        api.pon(f"/sessions/{UUID}/resume", {
            "cwd": str(carpeta), "exists": True, "error": "",
            "command": f"cd 'x' && claude --resume {UUID}",
        })
        destino = claude_sessions.destino_de_retomar(UUID)
        assert destino["exists"] and destino["session_id"] == UUID
        assert destino["command"] == (
            f"cd '{carpeta}' && claude --resume {UUID}"
        )

    def test_retomar_carpeta_inexistente(self, api, tmp_path):
        api.pon(f"/sessions/{UUID}/resume", {
            "cwd": str(tmp_path / "no-existe"), "exists": True,
            "command": f"cd x && claude --resume {UUID}",
        })
        destino = claude_sessions.destino_de_retomar(UUID)
        assert destino["exists"] is False and destino["command"] == ""

    def test_retomar_ignora_un_comando_raro_del_api(self, api, tmp_path):
        api.pon(f"/sessions/{UUID}/resume", {
            "cwd": str(tmp_path), "exists": True,
            "command": f"cd x && claude --resume {UUID}; rm -rf ~",
        })
        destino = claude_sessions.destino_de_retomar(UUID)
        assert destino["exists"] is False and destino["command"] == ""


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------
class TestEndpoints:
    def test_exigen_sesion(self, client, api):
        assert client.get("/api/claude-sessions").status_code == 401
        assert client.post("/api/claude-sessions/search", json={"q": "x"}).status_code == 401
        assert client.get(f"/api/claude-sessions/{UUID}").status_code == 401
        assert client.get(f"/api/claude-sessions/{UUID}/export").status_code == 401
        assert client.get(f"/api/claude-sessions/{UUID}/resume").status_code == 401
        resp = client.post(f"/api/claude-sessions/{UUID}/open-in-grid", json={})
        assert resp.status_code == 401
        assert api.peticiones == []

    def test_cabeceras_privadas(self, client_auth, api):
        api.pon("/sessions", {"sessions": []})
        resp = client_auth.get("/api/claude-sessions")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"
        assert "access-control-allow-origin" not in resp.headers

    def test_503_con_mensaje_y_comando(self, client_auth, api):
        api.pon("/sessions", {"error": "Apagadas.", "detail": "touch /x"}, 503)
        resp = client_auth.get("/api/claude-sessions")
        assert resp.status_code == 503
        assert resp.json()["detail"] == {
            "code": "err.claude_sessions_disabled", "mensaje": "Apagadas.", "detail": "touch /x",
        }

    def test_api_caido_502(self, client_auth, api):
        api.cierra()
        resp = client_auth.get("/api/claude-sessions")
        assert resp.status_code == 502
        assert resp.json()["detail"]["code"] == "err.claude_sessions_down"

    def test_lista_de_un_proyecto_usa_su_carpeta(self, client_auth, api, tmp_path):
        carpeta = tmp_path / "proy"
        carpeta.mkdir()
        proj = library_store.add_project("Proy", str(carpeta), ["claude"])
        api.pon("/sessions", {"sessions": [
            _fila(UUID, str(carpeta)),
            _fila(OTRO_UUID, str(carpeta) + "-analisis"),
        ]})
        resp = client_auth.get(f"/api/claude-sessions?project_id={proj.id}")
        assert [s["id"] for s in resp.json()["sessions"]] == [UUID]

    def test_proyecto_inexistente_o_sin_carpeta(self, client_auth, api):
        assert client_auth.get("/api/claude-sessions?project_id=nada").status_code == 404
        proj = library_store.add_project("Sin carpeta", None, ["claude"])
        resp = client_auth.get(f"/api/claude-sessions?project_id={proj.id}")
        assert resp.status_code == 400
        assert api.peticiones == []

    def test_busqueda_no_deja_rastro(self, client_auth, api, caplog, data_dir):
        api.pon("/sessions/search", {"hits": [
            {"session_id": UUID, "project": "/p", "title": "t", "role": "user",
             "kind": "text", "ts": "", "agent_id": "",
             "snippet": f"«{CONSULTA_SECRETA}»"},
        ]})
        antes = sorted(p.name for p in data_dir.rglob("*"))
        with caplog.at_level(logging.DEBUG):
            resp = client_auth.post(
                "/api/claude-sessions/search", json={"q": CONSULTA_SECRETA}
            )
            # Y también cuando falla el API.
            api.pon("/sessions/search", {"error": CONSULTA_SECRETA}, 400)
            client_auth.post("/api/claude-sessions/search", json={"q": CONSULTA_SECRETA})
            api.cierra()
            client_auth.post("/api/claude-sessions/search", json={"q": CONSULTA_SECRETA})
        assert resp.status_code == 200
        assert resp.json()["hits"][0]["segments"][0]["text"] == CONSULTA_SECRETA
        assert CONSULTA_SECRETA not in caplog.text
        # Ni en el registro de auditoría (que sí se escribe, sin la consulta).
        log = (data_dir / "audit.log").read_text()
        assert "claude-sessions-search" in log
        assert CONSULTA_SECRETA not in log
        # Y nada nuevo en disco salvo ese registro y los stores de siempre.
        nuevos = set(p.name for p in data_dir.rglob("*")) - set(antes)
        assert nuevos <= {"audit.log"}
        for p in data_dir.rglob("*"):
            if p.is_file():
                assert CONSULTA_SECRETA not in p.read_text(errors="ignore")

    def test_busqueda_va_por_post_y_no_por_get(self, client_auth):
        assert client_auth.get("/api/claude-sessions/search").status_code in (400, 405)

    def test_exportar_es_descarga(self, client_auth, api):
        api.pon(f"/sessions/{UUID}/export", "# hola\n")
        resp = client_auth.get(f"/api/claude-sessions/{UUID}/export")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == 'attachment; filename="11111111.md"'
        assert resp.text == "# hola\n"

    def test_id_malo_400(self, client_auth, api):
        assert client_auth.get("/api/claude-sessions/zz").status_code == 400
        assert api.peticiones == []

    def test_409_se_propaga(self, client_auth, api):
        api.pon("/sessions/1111", {"error": "x", "matches": [{"id": UUID, "title": "a"}]}, 409)
        resp = client_auth.get("/api/claude-sessions/1111")
        assert resp.status_code == 409
        assert resp.json()["detail"]["matches"] == [{"id": UUID, "title": "a"}]

    def test_comando_de_retomar_a_mano(self, client_auth, api, tmp_path):
        api.pon(f"/sessions/{UUID}/resume", {
            "cwd": str(tmp_path), "exists": True, "command": f"cd x && claude --resume {UUID}",
        })
        resp = client_auth.get(f"/api/claude-sessions/{UUID}/resume")
        assert resp.json() == {
            "exists": True, "command": f"cd {tmp_path} && claude --resume {UUID}",
        }


class TestRetomarEnElGrid:
    @pytest.fixture
    def tmux(self, monkeypatch):
        """tmux de mentira: se anota qué se pediría crear."""
        creadas: list[dict] = []
        monkeypatch.setattr(
            "main.list_sessions", lambda: [tmux_service.TmuxSession(name="Claude 11111111", windows=1, attached=False)],
        )

        def crear(name, command=None, cwd=None):
            creadas.append({"name": name, "command": command, "cwd": cwd})
            return True

        monkeypatch.setattr("main.create_session", crear)
        return creadas

    def _api(self, api, carpeta):
        api.pon(f"/sessions/{UUID}/resume", {
            "cwd": str(carpeta), "exists": True,
            "command": f"cd x && claude --resume {UUID}",
        })

    def test_crea_la_terminal_con_el_comando(self, client_auth, api, tmux, tmp_path):
        self._api(api, tmp_path)
        resp = client_auth.post(f"/api/claude-sessions/{UUID}/open-in-grid", json={})
        assert resp.status_code == 200, resp.text
        # Ya había «Claude 11111111»: el nombre sigue la convención del sufijo.
        assert resp.json() == {"name": "Claude 11111111 (2)", "created": True}
        assert tmux == [{
            "name": "Claude 11111111 (2)",
            "command": f"claude --resume {UUID}",
            "cwd": str(tmp_path),
        }]

    @pytest.mark.parametrize(
        "malo", ["1111", "zz", UUID + ";ls", "11111111-2222-3333-4444-55555555555g"]
    )
    def test_id_no_valido_no_hace_nada(self, client_auth, api, tmux, malo):
        resp = client_auth.post(f"/api/claude-sessions/{malo}/open-in-grid", json={})
        assert resp.status_code in (400, 404)
        assert tmux == [] and api.peticiones == []

    def test_carpeta_que_ya_no_existe(self, client_auth, api, tmux, tmp_path):
        self._api(api, tmp_path / "borrada")
        resp = client_auth.post(f"/api/claude-sessions/{UUID}/open-in-grid", json={})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "err.claude_session_cwd_missing"
        assert tmux == []

    def test_503_no_crea_nada(self, client_auth, api, tmux):
        api.pon(f"/sessions/{UUID}/resume", {"error": "Apagadas.", "detail": "touch /x"}, 503)
        resp = client_auth.post(f"/api/claude-sessions/{UUID}/open-in-grid", json={})
        assert resp.status_code == 503 and tmux == []

    def test_desde_un_proyecto_va_a_su_espacio_y_se_vincula(
        self, client_auth, api, tmux, tmp_path
    ):
        import space_store

        espacio = space_store.create_space("Mi espacio")
        proj = library_store.add_project(
            "Proy", str(tmp_path), ["claude"], space=espacio.id
        )
        self._api(api, tmp_path)
        resp = client_auth.post(
            f"/api/claude-sessions/{UUID}/open-in-grid", json={"project_id": proj.id}
        )
        nombre = resp.json()["name"]
        assert space_store.assignments()[nombre] == espacio.id
        assert library_store.session_projects()[nombre] == proj.id

    def test_proyecto_desconocido_404(self, client_auth, api, tmux):
        resp = client_auth.post(
            f"/api/claude-sessions/{UUID}/open-in-grid", json={"project_id": "nada"}
        )
        assert resp.status_code == 404 and tmux == []

    def test_el_token_de_scripts_no_llega(self, client_local, api, tmux, tmp_path):
        """Lo del token de scripts no pasa: la ruta es solo del panel."""
        self._api(api, tmp_path)
        resp = client_local.post(
            f"/api/claude-sessions/{UUID}/open-in-grid", json={},
            headers={"X-Muxspace-Script-Token": "cualquiera"},
        )
        assert resp.status_code in (401, 403)
        assert tmux == []


def test_no_toca_los_datos_reales(data_dir: Path):
    """El módulo no tiene ruta de datos propia: nada que escribir."""
    import claude_sessions as cs

    fuente = Path(cs.__file__).read_text()
    assert "_DATA_DIR" not in fuente and "write_private" not in fuente
    assert "open(" not in fuente.replace("_opener.open(", "")
