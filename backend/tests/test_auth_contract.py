"""El contrato de autenticación: ninguna ruta `/api` queda abierta por descuido.

En un panel que da shell, el control de acceso ES el perímetro: no hay una
segunda línea que limite el daño de un endpoint olvidado. Este archivo no
arregla nada — hoy la cobertura es correcta — existe para el día en que
alguien añada el endpoint número 40 y se deje el `user: str = _auth`.

Se mide en DOS capas independientes, y las dos hacen falta:

  - La **declarativa** recorre `app.routes` y mira las dependencias. Da el
    mensaje legible ("/api/x sin autenticación"), pero solo prueba que la
    dependencia está DECLARADA.
  - La **de comportamiento** recorre las rutas reales con `TestClient` sin
    credenciales y exige 401. Prueba que la dependencia además SE APLICA.

Que las dos sean independientes es el punto: una regresión que solo rompa
una de ellas sigue saliendo en rojo.

Lo que este test NO puede ver (2026-07-27, documentado para que no se
redescubra dos veces):

  - El filtro `isinstance(r, APIRoute)` es ciego a `/openapi.json`, `/docs`,
    `/redoc` y `/docs/oauth2-redirect`: son `starlette.routing.Route` (los
    monta FastAPI, no nuestro código) y no cuelgan de `/api`. Cuando se
    escribió este archivo respondían **200 sin autenticación**, publicando el
    mapa completo de la API a cualquiera que llegara al puerto. Corregido
    aparte (hallazgo S12): hoy `MUXSPACE_DOCS_ENABLED` es False por defecto y
    las tres rutas no existen. La ceguera del filtro sigue ahí, así que la
    regresión la cubre `TestDocumentacionDeLaApi` más abajo, con sus propias
    aserciones y sin depender del censo.
  - El `StaticFiles` montado en `/` es un `app.mount` CONDICIONAL a que
    exista `frontend/dist`. Nada de este archivo depende de que el build
    esté hecho: el censo filtra por `APIRoute` (un `Mount` no lo es) y el
    recorrido HTTP usa los métodos y las URLs de las propias rutas `/api`,
    que en Starlette tienen prioridad sobre el mount por estar declaradas
    antes. Los tests se comportan igual con y sin build.
"""
from __future__ import annotations

import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match
from starlette.websockets import WebSocketDisconnect

import auth
import main

# Las tres rutas `/api` que pueden vivir sin autenticación, ENUMERADAS una a
# una: nada de listas blancas por prefijo (`/api/pub/*`), que convertirían
# "abrir un endpoint" en algo que se cuela sin tocar este archivo.
#
# Se DECLARA aquí y no se importa de `main`, igual que `RUTAS` en
# `test_aislamiento.py`: es contabilidad por partida doble. Si el test leyera
# la lista del propio código bajo prueba, abrir una ruta nueva actualizaría a
# la vez el hecho y su comprobación, y la suite seguiría en verde. Duplicada,
# ampliarla es un cambio consciente y revisable en el diff.
RUTAS_PUBLICAS = frozenset({"/api/health", "/api/login", "/api/logout"})

# Rutas que NO declaran `require_auth` porque tienen una segunda puerta: el
# secreto del host (`attention_store.hook_token`), que presenta un proceso de
# la máquina sin navegador ni cookie. No son públicas —sin secreto y sin
# cookie responden 401— pero su dependencia es `main._attention_auth`, que
# solo cae en `require_auth` cuando el secreto no vale.
#
# Se enumeran una a una y con su propio test más abajo, por lo mismo que
# `RUTAS_PUBLICAS`: abrir esta puerta en una ruta nueva tiene que aparecer en
# el diff de este archivo.
RUTAS_CON_SECRETO_DEL_HOST = frozenset({"/api/attention/{name}"})

