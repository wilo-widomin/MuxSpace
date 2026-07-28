"""`auth.py`: el límite de intentos, la caducidad de sesiones y la lista negra.

Estas tres piezas son lo único que hay entre un desconocido y una shell. No
hay una segunda línea que limite el daño: quien pasa esta puerta ejecuta
comandos como el usuario que corre el backend.

El módulo hace bien dos cosas que suelen faltar en este patrón, y son las que
más vale fijar porque son las que un refactor "de limpieza" se lleva por
delante sin que nada salte:

  - **El registro de fallos se persiste en disco.** Un atacante no resetea el
    rate limit tirando el backend (ni esperando a que se reinicie solo).
  - **HTTP Basic pasa por el mismo contador.** El agujero clásico es limitar
    `/api/login` y dejar `Authorization: Basic` contra cualquier endpoint
    autenticado como vía de fuerza bruta ilimitada.

## La regla de este archivo

**El código de estado no basta.** Un 429 se puede producir por accidente y un
403 lo emiten dos middlewares distintos. Cada caso comprueba además el
*efecto*: qué quedó en `auth._login_failures`, qué se escribió en el JSON, si
el token sigue en `_sessions`, o —en el WebSocket— si el handler llegó
siquiera a consultar tmux. Donde un veredicto podría venir de otra puerta hay
un **control positivo** al lado que demuestra que esa otra puerta estaba
abierta.

## Las cuatro trampas del andamiaje (medidas, no supuestas)

1. **El reloj.** `auth.py` hace `import time`, así que `auth.time` **es** el
   módulo `time` del proceso: `monkeypatch.setattr(auth.time, "time", ...)`
   —la receta obvia— parchea `time.time` para TODO el intérprete, incluidos
   httpx, anyio y el propio pytest. Aquí se sustituye `auth.time` entero por
   un `_Reloj` que solo ve `auth` (y que delega en el módulo real lo que no
   sea `time()`). `test_auto_el_reloj_falso_no_se_filtra_al_resto_del_proceso`
   comprueba las dos mitades de esa afirmación.

2. **El mtime de `banned_ips.json`.** La recarga en caliente compara el
   `st_mtime` con el que tiene en memoria; dos escrituras dentro del mismo
   segundo pueden dar el mismo valor y el test saldría inestable según lo
   rápida que fuera la máquina. La fixture `baneos` fuerza un mtime
   estrictamente creciente con `os.utime` en cada escritura, y hay un
   auto-test que lo comprueba.

3. **La IP.** `TestClient` codifica `("testclient", 50000)` como cliente ASGI,
   literal, en dos sitios de `starlette/testclient.py`: por ahí no se pueden
   probar ni el baneo (`ipaddress.ip_address("testclient")` no es una IP) ni
   el aislamiento entre IPs. Para eso se llama a `main.app` por el contrato
   ASGI con el `client` que interese —la misma técnica que ya usa
   `test_upload.py` para el cuerpo por trozos—, y un auto-test verifica que la
   IP que se pide es la que ve el backend.

4. **Recargar el módulo.** `importlib.reload(auth)` está descartado a
   propósito y el motivo es de seguridad, no de estilo: `_FAILURES_PATH` se
   calcula en import time desde `auth.__file__`, así que un reload lo
   devolvería a `backend/data/` —los datos REALES del usuario— con `main`
   siguiendo autenticando contra los objetos viejos y sin que nada fallara.
   El reinicio se simula de dos formas, y ninguna toca los datos reales:
   vaciando `_login_failures` y releyendo del disco (el ciclo exacto que hace
   un proceso nuevo), y **ejecutando `auth.py` otra vez desde cero** sobre una
   copia en `tmp_path` (`_reencarnar_auth`), que es un reinicio de verdad
   —vuelve a correr `_login_failures = _load_login_failures()`— pero con su
   directorio `data/` dentro del tmp del test.

## Lo que este archivo NO cubre (documentado para no redescubrirlo)

  - Una cookie de sesión inventada **no** consume intentos del rate limit:
    solo penalizan `/api/login` y el Basic. Es la conducta actual y el motivo
    es razonable (un token de 32 bytes aleatorios no se adivina por fuerza
    bruta), pero conviene saberlo antes de contar el rate limit como defensa
    del WebSocket.
  - PAM se **simula** (`sys.modules["pam"]`). Validar contra el sistema real
    es cosa del dueño del despliegue, no del CI; aquí no se prueba ninguna
    contraseña real de ninguna cuenta real.
  - El TTL deslizante y `/api/logout-all` son de otra historia (US-020).
"""
from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import shutil
import stat
import sys
import time
import types
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from conftest import PASSWORD, USERNAME

import auth
import config
import main

# ----------------------------------------------------------------------
# Constantes del contrato. DECLARADAS aquí, no importadas de `auth`: es
# contabilidad por partida doble, igual que en `test_auth_contract.py`. Si el
# test leyera los valores del módulo bajo prueba, subir el tope de fallos a
# 1000 actualizaría a la vez el hecho y su comprobación y la suite seguiría en
# verde. `test_los_parametros_del_limite_son_los_declarados` los ata.
# ----------------------------------------------------------------------
MAX_FALLOS = 5
VENTANA_SEGUNDOS = 60
TOPE_IPS = 1000
COOKIE = "muxspace_session"

# Horas de vida de la sesión. El conftest fija MUXSPACE_SESSION_TTL_HOURS=1
# (el default de producción son 168, que haría los tests de caducidad más
# aparatosos sin probar nada distinto).
TTL_HORAS = 1

# La IP que `TestClient` presenta como cliente ASGI. Está escrita a mano en
# `starlette/testclient.py` y no se puede configurar; se declara aquí para que
# los tests puedan afirmar bajo qué clave quedó registrado un fallo.
IP_TESTCLIENT = "testclient"

# IPs de los rangos reservados para documentación (RFC 5737). Ninguna es
# encaminable, así que ni por accidente se prueba nada contra una máquina real.
IP_ATACANTE = "203.0.113.7"
IP_VECINA = "203.0.113.8"
RED_BANEADA = "198.51.100.0/24"
IP_DENTRO_DEL_RANGO = "198.51.100.5"
IP_FUERA_DEL_RANGO = "198.51.101.5"

# Contraseña incorrecta de los tests de fuerza bruta. Distinta de PASSWORD por
# construcción (lo comprueba un auto-test): si alguien igualara las dos, todos
# los tests de rate limit pasarían a hacer logins correctos y morirían en
# silencio, en verde.
PASSWORD_MALA = "esta-no-es-la-contrasena"

# Nombre de sesión de tmux para el handshake del WebSocket. No existe, y no
# debe existir: el espía de `session_exists` devuelve False precisamente para
# que ningún test se enganche a una sesión real del usuario.
SESION_INEXISTENTE = "sesion-que-no-existe"


# ======================================================================
# Andamiaje
# ======================================================================
class _Reloj:
    """Sustituto de `auth.time` con el reloj bajo control del test.

    Solo lo ve `auth`, que resuelve `time.time()` como global del módulo en
    tiempo de llamada. Lo que no sea `time()` se delega en el módulo real, así
    que el día que `auth.py` use `time.monotonic()` esto seguirá funcionando
    en vez de reventar con un AttributeError críptico.
    """

    def __init__(self, ahora: float) -> None:
        self._ahora = float(ahora)

    def time(self) -> float:
        return self._ahora

    def avanzar(self, segundos: float) -> float:
        self._ahora += segundos
        return self._ahora

    def __getattr__(self, nombre: str) -> Any:  # pragma: no cover - red de seguridad
        return getattr(time, nombre)


