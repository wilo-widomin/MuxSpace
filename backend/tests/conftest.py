"""Andamiaje de los tests del backend: entorno fijo y datos aislados.

`backend/data/` es la biblioteca de comandos del usuario, su historial de
subidas, sus capturas y el registro de IPs que le han atacado. Ningún test
puede escribir ahí, y el aislamiento no puede depender de que quien escriba
un test se acuerde de pedir una fixture: por eso `data_dir` es `autouse` y
por eso hay, además, un centinela de sesión que fotografía el directorio real
antes y después de todo y falla si algo cambió.

El orden de los bloques de este archivo es parte del diseño: `config.py` lee
el entorno EN IMPORT TIME (`load_dotenv` + `os.getenv`), así que las
variables tienen que estar puestas antes del primer `import config`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

# ----------------------------------------------------------------------
# Bloque 1 · Entorno. ANTES de importar nada del backend.
# ----------------------------------------------------------------------
USERNAME = "usuario-de-prueba"
# config.py se niega a arrancar con "admin" o "" (es la contraseña de ejemplo
# publicada en el README), así que la de los tests tiene que ser otra.
PASSWORD = "contrasena-de-prueba"
# El origen que usa TestClient para sus peticiones.
ORIGIN = "http://testserver"

# Una MUXSPACE_* exportada en la shell del desarrollador cambiaría la
# configuración bajo prueba sin que nada lo delate. Se limpian todas y luego
# se ponen las nuestras.
for _var in [k for k in os.environ if k.startswith("MUXSPACE_")]:
    del os.environ[_var]

# Se fijan LAS CATORCE que lee config.py, no solo las que interesan a un test
# concreto: cualquiera que se deje sin fijar la rellena el `backend/.env` del
# usuario (que es su despliegue real) y los tests pasarían a comportarse
# distinto según la máquina.
os.environ.update(
    {
        "MUXSPACE_AUTH_ENABLED": "true",
        "MUXSPACE_AUTH_MODE": "env",
        "MUXSPACE_PAM_SERVICE": "login",
        "MUXSPACE_USERNAME": USERNAME,
        "MUXSPACE_PASSWORD": PASSWORD,
        "MUXSPACE_SESSION_TTL_HOURS": "1",
        # Obligatorio false. TestClient habla http://testserver y el cookiejar
        # de httpx NO reenvía una cookie marcada `Secure` por http: con el
        # default de producción (true) el login devolvería 200, la cookie se
        # guardaría y la petición siguiente saldría 401.
        "MUXSPACE_COOKIE_SECURE": "false",
        # Se prueba el default de producción (cerrado), que es lo que hay que
        # proteger. El caso "abiertas" se cubre montando una app aparte en el
        # test: `docs_url` se resuelve al construir la FastAPI, en import time,
        # así que aquí no se puede cambiar de opinión luego.
        "MUXSPACE_DOCS_ENABLED": "false",
        "MUXSPACE_HOST": "127.0.0.1",
        "MUXSPACE_PORT": "8000",
        "MUXSPACE_TRUSTED_PROXIES": "127.0.0.1",
        "MUXSPACE_TMUX_BINARY": "tmux",
        # `main._ALLOWED_ORIGINS` y el CORSMiddleware se construyen en import
        # time a partir de esto: no se puede cambiar luego con monkeypatch.
        "MUXSPACE_CORS_ORIGINS": ORIGIN,
        # A una ruta que no existe, NO al home. Si alguien rompe la fixture que
        # apunta las raíces a tmp, el modo de fallo debe ser "no hay
        # sugerencias" y no "el test está paseando por el home del usuario".
        "MUXSPACE_DIR_SUGGESTION_ROOTS": json.dumps(["/nonexistent/muxspace-tests"]),
    }
)

# ----------------------------------------------------------------------
# Bloque 2 · sys.path. Reproduce el `uvicorn --app-dir backend`.
# ----------------------------------------------------------------------
# Se calcula desde __file__, nunca desde el cwd: pytest se puede invocar desde
# cualquier directorio y el andamiaje tiene que apuntar siempre al backend de
# ESTE árbol de trabajo.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# ----------------------------------------------------------------------
# Bloque 3 · Ya se puede importar el backend.
# ----------------------------------------------------------------------
import audit  # noqa: E402
import auth  # noqa: E402
import config  # noqa: E402
import library_store  # noqa: E402
import main  # noqa: E402
import space_store  # noqa: E402
import tmux_service  # noqa: E402
import upload_store  # noqa: E402
import worklog  # noqa: E402

# El directorio que nadie puede tocar, deducido de dónde vive el módulo que
# calcula las rutas de los stores (y no de una constante escrita a mano, que
# se desincronizaría en cuanto alguien moviera un archivo).
DATOS_REALES = (Path(config.__file__).resolve().parent / "data").resolve()

# NO se usa `importlib.reload` sobre config/auth/main para reconfigurar nada.
# Motivo: `auth.py` hace `from config import AUTH_ENABLED, ...`, o sea COPIA
# los valores al importarse, y `main.py` evaluó `_auth = Depends(require_auth)`
# en import time, capturando el objeto función. Recargar los módulos deja a la
# app sirviendo con los objetos viejos SIN lanzar ningún error: el peor tipo de
# fallo, el que se manifiesta como un test que pasa cuando no debería. Se
# parchea el atributo del módulo ya importado y punto.


def _raiz_permitida(tmp_path: Path) -> Path:
    """La única raíz de directorios que ven los tests (bajo tmp)."""
    return tmp_path / "roots" / "home"


@pytest.fixture(autouse=True)
def _tmux_server_flag_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cada test arranca sin que conste que `tmux start-server` ya corrió.

    `tmux_service._server_started` es estado **de proceso** (US-019): dura lo
    que dura el intérprete, y el intérprete de pytest dura toda la suite. Sin
    esto, el primer test que hable con tmux deja el flag puesto y todos los
    demás se saltan el `start-server` —incluidos los que lo están contando o
    los que apuntan a otro binario—. El resultado sería una suite cuyo verde
    depende del orden en que corran los tests, que es peor que una roja.
    """
    monkeypatch.setattr(tmux_service, "_server_started", False)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirige a `tmp_path` todo lo que el backend escribe en disco.

    Es `autouse` porque el aislamiento no es una opción que un test pueda
    olvidar activar: un solo test sin ella escribiría en los datos del usuario.
    """
    datos = tmp_path / "data"
    datos.mkdir(parents=True, exist_ok=True)
    raiz = _raiz_permitida(tmp_path)
    raiz.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(library_store, "_STORE_PATH", datos / "library.json")
    monkeypatch.setattr(space_store, "_STORE_PATH", datos / "spaces.json")
    monkeypatch.setattr(upload_store, "_STORE_PATH", datos / "upload_history.json")
    monkeypatch.setattr(auth, "_FAILURES_PATH", datos / "login_failures.json")
    monkeypatch.setattr(auth, "_BANNED_PATH", datos / "banned_ips.json")
    monkeypatch.setattr(main, "_PASTE_DIR", datos / "pastes")
    # El log de auditoría (US-018) escribe por su cuenta, sin pasar por los
    # stores: si no se apunta también a `tmp_path`, cada test que ejecute algo
    # deja una línea en el `data/` real. Lo cazó el centinela de esta misma
    # sesión la primera vez que se ejecutó la suite con el log ya enganchado.
    monkeypatch.setattr(audit, "_LOG_PATH", datos / "audit.log")
    # El registro de tiempo es SQLite y tampoco pasa por los stores. Sin esto,
    # cualquier test que toque el endpoint del latido metería ranuras falsas en
    # el histórico real del usuario, que es justo el dato que no se puede
    # reconstruir.
    monkeypatch.setattr(worklog, "_DB_PATH", datos / "worklog.db")
    # Crítico: el `lifespan` de la app llama a `harden_tree(_DATA_DIR)`, que es
    # un chmod recursivo. Sin este parche, abrir el TestClient como contexto
    # cambiaría los permisos de los ficheros reales del usuario.
    monkeypatch.setattr(main, "_DATA_DIR", datos)
    monkeypatch.setattr(config, "DIR_SUGGESTION_ROOTS", [str(raiz)])

    # Las sesiones viven en memoria y son globales del módulo: sin este reset,
    # una sesión abierta en un test seguiría valiendo en el siguiente.
    monkeypatch.setattr(auth, "_sessions", {})
    # `auth.py` llama a `_load_login_failures()` al importarse, cuando la ruta
    # todavía es la real: este diccionario viene POBLADO con las IPs que han
    # atacado al usuario. Sin vaciarlo, los tests arrancarían con rate limits
    # heredados y acabarían volcando ese histórico a tmp.
    monkeypatch.setattr(auth, "_login_failures", {})
    # El baneo por CIDR se recarga cuando cambia el mtime del archivo; con
    # el mtime de la ejecución anterior en memoria no releería el de tmp.
    monkeypatch.setattr(auth, "_banned_mtime", -1.0)
    monkeypatch.setattr(auth, "_banned_networks", [])

    return datos


@pytest.fixture
def allowed_root(tmp_path: Path) -> Path:
    """La raíz permitida para sugerencias, navegación y subidas.

    Es el terreno de juego de los tests de rutas (US-004): plantar aquí un
    symlink que apunte fuera es seguro precisamente porque "fuera" también
    está dentro de `tmp_path`.
    """
    raiz = _raiz_permitida(tmp_path)
    raiz.mkdir(parents=True, exist_ok=True)
    return raiz


@pytest.fixture
def auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Levanta la app como en el despliegue por mTLS: sin login."""
    # Hay que parchear LOS DOS. `auth` copió el valor con
    # `from config import AUTH_ENABLED`, y esa copia es la que consultan
    # `require_auth` y `ws_user`; `main.login`, en cambio, mira
    # `config.AUTH_ENABLED` por atributo. Parchear solo uno deja media app
    # autenticando y la otra media no.
    monkeypatch.setattr(auth, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "AUTH_ENABLED", False)