# Suelo del censo, no cifra exacta (hoy son 32 rutas protegidas). Un número
# exacto obligaría a tocar este archivo en cada endpoint nuevo y acabaría
# actualizándose a ciegas; un suelo solo salta cuando el censo se DERRUMBA,
# que es el fallo que importa.
MINIMO_RUTAS_PROTEGIDAS = 30

# Valor con el que se rellenan los parámetros de path. Da igual lo que sea:
# `solve_dependencies` ejecuta las dependencias ANTES de validar los
# parámetros propios del endpoint (verificado incluso con un path declarado
# `int` recibiendo un no-numérico: 401, no 422).
RELLENO = "relleno"

# HEAD y OPTIONS los añade el framework (HEAD lo agrega `APIRoute` a toda
# ruta GET; OPTIONS lo responde el CORSMiddleware antes de llegar al
# endpoint). Probarlos no diría nada sobre nuestras dependencias.
METODOS_NO_PROBADOS = frozenset({"HEAD", "OPTIONS"})


# ----------------------------------------------------------------------
# Helpers. Son funciones y no asserts en línea a propósito: los tests 10 y
# 11 se auto-testean llamando a ESTOS MISMOS helpers sobre una app de
# laboratorio con un agujero conocido. Un helper que se comprueba a sí mismo
# no puede degradarse en silencio a "función que nunca encuentra nada".
# ----------------------------------------------------------------------
def _dependencias(dependant) -> set:
    """Todos los invocables del árbol de dependencias, en profundidad.

    Recursivo y no solo `dependant.dependencies`: el día que aparezca un
    `require_admin` que a su vez dependa de `require_auth`, la protección
    seguirá estando y un recorrido de un solo nivel la daría por ausente.
    """
    encontradas: set = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            encontradas.add(sub.call)
        encontradas |= _dependencias(sub)
    return encontradas


def _protege(route: APIRoute) -> bool:
    """True si la ruta declara `require_auth` entre sus dependencias.

    Compara por IDENTIDAD (`is auth.require_auth`) y no por
    `d.call.__name__ == "require_auth"`. Es estrictamente más fuerte: un
    homónimo importado de otro módulo (o una función local llamada igual que
    no autentique nada) pasaría la comparación por nombre y no la de
    identidad. El `__name__` se usa solo para redactar el fallo.
    """
    return any(d is auth.require_auth for d in _dependencias(route.dependant))


def rutas_api(app) -> list[APIRoute]:
    """El censo: toda `APIRoute` cuyo path empiece por `/api`.

    `startswith("/api")` SIN barra final es deliberado: así una hipotética
    `/apiv2/...` queda INCLUIDA en el contrato. Es el lado seguro del error
    — de los dos fallos posibles, exigir autenticación de más solo produce
    un test que hay que actualizar; exigirla de menos produce un endpoint
    abierto que nadie ve.

    Filtra `APIRoute`, así que deja fuera el `Mount` del frontend estático y
    el `APIWebSocketRoute` del terminal (que tiene sus propios tests, 8 y 9,
    porque su autenticación no pasa por el sistema de dependencias).
    """
    return [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path.startswith("/api")
    ]


def rutas_api_sin_auth(app, publicas) -> list[str]:
    """Paths `/api` que NO declaran `require_auth`, descontando `publicas`.

    Con `publicas=frozenset()` devuelve el censo crudo de rutas abiertas,
    que es lo que el test 2 compara contra la lista declarada.
    """
    return [
        r.path
        for r in rutas_api(app)
        if r.path not in publicas and not _protege(r)
    ]


def _url(path: str) -> str:
    """`/api/pastes/{filename}` -> `/api/pastes/relleno`."""
    return re.sub(r"\{[^}]+\}", RELLENO, path)


def _metodos(route: APIRoute) -> list[str]:
    """Los métodos que este archivo prueba de una ruta, ordenados."""
    return sorted(set(route.methods) - METODOS_NO_PROBADOS)