@pytest.fixture
def reloj(monkeypatch: pytest.MonkeyPatch) -> _Reloj:
    """El reloj de `auth`, congelado y avanzable a mano.

    Arranca en la hora real y no en 0: `_reencarnar_auth` compara ventanas
    escritas por este reloj con el `time.time()` de verdad, y una marca de
    1970 haría que toda ventana pareciera vencida.
    """
    falso = _Reloj(time.time())
    monkeypatch.setattr(auth, "time", falso)
    return falso


class _Respuesta(NamedTuple):
    """Lo que devuelve una petición hecha por ASGI directo."""

    status: int
    cuerpo: dict


def _peticion_desde_ip(
    ip: str,
    ruta: str = "/api/health",
    metodo: str = "GET",
    cabeceras: dict[str, str] | None = None,
) -> _Respuesta:
    """Llama a `main.app` por ASGI con la IP de cliente que se le pida.

    Es la única forma de ejercitar el baneo por IP de punta a punta:
    `TestClient` presenta siempre `testclient`, que ni siquiera es una IP
    válida. El scope es el que construiría uvicorn; no se ejecuta el
    `lifespan`, que aquí no hace falta (el `conftest` ya redirigió a tmp todo
    lo que se escribe en disco).

    No se manda cabecera `Origin` a propósito: con una ajena, el
    `_csrf_origin_guard` respondería 403 desde otro middleware y taparía justo
    el 403 del baneo, que es lo que se viene a medir.
    """
    cabeceras_raw = [(b"host", b"testserver")]
    for k, v in (cabeceras or {}).items():
        cabeceras_raw.append((k.lower().encode(), v.encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": metodo,
        "scheme": "http",
        "path": ruta,
        "raw_path": ruta.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": cabeceras_raw,
        "client": (ip, 54321),
        "server": ("testserver", 80),
    }

    async def _correr() -> list[dict]:
        mensajes: list[dict] = []
        entregado = False

        async def receive() -> dict:
            nonlocal entregado
            if not entregado:
                entregado = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(mensaje: dict) -> None:
            mensajes.append(mensaje)

        await main.app(scope, receive, send)
        return mensajes

    mensajes = asyncio.run(_correr())
    inicio = next(m for m in mensajes if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in mensajes if m["type"] == "http.response.body"
    )
    return _Respuesta(inicio["status"], json.loads(payload) if payload else {})


def _handshake_websocket_desde_ip(
    ip: str, nombre: str, token: str | None = None
) -> list[dict]:
    """Abre el handshake de `/api/terminal/{nombre}` desde `ip`.

    Devuelve los mensajes que envió la app. El WebSocket no pasa por los
    middlewares HTTP (los de Starlette dejan pasar cualquier scope que no sea
    `http`), así que su chequeo de baneo es una comprobación aparte dentro del
    handler: la única forma de cubrirla es llegar hasta el handler con la IP
    puesta.
    """
    cabeceras_raw = [(b"host", b"testserver")]
    if token is not None:
        cabeceras_raw.append((b"cookie", f"{COOKIE}={token}".encode()))

    ruta = f"/api/terminal/{nombre}"
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": ruta,
        "raw_path": ruta.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": cabeceras_raw,
        "client": (ip, 54321),
        "server": ("testserver", 80),
        "subprotocols": [],
    }

    async def _correr() -> list[dict]:
        mensajes: list[dict] = []
        conectado = False

        async def receive() -> dict:
            nonlocal conectado
            if not conectado:
                conectado = True
                return {"type": "websocket.connect"}
            return {"type": "websocket.disconnect", "code": 1005}

        async def send(mensaje: dict) -> None:
            mensajes.append(mensaje)

        await main.app(scope, receive, send)
        return mensajes

    return asyncio.run(_correr())


def _codigo_de_cierre(mensajes: list[dict]) -> int | None:
    """El `code` del `websocket.close`, o None si nunca se cerró."""
    for mensaje in mensajes:
        if mensaje["type"] == "websocket.close":
            return mensaje.get("code")
    return None


class _ListaNegra:
    """`banned_ips.json` con el mtime bajo control del test."""

    # Época fija y un salto amplio entre escrituras: lo que la recarga en
    # caliente compara es la IGUALDAD del mtime, así que basta con que cada
    # escritura deje uno distinto, pero se usan valores crecientes para que un
    # fallo se lea como "no releyó" y no como "releyó un archivo del pasado".
    _BASE = 1_700_000_000.0
    _SALTO = 10.0

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self._escrituras = 0

    def escribir(self, entradas: list[str]) -> float:
        return self.escribir_crudo(json.dumps(entradas))

    def escribir_crudo(self, texto: str) -> float:
        """Escribe el archivo tal cual (para probar el JSON corrupto)."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(texto, encoding="utf-8")
        self._escrituras += 1
        marca = self._BASE + self._SALTO * self._escrituras
        os.utime(self.ruta, (marca, marca))
        return marca

    def borrar(self) -> None:
        self.ruta.unlink()


@pytest.fixture
def baneos() -> _ListaNegra:
    """La lista negra, apuntando a donde el `conftest` la haya redirigido."""
    return _ListaNegra(auth._BANNED_PATH)


@pytest.fixture
def espia_session_exists(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Registra si el handler del WebSocket llegó a preguntar por tmux.

    Devuelve siempre False: con True el handler haría `accept()` y lanzaría un
    `tmux attach` real contra las sesiones vivas del usuario, que tienen
    trabajo dentro. Es el mismo espía que usa `test_auth_contract.py`, y por
    el mismo motivo: `terminal_ws` cierra con 1008 por cuatro razones
    distintas y todas con `reason` vacío, así que el código de cierre por sí
    solo no dice cuál fue.
    """
    llamadas: list[str] = []

    def _falso(name: str) -> bool:
        llamadas.append(name)
        return False

    monkeypatch.setattr(main, "session_exists", _falso)
    return llamadas