@pytest.fixture
def client(data_dir: Path):
    """Cliente HTTP contra la app, con la autenticación ACTIVADA.

    Depende de `data_dir` explícitamente aunque sea `autouse`: el `with` de
    abajo ejecuta el `lifespan`, que toca disco, y el orden de dos fixtures
    autouse/no-autouse no es algo sobre lo que convenga hacer suposiciones
    cuando el precio de equivocarse son los datos del usuario.
    """
    from fastapi.testclient import TestClient

    # `with`: sin él, TestClient no ejecuta el lifespan y la app queda a medio
    # arrancar respecto de cómo corre en producción.
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def client_no_auth(auth_disabled: None, data_dir: Path):
    """Cliente HTTP contra la app con la autenticación DESACTIVADA."""
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def client_auth(client):
    """Cliente con sesión ya iniciada (cookie HttpOnly en el cookiejar)."""
    resp = client.post(
        "/api/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return client


def _huella(raiz: Path) -> dict[str, tuple[int, int]]:
    """Ruta -> (mtime_ns, tamaño) de todo lo que cuelga de `raiz`.

    `lstat` y no `stat`: si algún día hay un symlink ahí dentro, queremos la
    huella del enlace, no la del destino (que puede estar fuera y cambiar por
    motivos ajenos).
    """
    if not raiz.exists():
        return {}
    rutas = [raiz, *raiz.rglob("*")]
    huella: dict[str, tuple[int, int]] = {}
    for p in rutas:
        try:
            st = p.lstat()
        except OSError:
            continue
        huella[str(p)] = (st.st_mtime_ns, st.st_size)
    return huella


@pytest.fixture(scope="session", autouse=True)
def _centinela_datos_reales():
    """Falla la sesión entera si `backend/data/` cambió durante los tests.

    Es la red por debajo de la red: `data_dir` evita que se escriba ahí, los
    tests de `test_aislamiento.py` comprueban que `data_dir` hace su trabajo,
    y esto comprueba el resultado final aunque ambos fallaran a la vez.
    """
    antes = _huella(DATOS_REALES)
    yield
    despues = _huella(DATOS_REALES)
    assert despues == antes, (
        f"Los tests han modificado {DATOS_REALES}, que son los datos reales "
        f"del usuario. Añadidos/cambiados: "
        f"{sorted(set(despues.items()) - set(antes.items()))}; "
        f"desaparecidos: {sorted(set(antes) - set(despues))}"
    )