def _ruta_que_resuelve(app, metodo: str, url: str):
    """La ruta a la que Starlette entregaría `metodo url`, o None.

    Replica el algoritmo de `starlette.routing.Router.app`: recorre las
    rutas en orden, entrega a la primera con `Match.FULL` y, si ninguna da
    FULL, a la primera que dio `Match.PARTIAL` (el caso "path correcto,
    método equivocado", que acaba en 405).

    Existe para el test 5: sin él, el recorrido HTTP podría estar
    interrogando una ruta distinta de la que cree y aprobar por accidente.
    """
    scope = {
        "type": "http",
        "method": metodo,
        "path": url,
        "root_path": "",
        "headers": [],
        "query_string": b"",
    }
    parcial = None
    for r in app.routes:
        match, _ = r.matches(scope)
        if match == Match.FULL:
            return r
        if match == Match.PARTIAL and parcial is None:
            parcial = r
    return parcial


def _exige_401_sin_credenciales(client: TestClient, metodo: str, url: str) -> None:
    """Pide `metodo url` desnudo y exige 401. El corazón del test 4.

    Lo que NO se manda, y por qué (todo medido, no supuesto):

      - **Sin cuerpo.** Un JSON malformado da 422 (`json_invalid`) ANTES de
        resolver las dependencias, porque el cuerpo se decodifica en
        `get_request_handler`. Sin cuerpo no hay decodificación que fallar.
        Con un cuerpo válido el resultado es igualmente 401, así que
        mandarlo no aporta nada y sí puede tapar el 401.
      - **Sin `Origin`.** Un `Origin` ajeno en un POST da 403 por
        `_csrf_origin_guard`, que corre en un middleware y no llega nunca a
        las dependencias: taparía exactamente lo que venimos a medir.
      - **Sin `Authorization`.** Un Basic incorrecto da 401 cinco veces y
        429 a la sexta (rate limit de `_basic_user`), además de escribir en
        `login_failures.json`. El 401 que buscamos es el de "no hay
        credenciales", no el de "credenciales malas".

    `follow_redirects=False` porque un 307 de `redirect_slashes` seguido en
    silencio podría acabar respondiendo desde otra ruta.
    """
    # El cookiejar es del cliente, no de la petición: una cookie dejada por
    # otro test (o por otro caso de este mismo parametrize) autenticaría esta
    # llamada sin que se note.
    client.cookies.clear()
    resp = client.request(metodo, url, follow_redirects=False)
    # Igualdad ESTRICTA con 401, ni `in (401, 403)` ni `!= 200`. Un 403 es el
    # guard de Origin o el baneo por IP; un 422, la validación de FastAPI; un
    # 429, el rate limit; un 404, una ruta que no existe. Los cuatro son
    # "denegado" y ninguno demuestra que haya autenticación: aceptarlos
    # dejaría pasar un endpoint abierto que casualmente responde 422 a una
    # petición vacía.
    assert resp.status_code == 401, (
        f"{metodo} {url} respondió {resp.status_code} sin credenciales, "
        f"se esperaba 401: {resp.text[:200]}"
    )


# ----------------------------------------------------------------------
# El censo, calculado una vez en tiempo de colección.
# ----------------------------------------------------------------------
# Las del secreto del host quedan fuera de la capa DECLARATIVA (no declaran
# `require_auth`) pero siguen en la de COMPORTAMIENTO: sin credenciales tienen
# que responder 401 como cualquier otra.
# La excusa es por RUTA, no por path: `/api/attention/{name}` es POST (marca,
# con secreto) y DELETE (apaga, solo sesión del panel), y el segundo sigue
# obligado a declarar `require_auth` como cualquier otro.
_CON_SECRETO = [
    r
    for r in rutas_api(main.app)
    if r.path in RUTAS_CON_SECRETO_DEL_HOST and not _protege(r)
]

_PROTEGIDAS = [
    r
    for r in rutas_api(main.app)
    if r.path not in RUTAS_PUBLICAS and r not in _CON_SECRETO
]