@pytest.fixture
def pam_simulado(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Modo `pam` con un módulo `pam` de mentira. Devuelve sus llamadas.

    `_pam_verify` importa `pam` DENTRO de la función, así que basta con
    plantar el módulo en `sys.modules` antes de la llamada. Autentica siempre
    con True: así, si el `compare_digest` previo desapareciera, un usuario
    ajeno entraría y el test lo vería. Nunca se valida nada contra el sistema.
    """
    llamadas: list[tuple] = []

    class _FalsoPam:
        def authenticate(self, usuario: str, password: str, service: str) -> bool:
            llamadas.append((usuario, password, service))
            return True

    modulo = types.ModuleType("pam")
    modulo.pam = _FalsoPam  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pam", modulo)
    # `auth` copió AUTH_MODE con `from config import ...`, y es esa copia la
    # que lee `verify_credentials` en cada llamada.
    monkeypatch.setattr(auth, "AUTH_MODE", "pam")
    return llamadas


def _login(client, password: str = PASSWORD, username: str = USERNAME):
    """POST /api/login. Sin `Origin`: el guard de CSRF no es lo que se mide."""
    return client.post(
        "/api/login", json={"username": username, "password": password}
    )


def _basic(usuario: str, password: str) -> dict[str, str]:
    credenciales = base64.b64encode(f"{usuario}:{password}".encode()).decode()
    return {"Authorization": f"Basic {credenciales}"}


def _registro(ip: str = IP_TESTCLIENT) -> dict:
    """El registro en memoria de esa IP. Falla con un mensaje legible."""
    assert ip in auth._login_failures, (
        f"no hay registro de fallos para {ip!r}; registradas: "
        f"{sorted(auth._login_failures)}"
    )
    return auth._login_failures[ip]


def _registro_en_disco(ip: str = IP_TESTCLIENT) -> dict:
    datos = json.loads(auth._FAILURES_PATH.read_text(encoding="utf-8"))
    assert ip in datos, f"{ip!r} no está en el archivo; hay: {sorted(datos)}"
    return datos[ip]


def _agotar_intentos(client) -> None:
    """Consume los cinco intentos de la ventana con fallos reales."""
    for numero in range(1, MAX_FALLOS + 1):
        resp = _login(client, PASSWORD_MALA)
        assert resp.status_code == 401, (
            f"el intento fallido {numero} devolvió {resp.status_code} en vez "
            f"de 401: {resp.text[:200]}"
        )


def _atributos_de_cookie(cabecera: str) -> dict[str, str]:
    """`Set-Cookie` -> atributos en minúsculas (los booleanos, con valor "")."""
    partes = [p.strip() for p in cabecera.split(";")]
    atributos: dict[str, str] = {}
    for parte in partes[1:]:
        clave, sep, valor = parte.partition("=")
        atributos[clave.lower()] = valor if sep else ""
    return atributos


def _valor_de_cookie(cabecera: str) -> str:
    return cabecera.split(";")[0].partition("=")[2]


def _set_cookie(resp) -> str:
    """La única cabecera `Set-Cookie` de la respuesta."""
    cabeceras = resp.headers.get_list("set-cookie")
    assert len(cabeceras) == 1, f"se esperaba una sola Set-Cookie: {cabeceras}"
    return cabeceras[0]


def _reencarnar_auth(raiz: Path, fallos: Path | None) -> types.ModuleType:
    """Ejecuta `auth.py` OTRA VEZ desde cero, con su `data/` dentro de `raiz`.

    Es un reinicio del backend de verdad —se vuelve a correr todo el cuerpo
    del módulo, incluida la línea `_login_failures = _load_login_failures()`—
    y sin el peligro de `importlib.reload(auth)`: como el archivo se copia a
    `raiz`, el `Path(__file__).resolve().parent / "data"` que calcula el
    módulo nuevo cae dentro del tmp del test y no en los datos reales del
    usuario.

    El módulo no se registra en `sys.modules`: nadie más debe verlo, y el
    `auth` que usa `main` sigue siendo exactamente el mismo objeto.
    """
    (raiz / "data").mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(auth.__file__), raiz / "auth.py")
    if fallos is not None:
        # Con un mensaje propio: si el registro no se hubiera persistido, el
        # `shutil.copy` fallaría con un FileNotFoundError de la biblioteca
        # estándar y el informe hablaría de rutas de tmp en vez de decir que
        # la persistencia ha desaparecido.
        assert fallos.is_file(), (
            f"no hay registro de fallos que copiar en {fallos}: nada se ha "
            f"persistido, así que no hay nada que sobreviva a un reinicio"
        )
        shutil.copy(fallos, raiz / "data" / "login_failures.json")

    spec = importlib.util.spec_from_file_location("auth_reencarnado", raiz / "auth.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ======================================================================
# Auto-tests: que el andamiaje mide lo que dice medir.
# ======================================================================
def test_auto_el_reloj_falso_no_se_filtra_al_resto_del_proceso(
    reloj: _Reloj, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Las dos mitades de la trampa nº 1, comprobadas.

    Primera: sin el parche, `auth.time` ES el módulo `time` del intérprete, o
    sea que la receta obvia (`setattr(auth.time, "time", ...)`) le cambiaría
    el reloj a httpx, a anyio y a pytest. Segunda: con el sustituto puesto,
    `auth` ve un tiempo que avanza a saltos mientras `time.time()` sigue
    siendo el de verdad.
    """
    # El `reloj` de la fixture ya reemplazó `auth.time`; el módulo original se
    # recupera del propio `sys.modules` para no depender de otro import.
    assert sys.modules["time"] is time
    monkeypatch.undo()  # deshace el parche de la fixture: vuelve el módulo real
    assert auth.time is time, (
        "auth.time ha dejado de ser el módulo `time` global; revisa si la "
        "advertencia del docstring sigue vigente"
    )

    otro = _Reloj(1_000.0)
    monkeypatch.setattr(auth, "time", otro)
    antes = time.time()
    otro.avanzar(10_000)
    assert auth.time.time() == 11_000.0
    assert abs(time.time() - antes) < 5, "el reloj falso se ha filtrado a `time`"


def test_auto_la_peticion_por_asgi_entrega_la_ip_que_se_le_pide(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El backend ve como cliente exactamente la IP que pide el helper.

    Sin esto, todos los tests de baneo podrían estar preguntando por una IP
    distinta de la que creen (o por `testclient`) y aprobar por accidente: un
    200 es un 200 venga de donde venga. Se espía `main.is_ip_banned`, que es
    el nombre que el middleware resuelve como global del módulo.
    """
    vistas: list[str] = []

    def _espia(ip: str) -> bool:
        vistas.append(ip)
        return False

    monkeypatch.setattr(main, "is_ip_banned", _espia)
    assert _peticion_desde_ip(IP_ATACANTE).status == 200
    assert vistas == [IP_ATACANTE]


def test_auto_el_handshake_del_websocket_entrega_la_ip_que_se_le_pide(
    monkeypatch: pytest.MonkeyPatch, espia_session_exists: list[str]
) -> None:
    """Lo mismo para el WebSocket, que no pasa por los middlewares HTTP."""
    vistas: list[str] = []

    def _espia(ip: str) -> bool:
        vistas.append(ip)
        return False

    monkeypatch.setattr(main, "is_ip_banned", _espia)
    token = auth.create_session(USERNAME)
    _handshake_websocket_desde_ip(IP_ATACANTE, SESION_INEXISTENTE, token)
    assert vistas == [IP_ATACANTE]


def test_auto_cada_escritura_de_la_lista_negra_deja_un_mtime_distinto(
    baneos: _ListaNegra,
) -> None:
    """La trampa nº 2: sin mtimes forzados, la recarga en caliente es azar.

    Dos escrituras seguidas caben de sobra en el mismo segundo, y entonces
    `_reload_banned_locked` decide que no hay nada que releer. Con `os.utime`
    el test deja de depender de lo rápida que sea la máquina.
    """
    primera = baneos.escribir([IP_ATACANTE])
    assert baneos.ruta.stat().st_mtime == primera
    segunda = baneos.escribir([])
    assert segunda > primera
    assert baneos.ruta.stat().st_mtime == segunda


def test_auto_la_contrasena_mala_no_es_la_buena() -> None:
    """Si alguien igualara las dos, los tests de fuerza bruta harían logins
    correctos y pasarían todos sin probar nada."""
    assert PASSWORD_MALA != PASSWORD
    assert auth.verify_credentials(USERNAME, PASSWORD) is True
    assert auth.verify_credentials(USERNAME, PASSWORD_MALA) is False


def test_auto_las_rutas_de_auth_apuntan_al_tmp_del_test(tmp_path: Path) -> None:
    """Nada de lo que escriben estos tests cae en `backend/data/`.

    Lo garantiza el `conftest` y lo vigila su centinela de sesión; aquí se
    comprueba en el propio archivo porque casi todos los casos de abajo miran
    el contenido de esos dos ficheros, y hacerlo sobre los reales sería a la
    vez un test inútil y un incidente.
    """
    assert auth._FAILURES_PATH.is_relative_to(tmp_path)
    assert auth._BANNED_PATH.is_relative_to(tmp_path)


# ======================================================================
# Rate limit del login
# ======================================================================
def test_los_parametros_del_limite_son_los_declarados() -> None:
    """Ata las constantes de `auth` a las de este archivo.

    Es la otra pata de la contabilidad por partida doble: los tests de abajo
    usan las constantes locales, así que sin esto un cambio en `auth.py`
    (subir el tope a 1000, ampliar la ventana a un día) los seguiría dejando
    en verde con el límite prácticamente desactivado.
    """
    assert auth._LOGIN_MAX_FAILURES == MAX_FALLOS
    assert auth._LOGIN_WINDOW_SECONDS == VENTANA_SEGUNDOS
    assert auth._MAX_TRACKED_IPS == TOPE_IPS
    assert auth.SESSION_COOKIE == COOKIE
    assert auth.SESSION_TTL_HOURS == TTL_HORAS


def test_el_sexto_intento_fallido_devuelve_429_y_no_401(client) -> None:
    """Cinco fallos en la ventana y la puerta se cierra: 429, no 401.

    La distinción importa: 401 es "esa contraseña no es", 429 es "ya no te
    dejo probar". Con 401 el atacante sigue teniendo un oráculo; con 429 no.
    Se comprueba el `code` del cuerpo y no solo el número, porque son dos
    respuestas de significado opuesto.

    Y la parte que de verdad demuestra que la puerta está cerrada: el sexto
    intento con la contraseña **buena** también da 429 y no emite sesión. Sin
    esa afirmación, el test lo aprobaría igual un backend que se limitara a
    rechazar contraseñas malas.
    """
    _agotar_intentos(client)

    resp = _login(client, PASSWORD_MALA)
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "err.login_rate_limited"

    con_la_buena = _login(client)
    assert con_la_buena.status_code == 429
    assert con_la_buena.json()["detail"]["code"] == "err.login_rate_limited"
    assert con_la_buena.headers.get_list("set-cookie") == []
    assert auth._sessions == {}, "se abrió una sesión estando la IP limitada"

    # Los intentos rechazados por el límite NO inflan el contador: cortan
    # antes de llegar a `register_login_failure`.
    assert _registro()["count"] == MAX_FALLOS
    assert _registro()["total_failures"] == MAX_FALLOS


def test_pasados_60_segundos_la_ventana_se_resetea(client, reloj: _Reloj) -> None:
    """El límite es una ventana, no un baneo permanente.

    Se prueban los dos lados del borde con el mismo escenario: a los 59 s
    sigue cerrado, a los 61 s vuelve a abrir. Solo el segundo lado dejaría
    pasar una ventana de una hora sin enterarse.
    """
    _agotar_intentos(client)

    reloj.avanzar(VENTANA_SEGUNDOS - 1)
    assert _login(client).status_code == 429

    reloj.avanzar(2)  # 61 s desde el primer fallo: la ventana ha vencido
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json() == {"user": USERNAME}


def test_tras_vencer_la_ventana_los_fallos_empiezan_a_contar_de_cero(
    client, reloj: _Reloj
) -> None:
    """Vencida la ventana, el siguiente fallo abre una ventana nueva.

    Es la rama de `register_login_failure` que resetea `count` y
    `window_start`. Sin ella el contador seguiría en 5 y el primer fallo tras
    la espera volvería a cerrar la puerta de inmediato, que es un límite de
    "5 intentos en total", no de "5 por minuto".
    """
    _agotar_intentos(client)
    reloj.avanzar(VENTANA_SEGUNDOS + 1)

    assert _login(client, PASSWORD_MALA).status_code == 401
    assert _registro()["count"] == 1
    assert _registro()["total_failures"] == MAX_FALLOS + 1

    # Y la ventana nueva vuelve a tener cinco intentos completos.
    for _ in range(MAX_FALLOS - 1):
        assert _login(client, PASSWORD_MALA).status_code == 401
    assert _login(client, PASSWORD_MALA).status_code == 429


def test_un_login_correcto_resetea_el_contador_pero_conserva_el_historico(
    client, reloj: _Reloj
) -> None:
    """Acertar la contraseña borra la ventana, no el rastro.

    El histórico (`total_failures`, `first_seen`, `last_seen`) es lo que
    convierte el archivo en un registro de quién ha estado atacando el panel.
    Si un login correcto lo borrara, bastaría con acertar una vez —o con que
    el dueño entrara— para perder la evidencia.

    Se compara el registro ENTERO, campo a campo y con los valores exactos del
    reloj falso: así el test también fija que `window_start` no se mueve
    dentro de la ventana y que `first_seen` es el primer fallo y no el último.
    """
    t0 = reloj.time()
    for _ in range(3):
        assert _login(client, PASSWORD_MALA).status_code == 401
    reloj.avanzar(5)
    assert _login(client, PASSWORD_MALA).status_code == 401

    assert _registro() == {
        "count": 4,
        "window_start": t0,
        "total_failures": 4,
        "first_seen": t0,
        "last_seen": t0 + 5,
    }

    assert _login(client).status_code == 200

    assert _registro() == {
        "count": 0,  # la ventana se limpia...
        "window_start": t0,
        "total_failures": 4,  # ...y el histórico se queda
        "first_seen": t0,
        "last_seen": t0 + 5,
    }
    # Y el reseteo también se persiste: si solo ocurriera en memoria, un
    # reinicio devolvería al dueño una ventana ya agotada.
    assert _registro_en_disco() == _registro()


def test_el_limite_sobrevive_a_un_reinicio_del_backend(client) -> None:
    """Tirar el backend no devuelve los cinco intentos.

    Es la propiedad menos obvia del módulo y la que un refactor "para
    simplificar" (guardar los fallos solo en memoria) se lleva por delante sin
    romper nada visible.

    El reinicio se simula con el ciclo exacto de un proceso nuevo: el
    diccionario arranca vacío y se rellena con `_load_login_failures()`. El
    control del medio —con el registro vacío la puerta se abre— es
    imprescindible: sin él, el 429 final lo explicaría igualmente el estado
    que quedó en memoria y el test no diría nada sobre el disco.

    Ese control usa la contraseña BUENA a propósito. Un fallo más reescribiría
    el archivo con el contador a 1 y el "reinicio" acabaría releyendo lo que
    el propio control acaba de escribir; un acierto con el registro vacío no
    toca el disco (`clear_login_failures` de una IP desconocida es un no-op,
    lo fija su propio test).
    """
    _agotar_intentos(client)
    assert auth._FAILURES_PATH.is_file(), (
        "los fallos no llegaron al disco: el límite no sobrevive a un "
        "reinicio y este test ya no puede comprobar nada"
    )
    assert _registro_en_disco()["count"] == MAX_FALLOS
    en_disco = auth._FAILURES_PATH.read_text(encoding="utf-8")

    auth._login_failures.clear()
    assert auth.check_login_allowed(IP_TESTCLIENT) is True
    assert _login(client).status_code == 200  # control: sin memoria, la puerta abre
    assert auth._FAILURES_PATH.read_text(encoding="utf-8") == en_disco

    # Lo que hace un proceso recién arrancado: rellenar el registro del disco.
    auth._login_failures.update(auth._load_login_failures())
    assert auth.check_login_allowed(IP_TESTCLIENT) is False

    resp = _login(client)
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "err.login_rate_limited"


def test_un_auth_ejecutado_de_cero_relee_los_fallos_del_disco(
    client, tmp_path: Path
) -> None:
    """El reinicio de verdad: `auth.py` se vuelve a ejecutar entero.

    El test de arriba simula el ciclo a mano; este ejecuta el módulo desde su
    fuente, así que cubre la línea real que lo hace posible
    (`_login_failures = _load_login_failures()`, en el cuerpo del módulo).
    Borrarla dejaría el test anterior en verde.

    No se usa `importlib.reload(auth)`: recalcularía `_FAILURES_PATH` contra
    `backend/data/`, los datos reales del usuario. Ver el docstring del
    archivo.
    """
    _agotar_intentos(client)

    modulo = _reencarnar_auth(tmp_path / "reinicio", auth._FAILURES_PATH)

    assert modulo is not auth, "no se ha ejecutado un módulo nuevo"
    assert modulo._login_failures[IP_TESTCLIENT]["count"] == MAX_FALLOS
    assert modulo._login_failures[IP_TESTCLIENT]["total_failures"] == MAX_FALLOS
    assert modulo.check_login_allowed(IP_TESTCLIENT) is False
    # Control: el proceso nuevo no le niega el paso a todo el mundo, solo a
    # quien venía con los intentos agotados.
    assert modulo.check_login_allowed(IP_VECINA) is True


def test_auto_el_reinicio_simulado_mide_el_disco_y_no_la_memoria(
    client, tmp_path: Path
) -> None:
    """Con el archivo vacío, el módulo nuevo NO hereda el límite.

    Es la mutación del test anterior hecha explícita: demuestra que su
    veredicto sale del contenido del archivo. Si `_persist_login_failures`
    dejara de escribir, esto es lo que pasaría de verdad — y el test de arriba
    se pondría en rojo.
    """
    _agotar_intentos(client)
    vacio = tmp_path / "sin-fallos.json"
    vacio.write_text("{}", encoding="utf-8")

    modulo = _reencarnar_auth(tmp_path / "control", vacio)

    assert modulo._login_failures == {}
    assert modulo.check_login_allowed(IP_TESTCLIENT) is True


def test_un_basic_incorrecto_penaliza_igual_que_el_login(client) -> None:
    """El agujero clásico: Basic contra un endpoint autenticado.

    Limitar solo `/api/login` deja `Authorization: Basic` contra cualquiera de
    los 30+ endpoints protegidos como vía de fuerza bruta sin tope. Aquí se
    comprueba que comparte contador con el login, en las dos direcciones: el
    sexto Basic da 429, y la IP queda igual de limitada para `/api/login`.
    """
    for numero in range(1, MAX_FALLOS + 1):
        resp = client.get("/api/me", headers=_basic(USERNAME, PASSWORD_MALA))
        assert resp.status_code == 401, f"el Basic fallido {numero}: {resp.text[:200]}"

    assert _registro()["count"] == MAX_FALLOS
    assert _registro_en_disco()["total_failures"] == MAX_FALLOS

    resp = client.get("/api/me", headers=_basic(USERNAME, PASSWORD_MALA))
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "err.login_rate_limited"

    # Mismo contador por IP: no son dos cupos separados.
    assert _login(client).status_code == 429


def test_una_peticion_sin_credenciales_no_consume_intentos(client) -> None:
    """El control positivo del caso anterior, y una condición de uso real.

    Si una petición desnuda penalizara, cualquier pestaña abierta con la
    sesión caducada (el frontend pregunta por `/api/me` al arrancar) se
    autobloquearía el login. Se piden cuatro veces MÁS que el tope: si
    contaran, el login final daría 429.
    """
    for _ in range(MAX_FALLOS * 4):
        assert client.get("/api/me").status_code == 401

    assert auth._login_failures == {}
    assert not auth._FAILURES_PATH.exists(), (
        "una petición sin credenciales ha escrito en el registro de fallos"
    )
    assert _login(client).status_code == 200


def test_un_esquema_de_autorizacion_que_no_es_basic_tampoco_penaliza(client) -> None:
    """`Authorization: Bearer ...` no entra en el contador.

    `_basic_user` se retira antes de tocar el rate limit si el esquema no es
    Basic. Importa que siga así: un cliente mal configurado que mandara un
    Bearer en bucle no debe poder bloquearle el login al dueño.
    """
    bearer = {"Authorization": "Bearer un-token-que-no-es-de-aqui"}
    for _ in range(MAX_FALLOS * 2):
        assert client.get("/api/me", headers=bearer).status_code == 401
    assert auth._login_failures == {}
    assert _login(client).status_code == 200


def test_un_basic_ilegible_o_sin_dos_puntos_si_penaliza(client) -> None:
    """Una cabecera Basic rota cuenta como intento fallido.

    Son las dos ramas de error de `_basic_user` (base64 inválido y carga sin
    `usuario:contraseña`). Cuentan a propósito: mandar basura en el
    `Authorization` es exactamente lo que hace un escáner, y no debe salir más
    barato que probar contraseñas.
    """
    resp = client.get("/api/me", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
    assert _registro()["count"] == 1

    sin_dos_puntos = base64.b64encode(b"solo-el-usuario").decode()
    resp = client.get("/api/me", headers={"Authorization": f"Basic {sin_dos_puntos}"})
    assert resp.status_code == 401
    assert _registro()["count"] == 2


def test_un_basic_correcto_autentica_y_limpia_el_contador(client) -> None:
    """La otra mitad del contrato de Basic: sigue sirviendo para curl.

    Sin este caso, un `_basic_user` que devolviera siempre None pasaría todos
    los tests de rate limit de arriba con nota. Además cubre el
    `clear_login_failures` de esa vía: el cliente CLI que se equivoca y luego
    acierta no se queda con la ventana medio gastada.
    """
    malas = _basic(USERNAME, PASSWORD_MALA)
    for _ in range(3):
        assert client.get("/api/me", headers=malas).status_code == 401
    assert _registro()["count"] == 3

    resp = client.get("/api/me", headers=_basic(USERNAME, PASSWORD))
    assert resp.status_code == 200
    assert resp.json() == {"user": USERNAME}

    assert _registro()["count"] == 0
    assert _registro()["total_failures"] == 3


def test_el_limite_es_por_ip_y_no_global(client) -> None:
    """Una IP agotada no bloquea a las demás.

    Es el reverso del caso principal y no es cosmético: si el contador fuera
    global, cualquiera podría dejar al dueño fuera de su propio panel gastando
    cinco intentos desde otra máquina.
    """
    _agotar_intentos(client)
    assert _login(client).status_code == 429

    # La misma app, desde otra IP: pasa el rate limit y llega al endpoint.
    otra = _peticion_desde_ip(
        IP_VECINA, ruta="/api/me", cabeceras=_basic(USERNAME, PASSWORD)
    )
    assert otra.status == 200
    assert otra.cuerpo == {"user": USERNAME}
    assert IP_VECINA not in auth._login_failures


def test_al_superar_el_tope_se_descartan_las_ips_de_actividad_mas_antigua(
    monkeypatch: pytest.MonkeyPatch, reloj: _Reloj
) -> None:
    """El archivo no crece sin límite, y lo que se tira es lo más viejo.

    El tope se baja con monkeypatch: lo que se prueba aquí es el MECANISMO
    (¿poda?, ¿a quién?), no el número — del número se ocupa
    `test_los_parametros_del_limite_son_los_declarados`. Con el valor real
    harían falta 1001 escrituras del archivo completo para ver una sola poda.

    El escenario distingue "actividad más antigua" de "registrada primero",
    que es la confusión fácil: la primera IP en aparecer vuelve a fallar antes
    del desbordamiento, así que la que sobra es la segunda.
    """
    monkeypatch.setattr(auth, "_MAX_TRACKED_IPS", 3)

    for sufijo in (1, 2, 3):
        auth.register_login_failure(f"203.0.113.{sufijo}")
        reloj.avanzar(1)

    auth.register_login_failure("203.0.113.1")  # la .1 pasa a ser la más reciente
    reloj.avanzar(1)
    auth.register_login_failure("203.0.113.4")  # cuarta IP: hay que podar una

    esperadas = {"203.0.113.1", "203.0.113.3", "203.0.113.4"}
    assert set(auth._login_failures) == esperadas
    assert set(json.loads(auth._FAILURES_PATH.read_text(encoding="utf-8"))) == esperadas


def test_el_archivo_de_fallos_queda_a_0600(client) -> None:
    """Solo el dueño lo lee.

    El panel ya da una shell a su usuario; el registro de intentos —con las
    IPs que le atacan y cuándo— no tiene por qué ser legible por cualquier
    otra cuenta de la máquina. Se comprueba también que no queda el temporal
    de la escritura atómica, que se crea con el mismo modo pero al que nadie
    volvería a mirar.
    """
    assert _login(client, PASSWORD_MALA).status_code == 401

    modo = stat.S_IMODE(auth._FAILURES_PATH.stat().st_mode)
    assert oct(modo) == oct(0o600), f"el registro de fallos quedó en {oct(modo)}"

    modo_dir = stat.S_IMODE(auth._FAILURES_PATH.parent.stat().st_mode)
    assert oct(modo_dir) == oct(0o700)

    temporal = auth._FAILURES_PATH.with_name(auth._FAILURES_PATH.name + ".tmp")
    assert not temporal.exists()


def test_un_registro_de_fallos_corrupto_no_tumba_el_login(client) -> None:
    """Con el JSON a medias, `auth` arranca con el registro vacío.

    Es la decisión menos mala: preferir que el panel siga usable a que un
    archivo roto deje al dueño sin poder entrar. Queda anotado aquí porque es
    el reverso del baneo por IP, donde la política es la CONTRARIA (conservar
    la lista anterior) y esa asimetría es deliberada: un fallo aquí abre una
    ventana de cinco intentos, allí desbanearía a todos los atacantes.
    """
    auth._FAILURES_PATH.parent.mkdir(parents=True, exist_ok=True)
    auth._FAILURES_PATH.write_text('{"203.0.113.1": ', encoding="utf-8")
    assert auth._load_login_failures() == {}

    # Un JSON válido pero del tipo equivocado tampoco pasa.
    auth._FAILURES_PATH.write_text('["no", "es", "un", "dict"]', encoding="utf-8")
    assert auth._load_login_failures() == {}

    # Y las entradas que no son objetos se descartan una a una.
    auth._FAILURES_PATH.write_text(
        json.dumps({"203.0.113.1": 7, "203.0.113.2": {"count": 1}}), encoding="utf-8"
    )
    assert auth._load_login_failures() == {"203.0.113.2": {"count": 1}}


def test_sin_archivo_de_fallos_el_registro_arranca_vacio() -> None:
    """El caso normal de una instalación nueva."""
    assert not auth._FAILURES_PATH.exists()
    assert auth._load_login_failures() == {}
    assert auth.check_login_allowed(IP_ATACANTE) is True


def test_limpiar_una_ip_desconocida_no_crea_ni_escribe_nada() -> None:
    """`clear_login_failures` de quien nunca falló es un no-op.

    Sin la guarda, cada login correcto escribiría el archivo entero. Se
    comprueba por el efecto —el archivo no llega a existir— y no leyendo el
    código.
    """
    auth.clear_login_failures(IP_ATACANTE)
    assert auth._login_failures == {}
    assert not auth._FAILURES_PATH.exists()


# ======================================================================
# Sesiones
# ======================================================================
def test_el_login_correcto_emite_la_cookie_de_sesion_blindada(client) -> None:
    """`HttpOnly`, `SameSite=Lax`, `Path=/` y un `Max-Age` coherente.

    Cada atributo tapa un ataque distinto: `HttpOnly` impide que un XSS lea el
    token que abre la shell, `SameSite=Lax` corta el CSRF y el
    cross-site WebSocket hijacking. Se leen de la cabecera `Set-Cookie` cruda
    porque el cookiejar de httpx descarta los atributos al guardarla: mirar
    `client.cookies` no probaría ninguno de los dos.

    `Secure` NO aparece aquí porque el `conftest` fuerza
    `MUXSPACE_COOKIE_SECURE=false` (con `Secure`, httpx no reenviaría la
    cookie por http://testserver y toda la suite se caería). Su caso propio es
    el test siguiente.
    """
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.json() == {"user": USERNAME}

    cabecera = _set_cookie(resp)
    assert cabecera.startswith(f"{COOKIE}=")

    atributos = _atributos_de_cookie(cabecera)
    assert "httponly" in atributos
    assert atributos["samesite"].lower() == "lax"
    assert atributos["path"] == "/"
    assert atributos["max-age"] == str(TTL_HORAS * 3600)
    assert "secure" not in atributos  # ver el docstring

    # Y detrás de la cookie hay una sesión de verdad, no un valor decorativo.
    token = _valor_de_cookie(cabecera)
    assert auth._sessions[token][0] == USERNAME
    assert len(token) >= 32, "el token de sesión es sospechosamente corto"


def test_la_cookie_sale_marcada_secure_cuando_la_configuracion_lo_pide(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El flag existe y hace efecto (el default de producción es True).

    `main.login` lee `config.COOKIE_SECURE` por atributo en cada petición, así
    que el monkeypatch basta. Junto con el `assert "secure" not in atributos`
    del test anterior, esto demuestra que el atributo sigue al flag en las dos
    direcciones y no está simplemente ausente siempre.
    """
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    resp = _login(client)
    assert resp.status_code == 200
    assert "secure" in _atributos_de_cookie(_set_cookie(resp))


def test_con_la_cookie_un_endpoint_autenticado_responde_200(client_auth) -> None:
    """Lo que el navegador hace después del login, sin credenciales explícitas."""
    resp = client_auth.get("/api/me")
    assert resp.status_code == 200
    assert resp.json() == {"user": USERNAME}
    # Sin cabecera `Authorization`: la autenticación vino solo de la cookie.
    assert "authorization" not in {k.lower() for k in client_auth.headers}


def test_una_sesion_caducada_da_401_y_desaparece_del_registro(
    client, reloj: _Reloj
) -> None:
    """El TTL se aplica de verdad y la entrada se recoge al detectarla.

    Las dos mitades importan: el 401 es la puerta, y que el token desaparezca
    de `_sessions` es lo que impide que el diccionario crezca con sesiones
    muertas en un proceso que no se reinicia nunca.

    Se prueban los dos lados del borde con el mismo escenario. Sin el control
    de "un segundo antes sigue viva", un TTL de cero también pasaría.
    """
    assert _login(client).status_code == 200
    token = client.cookies[COOKIE]
    assert token in auth._sessions

    reloj.avanzar(TTL_HORAS * 3600 - 1)
    assert client.get("/api/me").status_code == 200

    reloj.avanzar(2)
    resp = client.get("/api/me")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "err.unauthenticated"
    assert token not in auth._sessions
    assert auth._sessions == {}


def test_crear_una_sesion_purga_las_que_ya_caducaron(reloj: _Reloj) -> None:
    """La recogida de basura no depende de que alguien use el token caducado.

    Es la otra vía de purga: un usuario que cierra el navegador sin hacer
    logout y vuelve al día siguiente deja su token viejo en memoria para
    siempre si nadie lo barre al crear el nuevo.
    """
    viejo = auth.create_session(USERNAME)
    reloj.avanzar(TTL_HORAS * 3600 + 1)
    nuevo = auth.create_session(USERNAME)

    assert list(auth._sessions) == [nuevo]
    assert auth.session_user(viejo) is None
    assert auth.session_user(nuevo) == USERNAME


def test_el_logout_invalida_el_token_en_el_servidor(client) -> None:
    """Cerrar sesión mata el token, no solo la cookie del navegador.

    La cookie se reenvía A MANO después del logout: si el test se limitara a
    comprobar que el cliente ya no la manda, aprobaría igual un `logout` que
    solo borrase la cookie y dejara el token vivo — o sea, un logout que no
    protege de nada a quien ya copió el valor.
    """
    assert _login(client).status_code == 200
    token = client.cookies[COOKIE]

    assert client.post("/api/logout").status_code == 200
    assert token not in auth._sessions
    assert auth._sessions == {}

    client.cookies.clear()
    resp = client.get("/api/me", headers={"Cookie": f"{COOKIE}={token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "err.unauthenticated"


def test_un_token_inventado_no_abre_nada(client) -> None:
    """Ni un token con pinta de bueno vale si no está en el registro."""
    inventado = "x" * 43  # la misma longitud que un token_urlsafe(32)
    resp = client.get("/api/me", headers={"Cookie": f"{COOKIE}={inventado}"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "err.unauthenticated"
    assert auth._sessions == {}


def test_los_casos_degenerados_del_token_no_revientan(client) -> None:
    """Sin cookie, cookie vacía y logout sin sesión: 401 o no-op, nunca un 500.

    Son las guardas de `session_user` y `destroy_session`. Un 500 aquí sería
    un DoS trivial (y, según cómo, una traza en el log con el nombre de la
    cookie).
    """
    assert auth.session_user(None) is None
    assert auth.session_user("") is None
    auth.destroy_session(None)  # no-op, sin excepción
    auth.destroy_session("no-existe")

    assert client.get("/api/me", headers={"Cookie": f"{COOKIE}="}).status_code == 401
    assert client.post("/api/logout").status_code == 200


def test_con_la_autenticacion_apagada_nadie_pide_credenciales(
    auth_disabled: None, espia_session_exists: list[str]
) -> None:
    """El despliegue por mTLS: el flag apaga las DOS puertas, no solo una.

    Todo lo demás en este archivo asume `AUTH_ENABLED=true`; esto fija el otro
    extremo. Se comprueban las dos vías porque son código distinto
    (`require_auth` y `ws_user` tienen cada una su propio `if not
    AUTH_ENABLED`): que una respetara el flag y la otra no daría un panel que
    parece abierto y tiene el terminal cerrado — o, si el olvido fuera al
    revés, un panel que parece cerrado con el terminal abierto.
    """
    resp = _peticion_desde_ip(IP_VECINA, "/api/me")
    assert resp.status == 200
    assert resp.cuerpo == {"user": "anonymous"}

    # Sin cookie ninguna: el WebSocket llega hasta la consulta de tmux.
    mensajes = _handshake_websocket_desde_ip(IP_VECINA, SESION_INEXISTENTE, token=None)
    assert _codigo_de_cierre(mensajes) == 1008  # la sesión de tmux no existe
    assert espia_session_exists == [SESION_INEXISTENTE]


def test_una_contrasena_con_acentos_no_revienta_la_comparacion() -> None:
    """`compare_digest` sobre str lanza TypeError con no-ASCII.

    Por eso `_compare` codifica a bytes antes. El fallo sería un 500 en el
    login —y un oráculo: "esta contraseña tiene caracteres raros"— en vez de
    un 401 limpio.
    """
    assert auth.verify_credentials(USERNAME, "contraseñá-con-tildes") is False
    assert auth.verify_credentials("usuarió", PASSWORD) is False


# ======================================================================
# Lista negra de IPs
# ======================================================================
def test_una_ip_en_la_lista_recibe_403_en_http(baneos: _ListaNegra) -> None:
    """La IP baneada no llega ni a `/api/health`, que es pública.

    Se elige `/api/health` a propósito: como no exige autenticación, un 403
    ahí solo lo puede haber puesto el middleware de baneo. Y el control con la
    IP vecina —un 200 en la misma petición— demuestra que el 403 lo produjo la
    lista y no que la ruta estuviera caída.
    """
    baneos.escribir([IP_ATACANTE])

    prohibida = _peticion_desde_ip(IP_ATACANTE)
    assert prohibida.status == 403
    assert prohibida.cuerpo == {"detail": "Acceso denegado."}

    permitida = _peticion_desde_ip(IP_VECINA)
    assert permitida.status == 200
    assert permitida.cuerpo == {"message": "ok"}


def test_el_baneo_manda_sobre_las_credenciales_correctas(baneos: _ListaNegra) -> None:
    """Con credenciales buenas y todo: 403 antes de mirar quién eres.

    Es lo que convierte la lista en una puerta y no en un aviso. El mismo
    Basic desde la IP vecina da 200, así que las credenciales eran válidas.
    """
    baneos.escribir([IP_ATACANTE])
    cabeceras = _basic(USERNAME, PASSWORD)

    assert _peticion_desde_ip(IP_ATACANTE, "/api/me", cabeceras=cabeceras).status == 403
    assert _peticion_desde_ip(IP_VECINA, "/api/me", cabeceras=cabeceras).status == 200


def test_una_entrada_cidr_bloquea_el_rango_y_deja_pasar_lo_de_fuera(
    baneos: _ListaNegra,
) -> None:
    """Un /24 entero, que es como se banea a un proveedor o a una botnet."""
    baneos.escribir([RED_BANEADA])

    assert _peticion_desde_ip(IP_DENTRO_DEL_RANGO).status == 403
    assert _peticion_desde_ip(IP_FUERA_DEL_RANGO).status == 200
    # La comprobación es de pertenencia a la red, no de prefijo textual: una
    # IP que empieza igual pero cae fuera del rango pasa.
    assert _peticion_desde_ip("198.51.100.255").status == 403


def test_la_lista_se_recarga_en_caliente_al_cambiar_el_archivo(
    baneos: _ListaNegra,
) -> None:
    """Banear y desbanear sin reiniciar el backend, en los dos sentidos.

    Solo el sentido "banear" dejaría pasar una implementación que cachea la
    lista para siempre en cuanto encuentra algo; solo "desbanear", una que no
    llegue a leer nunca. Cada escritura lleva un mtime forzado (ver la trampa
    nº 2 del docstring).
    """
    baneos.escribir([])
    assert _peticion_desde_ip(IP_ATACANTE).status == 200

    baneos.escribir([IP_ATACANTE])
    assert _peticion_desde_ip(IP_ATACANTE).status == 403

    baneos.escribir([])
    assert _peticion_desde_ip(IP_ATACANTE).status == 200


def test_un_json_corrupto_conserva_la_lista_anterior(baneos: _ListaNegra) -> None:
    """Guardar el archivo a medio editar no desbanea a todo el mundo.

    Es el modo de fallo que importa: el dueño abre `banned_ips.json` para
    añadir una IP, el editor guarda a mitad, y la política "ante la duda,
    lista vacía" levantaría todos los baneos en silencio.

    El control de después es imprescindible: sin él, el 403 se explicaría
    igualmente porque la recarga no llegó a mirar el archivo. Al reescribirlo
    con una lista vacía —mismo mecanismo, mtime nuevo— se ve que sí lo mira, y
    entonces el 403 anterior solo puede venir de haber conservado la lista.
    """
    baneos.escribir([IP_ATACANTE])
    assert _peticion_desde_ip(IP_ATACANTE).status == 403

    baneos.escribir_crudo('["203.0.113.7", "198.51.10')
    assert _peticion_desde_ip(IP_ATACANTE).status == 403

    baneos.escribir([])
    assert _peticion_desde_ip(IP_ATACANTE).status == 200


def test_una_entrada_malformada_no_tumba_las_demas(baneos: _ListaNegra) -> None:
    """Un typo en una línea no desactiva el resto de la lista.

    Se prueban tres formas de entrada inválida a la vez —texto que no es una
    IP, un CIDR imposible y un número— con una IP buena en medio: si el bucle
    abortara al primer error, la IP buena se colaría.
    """
    baneos.escribir(["no-es-una-ip", "198.51.100.0/99", IP_ATACANTE, 12345])

    assert _peticion_desde_ip(IP_ATACANTE).status == 403
    assert _peticion_desde_ip(IP_VECINA).status == 200


def test_un_json_que_no_es_una_lista_no_banea_a_nadie(baneos: _ListaNegra) -> None:
    """Con un objeto en vez de un array, la lista queda vacía (no explota)."""
    baneos.escribir_crudo('{"203.0.113.7": true}')
    assert _peticion_desde_ip(IP_ATACANTE).status == 200


def test_borrar_el_archivo_levanta_todos_los_baneos(baneos: _ListaNegra) -> None:
    """Sin archivo no hay lista negra, y el estado en memoria se limpia.

    Es la vía de escape del dueño si se banea a sí mismo por error. Se
    comprueba también `_banned_mtime`, que vuelve a -1: si se quedara con el
    valor del archivo borrado, un archivo nuevo con ese mismo mtime (posible:
    lo copia un `rsync -a`) no se leería.
    """
    baneos.escribir([IP_ATACANTE])
    assert _peticion_desde_ip(IP_ATACANTE).status == 403

    baneos.borrar()

    assert _peticion_desde_ip(IP_ATACANTE).status == 200
    assert auth._banned_mtime == -1.0
    assert auth._banned_networks == []


def test_un_cliente_sin_ip_valida_nunca_esta_baneado(baneos: _ListaNegra) -> None:
    """Lo que no es una IP no casa con ninguna red, y no revienta.

    Cubre el `ValueError` de `ip_address`, que es la razón por la que el resto
    de la suite (que llega como `testclient`) no se ve afectada por la lista
    negra aunque un test la deje puesta.
    """
    baneos.escribir([IP_ATACANTE, "0.0.0.0/0"])
    assert auth.is_ip_banned(IP_TESTCLIENT) is False
    assert auth.is_ip_banned("") is False
    # Control: con esa misma lista, una IP de verdad sí está baneada.
    assert auth.is_ip_banned(IP_VECINA) is True


def test_el_websocket_rechaza_a_una_ip_baneada_con_1008(
    baneos: _ListaNegra, espia_session_exists: list[str]
) -> None:
    """El terminal es la puerta que de verdad da shell: también se cierra.

    No pasa por los middlewares HTTP, así que su chequeo es una comprobación
    aparte dentro del handler y podría perderse en un refactor sin que ningún
    test HTTP se enterara.

    **El 1008 no prueba nada por sí solo**: `terminal_ws` cierra con 1008 por
    cuatro motivos y los cuatro con `reason` vacío. De ahí las otras dos
    aserciones: se entra con una sesión VÁLIDA (así el cierre no puede venir
    de `ws_user`) y se comprueba que el handler no llegó a consultar tmux, que
    es lo primero que hace después de las tres puertas. El control con la IP
    vecina cierra el argumento: mismo token, misma sesión inexistente, y ahí
    sí llega a tmux.
    """
    baneos.escribir([IP_ATACANTE])
    token = auth.create_session(USERNAME)

    baneada = _handshake_websocket_desde_ip(IP_ATACANTE, SESION_INEXISTENTE, token)
    assert _codigo_de_cierre(baneada) == 1008
    assert espia_session_exists == [], (
        "el handler consultó tmux desde una IP baneada: el cierre 1008 no lo "
        "produjo la lista negra"
    )

    permitida = _handshake_websocket_desde_ip(IP_VECINA, SESION_INEXISTENTE, token)
    assert _codigo_de_cierre(permitida) == 1008  # ahora, porque la sesión no existe
    assert espia_session_exists == [SESION_INEXISTENTE], (
        "con una IP no baneada el handler tampoco llegó a tmux: algo cierra "
        "antes y el caso baneado aprobaría solo"
    )


# ======================================================================
# Modo PAM
# ======================================================================
def test_en_modo_pam_otro_usuario_se_rechaza_sin_llegar_a_pam(
    pam_simulado: list[tuple],
) -> None:
    """El `compare_digest` previo es la defensa, no PAM.

    Sin privilegios de root, el helper de PAM solo puede verificar la
    contraseña del usuario que ejecuta el proceso; cualquier otro nombre no
    tiene nada que hacer ahí, y dejarlo pasar sería mandar credenciales
    ajenas a la pila de autenticación del sistema (con su registro en los logs
    y sus contadores de bloqueo de cuenta, que un atacante podría usar para
    dejar fuera al usuario legítimo).

    El PAM simulado autentica SIEMPRE: si la comparación previa desapareciera,
    `verify_credentials` devolvería True y este test lo diría. La lista de
    llamadas vacía es la otra mitad — ni siquiera se le preguntó.
    """
    assert auth.verify_credentials("otro-usuario", "lo-que-sea") is False
    assert pam_simulado == []


def test_en_modo_pam_el_usuario_del_backend_si_llega_a_pam(
    pam_simulado: list[tuple],
) -> None:
    """El control positivo: sin él, el test anterior lo pasaría un espía roto.

    Un `_pam_verify` que devolviera False siempre —o un módulo `pam` que
    nunca se llegara a importar— dejaría la lista de llamadas vacía igual. Lo
    que se comprueba es que, para el usuario del backend, la llamada llega
    con el usuario, la contraseña y el servicio configurado.

    La contraseña es de mentira y PAM está simulado: no se valida nada contra
    el sistema real.
    """
    usuario = auth._backend_user()
    assert auth.verify_credentials(usuario, "contrasena-simulada") is True
    assert pam_simulado == [(usuario, "contrasena-simulada", config.PAM_SERVICE)]


def test_en_modo_pam_las_credenciales_vacias_no_llegan_a_pam(
    pam_simulado: list[tuple],
) -> None:
    """Ni usuario vacío ni contraseña vacía se reenvían al sistema.

    Con algunas configuraciones de PAM una contraseña vacía es aceptable; el
    corte previo evita depender de eso.
    """
    assert auth.verify_credentials("", "") is False
    assert auth.verify_credentials(auth._backend_user(), "") is False
    assert auth.verify_credentials("", "algo") is False
    assert pam_simulado == []


def test_en_modo_pam_el_login_http_rechaza_a_otro_usuario_y_lo_apunta(
    client, pam_simulado: list[tuple]
) -> None:
    """El recorrido completo por HTTP: 401, sin PAM, y con el fallo apuntado.

    Cierra el circuito con el rate limit: en modo pam los intentos también
    cuentan, así que probar nombres de usuario del sistema contra el panel
    tiene el mismo tope de cinco por minuto.
    """
    resp = _login(client, password="lo-que-sea", username="otro-usuario")
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "err.bad_credentials"
    assert pam_simulado == []
    assert _registro()["count"] == 1