# El método entra en el id porque un mismo path aparece varias veces con
# métodos distintos (`/api/pastes/{filename}` es GET y DELETE, y son dos
# `APIRoute` diferentes): sin él, los ids se repetirían y pytest los
# desambiguaría con sufijos numéricos ilegibles.
_IDS_RUTAS = [f"{'+'.join(_metodos(r))} {r.path}" for r in _PROTEGIDAS]

# Pares (ruta, método) para los tests que hacen el recorrido real.
_CASOS = [(r, m) for r in _PROTEGIDAS + _CON_SECRETO for m in _metodos(r)]
_IDS_CASOS = [f"{m} {r.path}" for r, m in _CASOS]


# ----------------------------------------------------------------------
# Capa 1 · Declarativa: lo que dicen las rutas.
# ----------------------------------------------------------------------
@pytest.mark.parametrize("r", _PROTEGIDAS, ids=_IDS_RUTAS)
def test_toda_ruta_api_declara_require_auth(r: APIRoute) -> None:
    """Toda ruta `/api` no pública declara `require_auth`.

    Un test por ruta y no un bucle con un assert al final: así el informe de
    pytest nombra la ruta culpable en el título del caso, y no hay que leer
    un mensaje de fallo para saber cuál se rompió.
    """
    assert _protege(r), (
        f"{r.path} sin autenticación. Dependencias declaradas: "
        f"{sorted(getattr(d, '__name__', repr(d)) for d in _dependencias(r.dependant))}"
    )


def test_las_rutas_publicas_son_exactamente_las_declaradas() -> None:
    """Igualdad de conjuntos, en las DOS direcciones.

    Una sola dirección no basta: comprobar solo que las abiertas están en la
    lista deja pasar entradas obsoletas (una ruta que se protegió pero sigue
    figurando como pública seguiría autorizando a la siguiente que se llame
    igual); comprobar solo que las de la lista están abiertas deja pasar una
    ruta nueva sin autenticar.
    """
    abiertas = set(rutas_api_sin_auth(main.app, RUTAS_CON_SECRETO_DEL_HOST))
    assert abiertas == set(RUTAS_PUBLICAS), (
        f"Rutas abiertas no declaradas: {sorted(abiertas - RUTAS_PUBLICAS)}; "
        f"entradas obsoletas en RUTAS_PUBLICAS: "
        f"{sorted(RUTAS_PUBLICAS - abiertas)}"
    )


@pytest.mark.parametrize(
    "r", _CON_SECRETO, ids=[r.path for r in _CON_SECRETO]
)
def test_la_puerta_del_secreto_del_host_acaba_en_require_auth(r: APIRoute) -> None:
    """Las rutas del secreto no se saltan la autenticación: la aplazan.

    Es lo que impide que `RUTAS_CON_SECRETO_DEL_HOST` sirva de coladero: una
    ruta metida ahí con una dependencia cualquiera —o sin ninguna— haría que
    la igualdad de conjuntos del test anterior dejara de verla, y este test
    es el que exige que la dependencia declarada sea la que sabe volver a
    `require_auth`.
    """
    declaradas = _dependencias(r.dependant)
    assert main._attention_auth in declaradas, (
        f"{r.path} está declarada con secreto del host pero su dependencia "
        f"no es `_attention_auth`: "
        f"{sorted(getattr(d, '__name__', repr(d)) for d in declaradas)}"
    )


def test_el_secreto_del_host_abre_solo_lo_suyo(client: TestClient) -> None:
    """Con el secreto se marca; sin él, 401. Es toda la potestad que da."""
    import attention_store

    cabecera = {main._HOOK_TOKEN_HEADER: attention_store.hook_token()}
    assert client.post("/api/attention/x", headers=cabecera).status_code == 200
    assert client.post("/api/attention/x").status_code == 401
    # El secreto no vale para nada más que marcar.
    assert client.get("/api/sessions", headers=cabecera).status_code == 401


def test_el_censo_de_rutas_no_esta_vacio() -> None:
    """El censo tiene rutas. Sin esto, todo lo demás es decorativo.

    Deliberadamente NO parametrizado: un `parametrize` sobre una lista vacía
    no falla, se salta en silencio (y en pytest 9 el aviso de colección
    vacía tampoco rompe la suite). Si `rutas_api` dejara de encontrar nada
    —un cambio de prefijo, una clase de ruta distinta— los cuatro tests
    parametrizados de este archivo pasarían a "0 casos" y la suite seguiría
    en verde. Un test plano siempre corre.
    """
    assert len(_PROTEGIDAS) >= MINIMO_RUTAS_PROTEGIDAS, (
        f"El censo de rutas protegidas cayó a {len(_PROTEGIDAS)} "
        f"(mínimo {MINIMO_RUTAS_PROTEGIDAS}): "
        f"probablemente `rutas_api` ha dejado de ver las rutas reales"
    )


# ----------------------------------------------------------------------
# Capa 2 · Comportamiento: lo que hacen las rutas.
# ----------------------------------------------------------------------
@pytest.mark.parametrize(("r", "metodo"), _CASOS, ids=_IDS_CASOS)
def test_toda_ruta_api_responde_401_sin_credenciales(
    client: TestClient, r: APIRoute, metodo: str
) -> None:
    """El recorrido real: cada ruta `/api` protegida, sin cookie, da 401.

    Cubre el caso que la capa declarativa no puede ver: que `require_auth`
    esté declarado pero no llegue a aplicarse (un `dependency_overrides`
    olvidado, un middleware que responda antes, una `AUTH_ENABLED` que se
    quede en False).

    En `/api/pastes/{filename}` el relleno no es un nombre de archivo válido
    para `_PASTE_NAME_RE` a propósito: ese regex vive DENTRO del handler, o
    sea DESPUÉS de la autenticación, y sin credenciales no debería llegar a
    ejecutarse nunca. Usar un relleno "válido" ahí sería PEOR: escondería
    justo la regresión en la que el chequeo del nombre se adelantara a la
    autenticación y empezara a devolver 404 a los anónimos.
    """
    _exige_401_sin_credenciales(client, metodo, _url(r.path))


@pytest.mark.parametrize(("r", "metodo"), _CASOS, ids=_IDS_CASOS)
def test_el_relleno_no_desvia_la_ruta(r: APIRoute, metodo: str) -> None:
    """La URL con relleno resuelve a la ruta que creemos estar probando.

    Sin esto, el test de arriba podría estar interrogando otra ruta (o el
    `Mount` del frontend) y aprobar por accidente: un 401 es un 401 venga de
    donde venga. Aquí se ata cada 401 a su endpoint.
    """
    resuelta = _ruta_que_resuelve(main.app, metodo, _url(r.path))
    assert resuelta is r, (
        f"{metodo} {_url(r.path)} no resuelve a {r.path} sino a "
        f"{getattr(resuelta, 'path', resuelta)!r}"
    )


def test_health_responde_200_sin_credenciales(client: TestClient) -> None:
    """El healthcheck del despliegue tiene que seguir funcionando.

    Es la otra mitad del contrato: si alguien "asegura" `/api/health`, el
    healthcheck empieza a fallar en producción y este test lo dice antes.
    """
    client.cookies.clear()
    resp = client.get("/api/health", follow_redirects=False)
    assert resp.status_code == 200, resp.text


def test_logout_responde_sin_credenciales(client: TestClient) -> None:
    """`/api/logout` es público de verdad, no solo en la lista.

    `RUTAS_PUBLICAS` es una declaración; sin este test (y el de health)
    podría contener rutas que en realidad exigen sesión, y nadie lo notaría
    porque el contrato se limita a excluirlas. Cerrar sesión sin tener
    sesión tiene que ser un no-op, no un 401: si no, un usuario con la
    cookie caducada no puede ni salir.
    """
    client.cookies.clear()
    resp = client.post("/api/logout", follow_redirects=False)
    assert resp.status_code == 200, resp.text


# ----------------------------------------------------------------------
# El WebSocket del terminal. Su autenticación NO pasa por el sistema de
# dependencias (`ws_user` se llama a mano dentro del handler), así que
# ninguna de las dos capas de arriba lo ve.
# ----------------------------------------------------------------------
@pytest.fixture
def espia_session_exists(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Registra si el handler llegó a preguntar por la sesión de tmux.

    Devuelve siempre False a propósito: con True el handler haría `accept()`
    y lanzaría un `tmux attach` real contra las sesiones vivas del usuario,
    que tienen trabajo dentro.

    Parchear el atributo de `main` funciona porque `main.py` hace
    `from tmux_service import ... session_exists` y `terminal_ws` lo resuelve
    como global del módulo en tiempo de llamada, no en tiempo de import.
    """
    llamadas: list[str] = []

    def _falso(name: str) -> bool:
        llamadas.append(name)
        return False

    monkeypatch.setattr(main, "session_exists", _falso)
    return llamadas


def test_el_websocket_se_cierra_1008_sin_cookie(
    client: TestClient, espia_session_exists: list[str]
) -> None:
    """Sin cookie, el WebSocket cierra 1008 ANTES de mirar tmux.

    **El 1008 no prueba nada por sí solo.** `terminal_ws` cierra con 1008
    por cuatro motivos distintos —IP baneada, Origin no permitido, sin
    autenticación, y la sesión de tmux no existe— y `reason` viene vacío en
    los cuatro. Medido: sin cookie da 1008, y CON cookie válida también
    (porque `session_exists("relleno")` es False). Un test que solo mirase
    el código de cierre seguiría en verde con el `if ws_user(...) is None`
    borrado del handler.

    De ahí el espía: `session_exists` es la primera cosa que el handler hace
    DESPUÉS de autenticar. Que no se haya llamado demuestra que el cierre
    vino de una puerta anterior; el test 9 demuestra que esa puerta no es ni
    el baneo de IP ni el guard de Origin.
    """
    # `websocket_connect()` no lanza: devuelve un `WebSocketTestSession`.
    # Quien lanza es su `__enter__`, así que el `with` interior es
    # OBLIGATORIO. Y el `pytest.fail` de dentro es deliberado: si algún día
    # se aceptara el handshake sin cookie, el informe dirá qué pasó en vez
    # del críptico "DID NOT RAISE".
    client.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/terminal/{RELLENO}"):
            pytest.fail("el WebSocket aceptó la conexión sin cookie de sesión")
    assert exc.value.code == 1008
    assert espia_session_exists == [], (
        "el handler llegó a consultar tmux sin cookie de sesión: el cierre "
        "1008 no lo produjo la autenticación"
    )


def test_el_websocket_con_sesion_pasa_el_control_de_acceso(
    client_auth: TestClient, espia_session_exists: list[str]
) -> None:
    """El control positivo, sin el cual el test 8 no significa nada.

    Con cookie válida el handler SÍ llega a `session_exists`. Eso demuestra
    que, con la configuración de estos tests, ni el baneo por IP ni el guard
    de Origin cierran la conexión — luego en el test 8, donde lo único que
    cambia es la ausencia de cookie, el único responsable posible del cierre
    es `ws_user`.

    Cierra igualmente con 1008 porque el espía devuelve False: es la rama
    "la sesión de tmux no existe", y es exactamente la que hace falta para
    no tocar las sesiones reales del usuario.
    """
    with pytest.raises(WebSocketDisconnect) as exc:
        with client_auth.websocket_connect(f"/api/terminal/{RELLENO}"):
            pytest.fail("el WebSocket no debería aceptar: la sesión no existe")
    assert exc.value.code == 1008
    assert espia_session_exists == [RELLENO], (
        "con cookie válida el handler no llegó a consultar tmux: algo cierra "
        "la conexión antes de la autenticación y el test 8 aprobaría solo"
    )


# ----------------------------------------------------------------------
# Auto-tests: ¿este archivo muerde? Una app de laboratorio con un agujero
# conocido, medida con los mismos helpers que se usan contra la app real.
# ----------------------------------------------------------------------
def _app_de_laboratorio() -> FastAPI:
    """Una app con exactamente un endpoint protegido y uno abierto.

    Usa `auth.require_auth`, el objeto real, para que el helper tenga que
    reconocerlo por identidad igual que en la app de producción.
    """
    lab = FastAPI()

    @lab.get("/api/protegida")
    def _protegida(user: str = Depends(auth.require_auth)) -> dict:
        return {"user": user}

    @lab.get("/api/abierta")
    def _abierta() -> dict:
        return {"ok": True}

    return lab


def test_el_contrato_detecta_una_ruta_sin_proteger() -> None:
    """La capa declarativa encuentra el agujero, y solo el agujero.

    Las dos mitades importan: que señale `/api/abierta` prueba que el
    detector detecta; que NO señale `/api/protegida` prueba que no está
    señalándolo todo (un helper roto que devolviera siempre la lista entera
    también "encontraría" el agujero).
    """
    lab = _app_de_laboratorio()
    assert rutas_api_sin_auth(lab, RUTAS_PUBLICAS) == ["/api/abierta"]


def test_el_recorrido_http_detecta_una_ruta_sin_proteger() -> None:
    """La capa de comportamiento también muerde, con el helper de verdad.

    Se llama a `_exige_401_sin_credenciales`, el mismo que usa el test 4, y
    se comprueba que revienta con la ruta abierta y aprueba con la
    protegida. Sin esto, un helper que se tragara cualquier respuesta (un
    `assert` mal escrito, un `resp.status_code` que dejara de existir)
    dejaría los 32 casos del test 4 en verde permanente.
    """
    lab = _app_de_laboratorio()
    with TestClient(lab) as c:
        with pytest.raises(AssertionError, match="respondió 200"):
            _exige_401_sin_credenciales(c, "GET", "/api/abierta")
        _exige_401_sin_credenciales(c, "GET", "/api/protegida")


# Rutas que NO son API: entregan la misma cáscara HTML que `/`, que ya se
# sirve sin autenticar (StaticFiles). Añadir algo aquí es una decisión
# deliberada y solo vale para páginas del cliente sin datos dentro; en cuanto
# una devuelva algo del usuario, deja de pertenecer a esta lista.
_PAGINAS_SIN_API = {"/dashboard"}


def test_no_hay_endpoints_api_fuera_del_prefijo() -> None:
    """Toda `APIRoute` de la app cuelga de `/api`, salvo páginas declaradas.

    Cierra el bypass obvio de todo lo anterior: declarar `@app.get("/estado")`
    en vez de `@app.get("/api/estado")`. El censo filtra por prefijo, así que
    una ruta fuera de `/api` sería invisible para el contrato entero y
    quedaría abierta sin que nada saltara.
    """
    fuera = [
        r.path
        for r in main.app.routes
        if isinstance(r, APIRoute)
        and not r.path.startswith("/api")
        and r.path not in _PAGINAS_SIN_API
    ]
    assert fuera == [], (
        f"Endpoints fuera del prefijo /api, invisibles para el contrato de "
        f"autenticación: {fuera}"
    )


def test_las_paginas_sin_api_solo_devuelven_la_cascara() -> None:
    """Lo que se excluye del contrato no puede llevar datos dentro.

    La exclusión anterior es una puerta: si alguien mete ahí una ruta que
    responde JSON del usuario, se habría saltado la autenticación entera con
    una línea. Aquí se comprueba que lo que sirven es HTML, el mismo que ya
    entrega `/` sin credenciales.
    """
    with TestClient(main.app) as c:
        for ruta in _PAGINAS_SIN_API:
            resp = c.get(ruta)
            assert resp.status_code in (200, 404), ruta
            if resp.status_code == 200:
                assert resp.headers["content-type"].startswith("text/html"), (
                    f"{ruta} no devuelve HTML: si sirve datos, tiene que exigir "
                    "autenticación como el resto"
                )


# ----------------------------------------------------------------------
# S12 · La documentación de la API no se publica sin autenticación
# ----------------------------------------------------------------------
# Estas rutas las monta FastAPI por su cuenta y son `starlette.routing.Route`,
# no `APIRoute`: el censo de arriba es ciego a ellas POR CONSTRUCCIÓN, así que
# la regresión hay que cubrirla con aserciones propias. Es el mismo criterio de
# contabilidad por partida doble que `RUTAS_PUBLICAS`.
RUTAS_DE_DOCUMENTACION = ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"]


class TestDocumentacionDeLaApi:
    """`/docs`, `/redoc` y `/openapi.json` cerradas salvo que se pidan.

    Publicaban el esquema completo —`send-command`, `launch`, `run` y las
    rutas de subida, con sus parámetros— a cualquiera que alcanzara el puerto.
    En un panel que ejecuta comandos como el usuario que corre el backend eso
    es reconocimiento gratis, y no lo tapaba ni el `require_auth` (no pasan por
    él) ni el contrato de rutas (no las ve).
    """

    @pytest.mark.parametrize("ruta", RUTAS_DE_DOCUMENTACION)
    def test_no_se_publica_con_la_configuracion_por_defecto(
        self, client, ruta: str
    ) -> None:
        """404 con el default de producción, y sin credenciales.

        404 y no 401 a propósito: la ruta no existe, que es más fuerte que
        existir y pedir permiso. Nada que autenticar es nada que saltarse.
        """
        client.cookies.clear()
        resp = client.get(ruta, follow_redirects=False)
        assert resp.status_code == 404, (
            f"{ruta} respondió {resp.status_code} sin credenciales: la "
            f"documentación de la API vuelve a estar publicada"
        )

    @pytest.mark.parametrize("ruta", RUTAS_DE_DOCUMENTACION)
    def test_tampoco_se_publica_con_una_sesion_iniciada(
        self, client_auth, ruta: str
    ) -> None:
        """Ni con sesión: con el flag apagado las rutas no existen para nadie.

        Separado del anterior porque son dos afirmaciones distintas: una es
        "no se filtra a un extraño" y la otra "el flag apaga de verdad, no
        solo esconde".
        """
        assert client_auth.get(ruta, follow_redirects=False).status_code == 404

    def test_el_censo_de_rutas_api_no_las_incluye(self) -> None:
        """La razón por la que estos tests existen aparte.

        Si algún día el censo llegara a verlas, este test se pondría en rojo y
        sería la señal de que la cobertura de arriba ya las cubre y esta clase
        sobra. Mientras siga en verde, la ceguera es real y hay que taparla a
        mano.
        """
        censadas = {r.path for r in rutas_api(main.app)}
        assert censadas.isdisjoint(RUTAS_DE_DOCUMENTACION)

    def test_el_flag_las_publica_cuando_se_pide(self, monkeypatch) -> None:
        """El control positivo: sin él, un `FastAPI()` roto pasaría igual.

        Los tres tests de arriba también los cumpliría una app que no montara
        nunca la documentación (o que no arrancara). Este demuestra que el 404
        lo produce la configuración y no una avería, así que el default cerrado
        significa algo.

        Se construye una app aparte porque `docs_url` se resuelve al CONSTRUIR
        la FastAPI: sobre `main.app`, ya creada, no hay monkeypatch que valga.
        """
        from fastapi import FastAPI

        abierta = FastAPI(docs_url="/docs", openapi_url="/openapi.json")
        with TestClient(abierta) as c:
            assert c.get("/openapi.json").status_code == 200
            assert c.get("/docs").status_code == 200
