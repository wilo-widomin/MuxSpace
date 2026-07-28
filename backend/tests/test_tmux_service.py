"""`tmux_service` contra un tmux de verdad, en un servidor que no es el tuyo.

## Por qué no hay mocks aquí

`tmux_service` es la frontera con el sistema: casi todo su cuerpo son
`subprocess.run` y decisiones tomadas a partir del `returncode` y del texto
que tmux escupe por stderr ("duplicate session", "can't find session", "no
server running"). Un mock de `subprocess` probaría que sé escribir el mock,
no que esas cadenas siguen siendo las que tmux emite. Así que se habla con
tmux de verdad.

## El problema, y cómo se resuelve

Hablar con tmux de verdad significa, por defecto, hablar con **el servidor de
tmux del usuario**, donde tiene su trabajo abierto. Un test que se equivoque
de nombre en un `kill-session` —o cualquier `kill-server`— le cierra sesiones
reales. Un prefijo en los nombres de sesión reduce el riesgo pero no lo
elimina: sigue siendo el mismo servidor, y un fallo de la variable que
contiene el prefijo vuelve a apuntar al trabajo del usuario.

La solución no es tener cuidado, es **no compartir servidor**. tmux selecciona
el servidor por el socket (`-L <nombre>`), y dos sockets distintos son dos
procesos `tmux` distintos que no comparten absolutamente nada: ni sesiones, ni
opciones, ni la posibilidad de que un `kill-server` en uno afecte al otro.

`tmux_service` no acepta un socket, pero sí invoca `TMUX_BINARY`. Así que los
tests escriben un **wrapper ejecutable** en `tmp_path`:

    #!/bin/sh
    unset TMUX
    TMUX_TMPDIR=<tmp_path>
    export TMUX_TMPDIR
    exec /usr/bin/tmux -L muxspace-tests-<único> "$@"

y apuntan ahí `tmux_service.TMUX_BINARY`. Detalles del wrapper:

- `unset TMUX`: la suite se puede estar ejecutando **dentro** de una sesión de
  tmux del usuario, y esa variable apunta a su socket. `-L` ya gana, pero
  dejarla puesta es dejar un puntero al servidor equivocado en el entorno del
  proceso que menos debería tenerlo.
- `TMUX_TMPDIR` bajo `tmp_path`: sin ella el socket del servidor de pruebas se
  crearía en `/tmp/tmux-<uid>/`, junto al del usuario, y quedaría ahí muerto
  después de cada ejecución. Bajo `tmp_path` lo borra pytest.

## Por qué se parchea `tmux_service.TMUX_BINARY` y no `config.TMUX_BINARY`

`tmux_service.py` hace `from config import TMUX_BINARY`: **copia** el valor al
importarse. Parchear `config.TMUX_BINARY` no cambiaría nada de lo que ejecuta
el módulo bajo prueba, y el aislamiento fallaría en silencio —los tests
pasarían, contra el servidor del usuario—. Se parchean los dos (el de `config`
por coherencia con quien lo lea por atributo), pero el que manda es el del
módulo. Es la misma trampa que documenta el `conftest.py` para `AUTH_ENABLED`.

## Las tres redes de seguridad

1. `_binario_prohibido` es **autouse**: por defecto TODOS los tests de este
   archivo tienen `TMUX_BINARY` apuntando a un script que se niega a
   ejecutarse. Un test que hable con tmux sin pedir `tmux_aislado` no acaba en
   el servidor del usuario: acaba en rojo.
2. `tmux_aislado` verifica el aislamiento **antes de cada test**: crea una
   sesión canario por el camino real (`tmux_service.create_session`) y aborta
   si el servidor del usuario llega a verla.
3. `_centinela_sesiones_del_usuario` fotografía las sesiones reales (nombre y
   fecha de creación) antes y después de todo el módulo y falla si cambió
   alguna. Es el veredicto final aunque las otras dos fallaran a la vez.

## Qué se prueba y qué no

- El ciclo de vida completo contra el servidor de pruebas, y `_quote_path`
  directa (es privada, pero es donde está el riesgo).
- La propiedad de fondo: tmux se invoca **siempre por argv**, nunca por shell,
  así que un nombre de sesión con `$(...)` es un nombre raro y no una
  ejecución de comandos. Hay un test que lo comprueba con un fichero centinela.
- No se prueban `pty_bridge` ni los endpoints HTTP de sesiones (US-021, US-025).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

import config
import main
import tmux_service
from tmux_service import TmuxError

# ----------------------------------------------------------------------
# Andamiaje: hablar con el servidor del USUARIO (solo para verificarlo)
# ----------------------------------------------------------------------

# El tmux del sistema, resuelto por PATH. El wrapper vive en `tmp_path` y no
# está en el PATH, así que esto nunca lo devuelve a él: es siempre el binario
# real, que es lo que hace falta para poder mirar el servidor del usuario.
TMUX_REAL = shutil.which("tmux")

# Motivo legible en el `skip`: si tmux no está, los tests de `_quote_path`
# (función pura) siguen corriendo, que es la mitad con más valor por línea.
sin_tmux = pytest.mark.skipif(
    TMUX_REAL is None,
    reason="tmux no está instalado en esta máquina (falta en el PATH); los "
    "tests de ciclo de vida necesitan un tmux real. Los de _quote_path no.",
)

# Formato propio para la foto del servidor del usuario. Se incluye `created`
# a propósito: comparar solo los nombres dejaría pasar el caso en el que una
# sesión se mata y se recrea con el mismo nombre, que para el usuario es
# exactamente la pérdida contra la que existe este archivo.
_FOTO = "#{session_name}\t#{session_created}"


def sesiones_del_usuario() -> dict[str, str]:
    """Nombre -> fecha de creación de las sesiones del servidor por defecto.

    Sin `-L`: es justo el servidor que estos tests NO deben tocar. La llamada
    es de solo lectura (`list-sessions`) y no arranca servidor si no lo hay.
    """
    if TMUX_REAL is None:
        return {}
    result = subprocess.run(
        [TMUX_REAL, "list-sessions", "-F", _FOTO],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        # "no server running": el usuario no tiene tmux abierto. Foto vacía.
        return {}
    foto: dict[str, str] = {}
    for linea in result.stdout.splitlines():
        if "\t" in linea:
            nombre, creada = linea.split("\t", 1)
            foto[nombre] = creada
    return foto


@pytest.fixture(scope="module", autouse=True)
def _centinela_sesiones_del_usuario():
    """Falla el módulo entero si alguna sesión real del usuario cambió.

    La red por debajo de las otras dos. No comprueba un mecanismo: comprueba
    el resultado, que es lo único que le importa a quien tiene cinco sesiones
    con trabajo dentro.
    """
    antes = sesiones_del_usuario()
    yield
    despues = sesiones_del_usuario()
    assert despues == antes, (
        "Los tests han alterado las sesiones de tmux REALES del usuario. "
        f"Desaparecidas: {sorted(set(antes) - set(despues))}; "
        f"nuevas: {sorted(set(despues) - set(antes))}; "
        f"recreadas (mismo nombre, otra fecha): "
        f"{sorted(n for n in set(antes) & set(despues) if antes[n] != despues[n])}"
    )


# ----------------------------------------------------------------------
# Andamiaje: el servidor de pruebas
# ----------------------------------------------------------------------


@dataclass
class ServidorDePruebas:
    """Lo que un test necesita saber del servidor aislado."""

    wrapper: Path
    socket: str

    def ejecutar(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Un comando de tmux contra el servidor de pruebas, por el wrapper.

        Para observar cosas que `tmux_service` no expone (`pane_current_path`)
        sin construir a mano el `-L`, que es justo el detalle que no conviene
        repetir en cada test.
        """
        return subprocess.run(
            [str(self.wrapper), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def apagar(self, timeout: float = 5.0) -> None:
        """`kill-server` y espera a que el servidor esté REALMENTE apagado.

        `kill-server` es asíncrono: el cliente vuelve en cuanto ha mandado la
        orden, no cuando el servidor ha terminado de morir. Un `new-session`
        que caiga en esa ventana no encuentra un socket limpio ni un servidor
        vivo, y falla con **"server exited unexpectedly"** — un error que
        `create_session` no reconoce (no dice "duplicate session"), así que lo
        eleva como `TmuxError` y el test que lo pillara se cae por un motivo
        que no tiene nada que ver con lo que estaba probando.

        Medido contra tmux 3.4, encadenando `kill-server` y `new-session` sin
        pausa: **30 fallos en 500 intentos (6 %)**. Con esta espera, 0 en 1200.
        En la suite la tasa era mucho más baja —del orden de 1 pasada completa
        de cada 20— porque entre el teardown de un test y el siguiente hay
        decenas de milisegundos de pytest, casi siempre suficientes. "Casi
        siempre" es exactamente lo que no sirve cuando el CI bloquea merges:
        un rojo intermitente enseña a reintentar hasta que pase, y ahí el CI
        deja de valer para nada.

        La condición de parada es que `list-sessions` conteste "no server
        running": es la respuesta que da tmux cuando el socket ya no existe o
        no responde, o sea justo lo contrario de "el servidor sigue muriendo".
        """
        self.ejecutar("kill-server")
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if "no server running" in (self.ejecutar("list-sessions").stderr or ""):
                return
            time.sleep(0.005)
        raise AssertionError(
            f"el servidor de pruebas ({self.socket}) sigue respondiendo "
            f"{timeout}s después del kill-server"
        )


@pytest.fixture(scope="module")
def _servidor_de_pruebas(tmp_path_factory: pytest.TempPathFactory):
    """Crea el wrapper y, al terminar el módulo, mata el servidor de pruebas.

    `kill-server` aquí es seguro **precisamente porque es otro servidor**: el
    wrapper lleva su `-L` incrustado, así que el comando no puede alcanzar al
    del usuario ni aunque quisiera.

    Es de ámbito módulo y no de función para que la ruta del socket unix sea
    corta: los sockets tienen un límite de ~108 bytes y los `tmp_path` por
    test incluyen el nombre del test, que en este archivo es largo.
    """
    if TMUX_REAL is None:
        pytest.skip("tmux no está instalado")

    base = tmp_path_factory.mktemp("tmux-aislado")
    socket = f"muxspace-tests-{uuid.uuid4().hex[:8]}"
    wrapper = base / "tmux"
    wrapper.write_text(
        "#!/bin/sh\n"
        # Ver el docstring del módulo: la suite puede correr dentro de una
        # sesión de tmux del usuario y esta variable apunta a su socket.
        "unset TMUX\n"
        f"TMUX_TMPDIR={shlex.quote(str(base))}\n"
        "export TMUX_TMPDIR\n"
        f"exec {shlex.quote(TMUX_REAL)} -L {shlex.quote(socket)} \"$@\"\n"
    )
    wrapper.chmod(0o755)

    ruta_socket = base / f"tmux-{os.getuid()}" / socket
    assert len(str(ruta_socket).encode()) < 100, (
        f"la ruta del socket es demasiado larga ({ruta_socket}): un socket "
        "unix no puede pasar de ~108 bytes y tmux fallaría por un motivo "
        "que no tiene nada que ver con lo que se está probando"
    )

    servidor = ServidorDePruebas(wrapper=wrapper, socket=socket)
    yield servidor

    # `yield` y no `addfinalizer` manual: corre pase lo que pase, incluso si
    # un test revienta a mitad dejando sesiones vivas.
    #
    # `apagar()` en vez de `kill-server` + un `assert` a pelo: la comprobación
    # de una sola pasada era ella misma una carrera, porque podía mirar
    # mientras el servidor todavía estaba muriendo.
    servidor.apagar()


@pytest.fixture(autouse=True)
def _binario_prohibido(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Por defecto, en este archivo, hablar con tmux está PROHIBIDO.

    Es `autouse` por el mismo motivo que `data_dir` en el `conftest.py`: el
    aislamiento no puede depender de que quien escriba el próximo test se
    acuerde de pedir la fixture. Sin esto, un test nuevo que llame a
    `tmux_service` y olvide `tmux_aislado` heredaría el `TMUX_BINARY` de
    producción —`tmux` a secas— y acabaría en el servidor del usuario.

    Con esto acaba en un script que se niega, y el modo de fallo es un test en
    rojo con un mensaje que explica qué falta.
    """
    prohibido = tmp_path / "tmux-prohibido"
    prohibido.write_text(
        "#!/bin/sh\n"
        'echo "TMUX PROHIBIDO: este test llamó a tmux_service sin pedir la '
        'fixture tmux_aislado, que es la que lo aparta del servidor del '
        'usuario. Añádela a la firma del test." >&2\n'
        "exit 1\n"
    )
    prohibido.chmod(0o755)
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", str(prohibido))
    monkeypatch.setattr(config, "TMUX_BINARY", str(prohibido))
    return prohibido


@pytest.fixture
def tmux_aislado(
    _binario_prohibido: Path,
    _servidor_de_pruebas: ServidorDePruebas,
    monkeypatch: pytest.MonkeyPatch,
) -> ServidorDePruebas:
    """Apunta `tmux_service` al servidor de pruebas y lo verifica.

    Depende de `_binario_prohibido` explícitamente para fijar el orden: esta
    fixture tiene que parchear DESPUÉS que él, o el script prohibido ganaría.
    """
    servidor = _servidor_de_pruebas
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", str(servidor.wrapper))
    monkeypatch.setattr(config, "TMUX_BINARY", str(servidor.wrapper))

    # La verificación no es "el atributo tiene el valor que le he puesto"
    # (tautología): se crea una sesión POR EL CAMINO REAL —el mismo
    # `create_session` que usan los tests— y se comprueba en el servidor del
    # usuario que no ha aparecido. Se hace antes de CADA test y no una sola
    # vez, porque el precio de un aislamiento roto no es un test en rojo.
    canario = f"muxspace-canario-{uuid.uuid4().hex[:8]}"
    assert tmux_service.create_session(canario) is True
    if canario in sesiones_del_usuario():
        # Solo se llega aquí si el parcheo no surtió efecto. La sesión está en
        # el servidor del usuario y es nuestra: se retira por nombre exacto
        # (nunca un kill-server) antes de abortar.
        subprocess.run(
            [TMUX_REAL, "kill-session", "-t", canario],
            capture_output=True,
            timeout=10,
        )
        pytest.fail(
            "AISLAMIENTO ROTO: la sesión creada por tmux_service ha aparecido "
            "en el servidor de tmux del usuario. Ningún test de este archivo "
            "puede correr en estas condiciones."
        )
    assert tmux_service.kill_session(canario) is True

    yield servidor

    # Entre test y test el servidor de pruebas se tira entero. Es más simple
    # que enumerar y matar sesión a sesión, no deja restos si un test murió a
    # medias, y es seguro por lo de siempre: es otro servidor. Lo levanta de
    # nuevo el primer `new-session` del test siguiente.
    #
    # Y se ESPERA a que muera (ver `ServidorDePruebas.apagar`): sin esa espera,
    # el `new-session` del test siguiente puede caer en la ventana en la que el
    # servidor ya no atiende pero el socket todavía está, y falla con "server
    # exited unexpectedly". Era el origen del test intermitente.
    servidor.apagar()


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------


def esperar(condicion, mensaje: str, timeout: float = 10.0) -> None:
    """Espera a que `condicion()` sea cierta, o falla con `mensaje`.

    `create_session` inyecta el `cd` y el comando con `send-keys`: el shell de
    la sesión los procesa de forma asíncrona. Comprobar el efecto justo
    después de la llamada sería una carrera; un `sleep` fijo sería lento o
    inestable según la máquina.
    """
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return
        time.sleep(0.05)
    pytest.fail(f"{mensaje} (no ocurrió en {timeout}s)")


def nombre(sufijo: str = "") -> str:
    """Un nombre de sesión único para el servidor de pruebas."""
    return f"muxspace-test-{uuid.uuid4().hex[:8]}{sufijo}"


# ----------------------------------------------------------------------
# Los auto-tests del aislamiento. Son la licencia para escribir los demás.
# ----------------------------------------------------------------------


@sin_tmux
def test_auto_la_sesion_de_los_tests_no_existe_en_el_servidor_del_usuario(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """El test que autoriza a todos los demás.

    Crea una sesión por el camino real y comprueba las dos mitades: que el
    servidor de pruebas SÍ la ve (si no, el resto del archivo estaría
    probando el vacío) y que el del usuario NO, con sus sesiones intactas
    hasta la fecha de creación.
    """
    antes = sesiones_del_usuario()

    sesion = nombre()
    assert tmux_service.create_session(sesion) is True

    # Mitad positiva: existe de verdad, en el servidor de pruebas.
    assert tmux_service.session_exists(sesion)
    assert sesion in tmux_aislado.ejecutar("list-sessions", "-F", "#S").stdout

    # Mitad negativa: el servidor del usuario no sabe nada de ella.
    despues = sesiones_del_usuario()
    assert sesion not in despues, (
        "la sesión de prueba ha aparecido en el servidor de tmux del usuario"
    )
    assert despues == antes, (
        "las sesiones reales del usuario han cambiado al crear una de prueba"
    )


@sin_tmux
def test_auto_el_binario_bajo_prueba_es_el_wrapper_y_no_el_tmux_del_sistema(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """El parche llegó a `tmux_service`, que es el módulo que lo lee.

    Complementa al test de arriba por el otro lado: aquel mira el efecto,
    este mira la causa. Si alguien "arregla" el parcheo cambiándolo a
    `config.TMUX_BINARY` (que es donde parece que vive), este test lo caza.
    """
    assert tmux_service.TMUX_BINARY == str(tmux_aislado.wrapper)
    assert Path(tmux_service.TMUX_BINARY).is_file()
    assert f"-L {tmux_aislado.socket}" in tmux_aislado.wrapper.read_text(), (
        "el wrapper no selecciona un socket propio: no habría aislamiento"
    )
    assert tmux_aislado.socket.startswith("muxspace-tests-")


@sin_tmux
def test_auto_sin_la_fixture_de_aislamiento_no_se_puede_hablar_con_tmux() -> None:
    """La fixture `autouse` prohíbe tmux por defecto, y se nota.

    Este test NO pide `tmux_aislado` a propósito: comprueba que el modo de
    fallo de un test olvidadizo es un error, y no una conversación con el
    servidor del usuario.
    """
    assert "prohibido" in tmux_service.TMUX_BINARY
    with pytest.raises(TmuxError):
        tmux_service.create_session(nombre())


# ----------------------------------------------------------------------
# Ciclo de vida de las sesiones
# ----------------------------------------------------------------------


@sin_tmux
def test_crear_una_sesion_devuelve_true_y_session_exists_la_ve(
    tmux_aislado: ServidorDePruebas,
) -> None:
    sesion = nombre()
    assert tmux_service.session_exists(sesion) is False
    assert tmux_service.create_session(sesion) is True
    assert tmux_service.session_exists(sesion) is True


@sin_tmux
def test_crear_una_sesion_con_un_nombre_ya_usado_devuelve_false_sin_lanzar(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """El duplicado es un "no" del dominio, no una excepción.

    tmux responde con returncode != 0 y "duplicate session: ..." por stderr;
    `create_session` traduce ESE stderr concreto a False. Si tmux cambiara el
    texto, el módulo pasaría a lanzar `TmuxError` y el panel devolvería un 500
    donde hoy dice "ya existe". Por eso el caso se prueba contra tmux real.
    """
    sesion = nombre()
    assert tmux_service.create_session(sesion) is True
    assert tmux_service.create_session(sesion) is False
    # Y la original sigue viva: el intento fallido no se la llevó por delante.
    assert tmux_service.session_exists(sesion) is True


@sin_tmux
def test_renombrar_una_sesion_hace_desaparecer_el_nombre_viejo(
    tmux_aislado: ServidorDePruebas,
) -> None:
    viejo, nuevo = nombre("-viejo"), nombre("-nuevo")
    assert tmux_service.create_session(viejo) is True

    assert tmux_service.rename_session(viejo, nuevo) is True

    assert tmux_service.session_exists(nuevo) is True
    assert tmux_service.session_exists(viejo) is False


@sin_tmux
def test_renombrar_una_sesion_que_no_existe_devuelve_false(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Igual que el duplicado: depende del stderr "can't find session"."""
    # Con al menos una sesión viva, para que el servidor esté arrancado y el
    # motivo del False sea "no existe esa sesión" y no "no hay servidor".
    assert tmux_service.create_session(nombre()) is True
    assert tmux_service.rename_session(nombre("-fantasma"), nombre()) is False


@sin_tmux
def test_renombrar_al_nombre_de_otra_sesion_lanza_con_codigo_traducible(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Aquí sí hay excepción, y con el `code` que el frontend traduce.

    Es la diferencia con el caso anterior: "no existe el origen" es False,
    "el destino ya está ocupado" es un error que el usuario tiene que ver.
    """
    una, otra = nombre("-una"), nombre("-otra")
    assert tmux_service.create_session(una) is True
    assert tmux_service.create_session(otra) is True

    with pytest.raises(TmuxError) as exc:
        tmux_service.rename_session(una, otra)
    assert exc.value.code == "err.session_exists"
    assert exc.value.params == {"name": otra}
    # Ninguna de las dos se ha movido.
    assert tmux_service.session_exists(una) is True
    assert tmux_service.session_exists(otra) is True


@sin_tmux
def test_matar_una_sesion_devuelve_true_y_deja_de_existir(
    tmux_aislado: ServidorDePruebas,
) -> None:
    sesion = nombre()
    assert tmux_service.create_session(sesion) is True

    assert tmux_service.kill_session(sesion) is True

    assert tmux_service.session_exists(sesion) is False


@sin_tmux
def test_matar_una_sesion_inexistente_devuelve_false_sin_excepcion(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Idempotencia: matar dos veces no es un error, es un no-op.

    Se prueban los dos caminos que devuelven False, que en el código son la
    misma rama pero en tmux son dos stderr distintos: "can't find session"
    (hay servidor, no hay sesión) y "no server running" (no hay ni servidor).
    """
    superviviente = nombre("-viva")
    assert tmux_service.create_session(superviviente) is True
    # Hay servidor, pero no esa sesión.
    assert tmux_service.kill_session(nombre("-fantasma")) is False
    assert tmux_service.session_exists(superviviente) is True

    # Y ahora sin servidor: se mata la única que quedaba.
    assert tmux_service.kill_session(superviviente) is True
    assert tmux_service.kill_session(superviviente) is False


@sin_tmux
def test_list_sessions_devuelve_la_sesion_con_todos_sus_campos(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Los cuatro campos del dataclass, con su tipo, no solo el nombre.

    `windows` y `attached` se parsean a mano de una línea separada por
    tabuladores (`"1"` -> True, dígitos -> int). Un cambio en `_FORMAT` que
    descolocara las columnas dejaría los nombres bien y el resto en silencio
    a 0/False, que es exactamente lo que el panel pinta al usuario.
    """
    sesion = nombre()
    antes = int(time.time())
    assert tmux_service.create_session(sesion) is True

    encontradas = [s for s in tmux_service.list_sessions() if s.name == sesion]
    assert len(encontradas) == 1
    s = encontradas[0]

    assert s.name == sesion
    # Una sesión nueva tiene exactamente una ventana.
    assert s.windows == 1
    assert isinstance(s.windows, int)
    # `-d`: creada desacoplada, nadie conectado.
    assert s.attached is False
    # `created` es la marca de tiempo unix de tmux, como cadena.
    assert s.created is not None and s.created.isdigit()
    assert antes - 5 <= int(s.created) <= int(time.time()) + 5

    # El dict que viaja al frontend lleva las mismas cuatro claves.
    assert s.to_dict() == {
        "name": sesion,
        "windows": 1,
        "attached": False,
        "created": s.created,
    }


@sin_tmux
def test_list_sessions_sin_servidor_arrancado_devuelve_lista_vacia(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Sin sesiones no hay error: hay lista vacía.

    Es el estado en el que arranca el panel en una máquina recién encendida.
    Si `list_sessions` lanzara aquí, la primera carga sería un 500.

    `apagar()` y no `kill-server` a secas: lo que se quiere probar es "no hay
    servidor", no "el servidor se está muriendo", que es un estado distinto y
    transitorio en el que tmux contesta otra cosa.
    """
    tmux_aislado.apagar()
    assert tmux_service.list_sessions() == []


def _tmux_de_mentira(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    salida: str = "",
    error: str = "",
    codigo: int = 0,
) -> None:
    """Sustituye tmux por un script que dice exactamente lo que se le pida.

    Es la única parte del archivo donde NO se habla con tmux, y con motivo: lo
    que se prueba aquí es cómo `list_sessions` digiere una salida rara, y una
    salida rara es justamente lo que un tmux sano nunca produce. Es un doble
    del sistema operativo, no un mock del módulo bajo prueba.

    El script atiende `start-server` por separado porque `list_sessions`
    empieza llamándolo y no queremos que ese primer paso devuelva la salida de
    prueba ni el código de error.
    """
    falso = tmp_path / "tmux-de-mentira"
    falso.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "start-server" ]; then exit 0; fi\n'
        f"printf %s {shlex.quote(salida)}\n"
        f"printf %s {shlex.quote(error)} >&2\n"
        f"exit {codigo}\n"
    )
    falso.chmod(0o755)
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", str(falso))


def test_list_sessions_tolera_lineas_en_blanco_y_campos_incompletos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una salida a medias degrada campo a campo, no tumba el listado entero.

    Es el contrato que el módulo se propone (el comentario dice "tolerante a
    campos faltantes") y no estaba escrito en ningún sitio comprobable. La
    consecuencia práctica: si una versión futura de tmux dejara de rellenar
    `session_created`, el panel seguiría listando las sesiones —con la fecha a
    None— en vez de devolver un 500.
    """
    _tmux_de_mentira(
        tmp_path,
        monkeypatch,
        salida=(
            "completa\t3\t1\t1700000000\n"
            "\n"  # línea vacía: se ignora
            "   \n"  # solo espacios: también
            "sin-fecha\t2\t0\n"  # falta `created`
            "solo-nombre\n"  # faltan los tres
            "ventanas-no-numericas\tmuchas\t0\t1700000000\n"
        ),
    )

    por_nombre = {s.name: s for s in tmux_service.list_sessions()}

    assert set(por_nombre) == {
        "completa",
        "sin-fecha",
        "solo-nombre",
        "ventanas-no-numericas",
    }
    completa = por_nombre["completa"]
    assert (completa.windows, completa.attached) == (3, True)
    assert por_nombre["completa"].created == "1700000000"
    assert por_nombre["sin-fecha"].created is None
    assert por_nombre["sin-fecha"].attached is False
    assert (por_nombre["solo-nombre"].windows, por_nombre["solo-nombre"].created) == (
        0,
        None,
    )
    # Un contador no numérico cae a 0 en vez de reventar el parseo.
    assert por_nombre["ventanas-no-numericas"].windows == 0


def test_list_sessions_con_un_error_desconocido_lanza_con_el_stderr_dentro(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un fallo que no es "no hay servidor" sí es un error, y viaja completo.

    `technical` lleva el stderr crudo (en el idioma del sistema) para que el
    frontend lo pinte junto al mensaje traducido, según documenta `errors.py`.
    Si se tragara este caso como lista vacía, el panel diría "no hay sesiones"
    cuando lo que hay es un tmux roto.
    """
    _tmux_de_mentira(
        tmp_path, monkeypatch, error="server exited unexpectedly", codigo=1
    )

    with pytest.raises(TmuxError) as exc:
        tmux_service.list_sessions()
    assert exc.value.code == "err.tmux_unknown"
    assert exc.value.technical == "server exited unexpectedly"


@sin_tmux
def test_crear_una_sesion_con_cwd_la_deja_en_esa_carpeta(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """El `cd` que ve el usuario al abrir la terminal.

    Se comprueba con `pane_current_path`, que es lo que tmux sabe del shell,
    y no con el `cd` que enviamos: preguntar por lo que se acaba de escribir
    no demuestra que llegara a ejecutarse.
    """
    carpeta = tmp_path / "proyecto"
    carpeta.mkdir()
    sesion = nombre()

    assert tmux_service.create_session(sesion, cwd=str(carpeta)) is True

    def en_la_carpeta() -> bool:
        salida = tmux_aislado.ejecutar(
            "display-message", "-p", "-t", sesion, "#{pane_current_path}"
        )
        return salida.stdout.strip() == str(carpeta)

    esperar(en_la_carpeta, f"la sesión no se posicionó en {carpeta}")


@sin_tmux
def test_crear_una_sesion_con_command_lo_ejecuta_en_su_shell(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """El comando corre de verdad, y la sesión sobrevive a que termine.

    Las dos mitades importan. Si solo se comprobara el efecto, un
    `new-session -d <comando>` (que mata la sesión al acabar el comando) daría
    el mismo resultado, y el panel dejaría al usuario mirando una terminal que
    se cierra sola en cuanto sale de nvim.
    """
    marcador = tmp_path / "el-comando-corrio"
    sesion = nombre()

    assert (
        tmux_service.create_session(
            sesion, command=f"touch {shlex.quote(str(marcador))}"
        )
        is True
    )

    esperar(marcador.exists, "el comando no llegó a ejecutarse")
    assert tmux_service.session_exists(sesion) is True


@sin_tmux
def test_crear_con_cwd_y_command_ejecuta_el_comando_dentro_del_cwd(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """El `cd X && comando` del mismo shell, con espacios en X.

    La carpeta lleva espacios a propósito: es el caso que rompe si alguien
    quita el `_quote_path` del `cd`. Y el comando toca una ruta RELATIVA, así
    que el fichero solo puede aparecer si el `cd` funcionó antes.
    """
    carpeta = tmp_path / "mi carpeta con espacios"
    carpeta.mkdir()
    sesion = nombre()

    assert (
        tmux_service.create_session(
            sesion, command="touch marcador-relativo", cwd=str(carpeta)
        )
        is True
    )

    esperar(
        (carpeta / "marcador-relativo").exists,
        "el comando no se ejecutó dentro del cwd (¿se rompió el cd?)",
    )


@sin_tmux
def test_send_command_escribe_en_la_sesion_y_el_vacio_es_un_no_op(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """`send_command` con contenido ejecuta; en blanco no hace nada.

    El caso en blanco se prueba contra una sesión INEXISTENTE: si llegara a
    llamar a tmux, tmux fallaría y `send_command` lanzaría. Que no lance es la
    prueba de que ni lo intentó.
    """
    tmux_service.send_command(nombre("-fantasma"), "   \n  ")

    marcador = tmp_path / "enviado"
    sesion = nombre()
    assert tmux_service.create_session(sesion) is True
    tmux_service.send_command(sesion, f"touch {shlex.quote(str(marcador))}")
    esperar(marcador.exists, "send_command no ejecutó el comando")


@sin_tmux
def test_detach_session_sin_servidor_arrancado_devuelve_false(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """Mismo contrato que `kill_session`: "no estaba" no es una excepción.

    Se prueba solo la rama de "no hay servidor". La de "hay servidor y no hay
    esa sesión" no se puede alcanzar desde aquí: `detach-client` falla con
    "no current client" —no con "can't find session"— cuando no hay ningún
    cliente adjunto, que es siempre el caso de un test. Probarla de verdad
    exige un cliente attachado, y eso es terreno de US-021/US-025.

    Mismo motivo que el de `list_sessions` para usar `apagar()`: la rama que
    se quiere ejercitar es la de "no hay servidor", y con el servidor a medio
    morir tmux contesta "server exited unexpectedly", que es otra rama.
    """
    tmux_aislado.apagar()
    assert tmux_service.detach_session(nombre("-fantasma")) is False


def test_si_el_binario_de_tmux_no_existe_se_lanza_un_error_con_codigo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El error de "tmux no instalado" viaja traducible, no como OSError.

    No necesita tmux: al contrario, necesita que no lo haya. Es el escenario
    de un despliegue donde falta el paquete, y el panel tiene que decirlo en
    el idioma del usuario en vez de reventar con un traceback.
    """
    inexistente = str(tmp_path / "no-hay-tmux-aqui")
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", inexistente)

    with pytest.raises(TmuxError) as exc:
        tmux_service.create_session(nombre())
    assert exc.value.code == "err.tmux_not_found"
    assert exc.value.params == {"binary": inexistente}


def test_list_sessions_sin_tmux_instalado_lanza_error_con_codigo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """La misma promesa que el test de arriba, por la puerta de `list_sessions`.

    Fue un `xfail(strict=True)` desde US-007: `_ensure_tmux_server` hacía un
    `subprocess.run` suelto, así que con tmux sin instalar el
    `FileNotFoundError` salía en crudo desde ahí ANTES de llegar al `except`
    de `list_sessions` —que quedaba como código muerto— y el panel devolvía un
    500 con traceback en vez del mensaje traducido.

    US-019 lo arregla de paso, porque el `start-server` pasa ahora por
    `_run_tmux`, que es quien traduce el error. El marcador se borra en este
    mismo PR: con `strict=True`, un xfail que pasa se pone en ROJO, así que
    dejarlo habría roto la suite.
    """
    inexistente = str(tmp_path / "no-hay-tmux-aqui")
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", inexistente)

    with pytest.raises(TmuxError) as exc:
        tmux_service.list_sessions()
    assert exc.value.code == "err.tmux_not_found"


# ----------------------------------------------------------------------
# La propiedad de fondo: tmux se invoca por argv, nunca por shell
# ----------------------------------------------------------------------


@sin_tmux
def test_un_nombre_de_sesion_con_sustitucion_de_comandos_no_ejecuta_nada(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """El test más valioso del archivo.

    `subprocess.run` con una LISTA no pasa por ningún shell: el nombre de la
    sesión llega a tmux como un argumento más, con sus paréntesis y su dólar
    dentro, y nadie lo interpreta. La inyección de comandos por el nombre de
    la sesión no existe como categoría mientras eso se mantenga.

    El centinela va bajo `tmp_path` y no bajo `/tmp` a secas: si algún día
    este test falla de verdad, el daño se queda dentro del directorio
    temporal que pytest borra, y no deja un fichero en un directorio
    compartido con el resto del sistema.
    """
    centinela = tmp_path / f"pwned-{uuid.uuid4().hex[:8]}"
    malicioso = f"$(touch {centinela})"

    # El `TmuxError` se traga a propósito y el centinela se mira ANTES de
    # juzgar el resultado. Si el nombre acabara pasando por un shell, la
    # sustitución se ejecutaría y tmux recibiría un `-s` vacío: la llamada
    # fallaría, sí, pero el fichero ya estaría creado. Sin este orden el test
    # se caería igual, con un "err.session_create_failed" que no dice nada de
    # lo que de verdad ha pasado.
    try:
        creada = tmux_service.create_session(malicioso)
    except TmuxError:
        creada = False

    assert not centinela.exists(), (
        f"¡INYECCIÓN! El nombre de la sesión se ejecutó como shell y creó "
        f"{centinela}. Alguien ha cambiado subprocess.run(lista) por shell=True."
    )
    # tmux acepta el nombre tal cual: es un nombre raro, no una orden.
    assert creada is True
    # Y la mitad positiva: la sesión existe CON ese nombre literal. Sin ella,
    # un `create_session` que se negara a crear nada pasaría el test por la
    # vía barata sin demostrar nada sobre el shell.
    assert malicioso in [s.name for s in tmux_service.list_sessions()]


@sin_tmux
@pytest.mark.parametrize(
    "carga",
    [
        "$(touch PWNED)",
        "`touch PWNED`",
        "; touch PWNED",
        "&& touch PWNED",
        "| touch PWNED",
    ],
    ids=["dolar-parentesis", "backticks", "punto-y-coma", "and", "pipe"],
)
@pytest.mark.parametrize("operacion", ["rename", "kill"])
def test_ninguna_operacion_interpreta_el_nombre_de_la_sesion_como_shell(
    tmux_aislado: ServidorDePruebas, tmp_path: Path, carga: str, operacion: str
) -> None:
    """La propiedad no es de `create_session`: es de `_run_tmux`, o sea de todas.

    Se recorre el resto de la superficie (renombrar y matar) con las cinco
    formas de encadenar comandos en sh. Ninguna puede escribir el centinela.

    No se afirma nada sobre el valor de retorno de la operación: para algunos
    de estos nombres tmux ni siquiera encuentra la sesión (ver
    `test_una_sesion_cuyo_nombre_empieza_por_dolar_no_se_puede_matar`). Eso es
    otro asunto; aquí lo único que se mide es que nadie ejecutó nada.
    """
    centinela = tmp_path / f"pwned-{uuid.uuid4().hex[:8]}"
    nombre_malicioso = carga.replace("PWNED", str(centinela))

    # Mismo motivo que en el test anterior: primero se mira el centinela, y
    # para eso hay que dejar que la operación falle sin romper el test.
    hecha = False
    try:
        if operacion == "rename":
            origen = nombre()
            tmux_service.create_session(origen)
            hecha = tmux_service.rename_session(origen, nombre_malicioso)
        else:
            hecha = tmux_service.create_session(nombre_malicioso)
            tmux_service.kill_session(nombre_malicioso)
    except TmuxError:
        pass

    assert not centinela.exists(), (
        f"¡INYECCIÓN! La operación '{operacion}' interpretó el nombre como "
        f"shell y creó {centinela}"
    )
    # La mitad positiva: la operación con el nombre raro llegó a hacerse. Sin
    # ella, un `tmux_service` que se negara a tocar estos nombres pasaría el
    # test sin demostrar nada sobre el shell.
    assert hecha is True


@sin_tmux
def test_una_sesion_cuyo_nombre_empieza_por_dolar_no_se_puede_matar(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """Comportamiento observado de tmux, fijado aquí porque sorprende.

    En un `-t`, tmux lee un `$` inicial como el prefijo de un **ID de sesión**
    (`$0`, `$1`…), no como el primer carácter de un nombre. Así que la sesión
    del test de inyección de arriba se crea sin problema y se lista con su
    nombre entero, pero después no hay forma de apuntarla: `kill_session`
    devuelve False ("can't find session") y se queda ahí para siempre. Ni el
    prefijo `=` de coincidencia exacta la rescata (comprobado en tmux 3.4).

    No es una vulnerabilidad —nada se ejecuta, eso lo cubren los tests de
    arriba— pero sí una sesión que el panel no puede cerrar.

    Este test NO cambia con el arreglo de S17 y por eso se queda como está:
    describe a tmux, no al panel. Lo que se arregló fue el camino por el que
    el panel llegaba a crear uno de estos nombres, y eso lo cubre el test de
    abajo.
    """
    rara = f"$(true {tmp_path})"
    assert tmux_service.create_session(rara) is True
    assert rara in [s.name for s in tmux_service.list_sessions()]

    assert tmux_service.kill_session(rara) is False
    assert rara in [s.name for s in tmux_service.list_sessions()], (
        "tmux ya sabe apuntar sesiones que empiezan por '$': borra este test"
    )


@sin_tmux
@pytest.mark.parametrize(
    "etiqueta",
    ["$MI_COMANDO", "$(id) build", "$", "$HOME/proyecto"],
    ids=["variable", "sustitucion", "solo-el-dolar", "con-barra"],
)
def test_regresion_s17_una_etiqueta_con_dolar_da_una_sesion_que_si_se_puede_matar(
    tmux_aislado: ServidorDePruebas, etiqueta: str
) -> None:
    """S17: el camino por el que el panel llegaba a crear una sesión incerrable.

    `_SESSION_NAME_RE` bloquea el '$' en `/api/create-session`, pero
    `/api/commands/{id}/launch` y `/api/projects/{id}/run` no pasan por ahí:
    derivan el nombre de sesión de la **etiqueta** del comando o del **título**
    del proyecto con `_tmux_safe_label`, que solo sustituía `[.:/\\]`. Una
    etiqueta que empezara por '$' —perfectamente teclearble en el panel— dejaba
    la sesión del test de arriba: creada, listada y sin forma de cerrarla.

    Se prueba de extremo a extremo y contra tmux de verdad porque el fallo no
    está en ninguna de las dos capas por separado: `_tmux_safe_label` producía
    un nombre razonable y `kill_session` hacía su trabajo. Está en la juntura,
    y una aserción sobre la cadena que devuelve `_tmux_safe_label` no
    demostraría que tmux sabe apuntar el resultado.

    El sustituto se aplica a TODOS los '$', no solo al inicial (que es el
    único que rompe el `-t`). Es deliberado: la alternativa es depender de
    dónde exactamente pone tmux la frontera al parsear un target, que es justo
    la clase de detalle que ya sorprendió una vez.
    """
    nombre_sesion = main._tmux_safe_label(etiqueta)
    assert "$" not in nombre_sesion, (
        f"_tmux_safe_label dejó pasar un '$': {nombre_sesion!r}"
    )

    assert tmux_service.create_session(nombre_sesion) is True
    assert nombre_sesion in [s.name for s in tmux_service.list_sessions()]

    assert tmux_service.kill_session(nombre_sesion) is True
    assert nombre_sesion not in [s.name for s in tmux_service.list_sessions()]


@sin_tmux
def test_un_cwd_con_sustitucion_de_comandos_no_ejecuta_nada(
    tmux_aislado: ServidorDePruebas,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El `cwd` sí acaba dentro de una cadena de shell, y por eso va citado.

    Es el otro lado de la moneda del test anterior: `command` se envía al
    shell de la sesión a propósito, así que el `cd <cwd> && <command>` que
    construye `create_session` es shell de verdad. Lo único que impide que un
    directorio con `$( )` se ejecute es el `shlex.quote` de `_quote_path`.

    El `touch` del centinela va con ruta RELATIVA porque un nombre de
    directorio no puede contener `/`. Eso obliga a saber dónde caería el
    fichero si la sustitución llegara a ejecutarse: en el directorio de
    trabajo del shell de la sesión, que tmux hereda del proceso que lanza
    `new-session`. De ahí el `chdir` a `tmp_path` — sin él el centinela
    aterrizaría en el repositorio.
    """
    monkeypatch.chdir(tmp_path)
    carpeta_maliciosa = tmp_path / "carpeta $(touch pwned)"
    carpeta_maliciosa.mkdir()
    sesion = nombre()

    assert (
        tmux_service.create_session(
            sesion, command="touch marcador-relativo", cwd=str(carpeta_maliciosa)
        )
        is True
    )

    # Se espera al marcador y no a un `sleep` fijo: cuando aparece, el shell
    # ya ha procesado la línea entera, así que si la sustitución fuera a
    # ejecutarse ya lo habría hecho. Y que aparezca DENTRO de la carpeta
    # maliciosa demuestra además que el `cd` llegó ahí, o sea que el shell
    # leyó el nombre entero como una sola ruta literal.
    esperar(
        (carpeta_maliciosa / "marcador-relativo").exists,
        "el cd a la carpeta con metacaracteres no funcionó",
    )
    assert not (tmp_path / "pwned").exists(), (
        "¡INYECCIÓN! El cwd se interpretó como shell y ejecutó el touch"
    )


@sin_tmux
def test_command_si_es_shell_por_diseno(
    tmux_aislado: ServidorDePruebas, tmp_path: Path
) -> None:
    """Documenta el límite: `command` NO se cita, y es intencionado.

    El usuario escribe ahí lo que quiere ejecutar al abrir la terminal
    (`nvim . && git status`), así que citarlo lo rompería. Este test existe
    para que quede escrito dónde está la frontera y para que nadie "arregle"
    `command` con un `shlex.quote` creyendo que endurece algo: lo que
    endurecería es la funcionalidad, hasta romperla.
    """
    marcador = tmp_path / "las-dos-partes"
    sesion = nombre()

    assert (
        tmux_service.create_session(
            sesion, command=f"true && touch {shlex.quote(str(marcador))}"
        )
        is True
    )

    esperar(marcador.exists, "el '&&' de command no se interpretó como shell")


# ----------------------------------------------------------------------
# `_quote_path`: función pura, no necesita tmux
# ----------------------------------------------------------------------


def test_quote_path_deja_una_ruta_limpia_sin_comillas() -> None:
    """Sin metacaracteres no hay nada que citar.

    No es cosmético: es lo que hace que el resto de los tests de este bloque
    signifiquen algo. Si `_quote_path` citara siempre, "está entrecomillada"
    dejaría de ser evidencia de nada.
    """
    assert tmux_service._quote_path("/home/usuario/proyectos/muxspace") == (
        "/home/usuario/proyectos/muxspace"
    )
    assert "'" not in tmux_service._quote_path("/var/log")


def test_quote_path_entrecomilla_una_ruta_con_espacios() -> None:
    resultado = tmux_service._quote_path("/datos/mi carpeta/sub dir")
    assert resultado == "'/datos/mi carpeta/sub dir'"


@pytest.mark.parametrize(
    "peligrosa",
    [
        "/datos/$(touch pwned)",
        "/datos/`touch pwned`",
        "/datos/uno; touch pwned",
        "/datos/uno && touch pwned",
        "/datos/uno | touch pwned",
        "/datos/${HOME}",
        "/datos/uno\ndos",
        "/datos/comilla's",
    ],
    ids=[
        "dolar-parentesis",
        "backticks",
        "punto-y-coma",
        "and",
        "pipe",
        "variable",
        "salto-de-linea",
        "comilla-simple",
    ],
)
def test_quote_path_neutraliza_los_metacaracteres_ante_un_sh_de_verdad(
    peligrosa: str,
) -> None:
    """La aserción fuerte: se le pregunta a `sh`, no a una expresión regular.

    Comprobar "empieza y acaba por comilla simple" probaría el formato de
    `shlex.quote`, no la propiedad. Lo que hace falta saber es que un shell
    real, al leer eso, ve la ruta ENTERA y LITERAL y no ejecuta nada — el
    caso de la comilla simple dentro de la ruta, por ejemplo, no lo cumple
    ningún entrecomillado ingenuo.
    """
    citada = tmux_service._quote_path(peligrosa)

    salida = subprocess.run(
        ["/bin/sh", "-c", f"printf %s {citada}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert salida.returncode == 0
    assert salida.stdout == peligrosa, (
        f"sh interpretó {peligrosa!r} en vez de tratarla como texto literal"
    )


def test_quote_path_permite_un_cd_a_una_carpeta_con_metacaracteres(
    tmp_path: Path,
) -> None:
    """El escenario completo: una carpeta que existe de verdad y un `cd`.

    Es el uso real de `_quote_path` (el `cd <cwd> && <command>` de
    `create_session`) reducido a lo esencial, sin tmux de por medio: la
    carpeta se crea, se hace `cd` a ella desde `sh`, y se comprueba que se
    llegó y que la sustitución que lleva en el nombre no se ejecutó.

    Los `touch` van con ruta relativa porque un nombre de directorio no puede
    contener `/`; el `cwd=escenario` del subprocess fija dónde caerían si se
    llegaran a ejecutar. El escenario es un subdirectorio propio y no
    `tmp_path` a secas para poder afirmar que ahí dentro NO apareció nada
    más: `tmp_path` lo comparten las fixtures autouse del conftest.
    """
    escenario = tmp_path / "escenario"
    escenario.mkdir()
    carpeta = escenario / "rara $(touch pwned) ; `touch pwned2` && x | y"
    carpeta.mkdir()

    salida = subprocess.run(
        ["/bin/sh", "-c", f"cd {tmux_service._quote_path(str(carpeta))} && pwd"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=escenario,
    )

    assert salida.returncode == 0, salida.stderr
    assert salida.stdout.strip() == str(carpeta)
    # Nada nuevo en el escenario aparte de la propia carpeta: si el `$( )`, el
    # `;`, el `` ` `` o el `|` hubieran partido el comando, sh habría hecho
    # algo, aunque fuera fallar dejando basura.
    assert [p.name for p in escenario.iterdir()] == [carpeta.name]


def test_quote_path_expande_la_virgulilla_antes_de_entrecomillar() -> None:
    """El detalle que da nombre a esta historia.

    `shlex.quote` envuelve en comillas simples, y dentro de comillas el shell
    NO expande `~`: `cd '~/proyectos'` busca un directorio llamado
    literalmente `~`, que no existe. Como las rutas de la biblioteca se
    guardan en forma `~/...`, citar sin expandir primero rompe el `cd` de
    todos los proyectos del usuario.

    Se comprueba el ORDEN, no solo el resultado: que no quede ni un `~` en la
    salida es justo lo que distingue "expandir y luego citar" de "citar y
    luego expandir" (que no expandiría) o de "solo citar".
    """
    resultado = tmux_service._quote_path("~/proyectos/muxspace")

    assert "~" not in resultado, (
        "quedó una virgulilla en la salida: si va entre comillas el shell ya "
        "no la expande y el cd falla"
    )
    assert resultado == str(Path.home() / "proyectos/muxspace")


def test_quote_path_expande_y_ademas_entrecomilla_cuando_el_home_lleva_espacios(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Las dos propiedades a la vez, que es donde una anula a la otra.

    Expandir sin citar rompe con espacios; citar sin expandir rompe con `~`.
    Aquí hacen falta las dos. El home se redirige a `tmp_path` para que la
    aserción sea exacta y no dependa de cómo se llame el home de la máquina
    donde corran los tests.
    """
    home_falso = tmp_path / "home de prueba"
    home_falso.mkdir()
    monkeypatch.setenv("HOME", str(home_falso))

    resultado = tmux_service._quote_path("~/carpeta con espacios")

    assert "~" not in resultado
    assert resultado == f"'{home_falso}/carpeta con espacios'"
    # Y el shell la lee entera, que es para lo que sirve.
    salida = subprocess.run(
        ["/bin/sh", "-c", f"printf %s {resultado}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert salida.stdout == f"{home_falso}/carpeta con espacios"


def test_quote_path_con_una_ruta_vacia_devuelve_dos_comillas() -> None:
    """La cadena vacía tiene que seguir siendo UN argumento.

    `cd ` sin nada detrás se va al home; `cd ''` falla o se queda donde está.
    Ninguna de las dos es interesante por sí misma: lo que importa es que
    `_quote_path("")` no devuelva la cadena vacía, porque eso convertiría
    `cd  && comando` en un `cd` sin argumento y el comando correría en un
    directorio que no es el que el usuario pidió.

    (En la práctica `create_session` filtra el vacío antes de llegar aquí; el
    contrato de la función se fija igualmente, que es lo que se refactoriza.)
    """
    assert tmux_service._quote_path("") == "''"


def test_quote_path_con_none_lanza_typeerror() -> None:
    """`None` no es una ruta, y el fallo es ruidoso e inmediato.

    Se documenta el comportamiento real (`os.path.expanduser` rechaza `None`)
    en vez de fingir que la función lo tolera. Es el comportamiento deseable:
    un `None` que llegara hasta aquí sería un fallo del llamante, y prefiero
    verlo en la traza que verlo convertido en `cd 'None'`. Quien lo cambie a
    devolver algo, que lo haga a propósito y actualice este test.
    """
    with pytest.raises(TypeError):
        tmux_service._quote_path(None)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# El andamiaje probándose a sí mismo.
# ----------------------------------------------------------------------


@sin_tmux
def test_apagar_deja_el_servidor_confirmadamente_muerto(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """El contrato de `ServidorDePruebas.apagar`, en una línea."""
    tmux_aislado.ejecutar("new-session", "-d", "-s", nombre())

    tmux_aislado.apagar()

    assert "no server running" in tmux_aislado.ejecutar("list-sessions").stderr


@sin_tmux
def test_regresion_apagar_y_crear_encadenados_no_produce_fallos(
    tmux_aislado: ServidorDePruebas,
) -> None:
    """La carrera que hacía intermitente a esta suite, en su forma concentrada.

    `kill-server` es asíncrono: vuelve cuando ha mandado la orden, no cuando el
    servidor ha muerto. Un `new-session` que caiga en esa ventana falla con
    "server exited unexpectedly", que `create_session` no reconoce —no dice
    "duplicate session"— y eleva como `TmuxError`. Como el teardown de
    `tmux_aislado` hacía justo eso antes de cada test siguiente, la suite
    entera fallaba cada ~20 pasadas completas, en un test distinto cada vez.

    Aquí se encadenan las dos operaciones sin la pausa que pytest regala entre
    test y test, que es lo que escondía el problema. Medido en tmux 3.4:

    | Encadenando                      | Fallos     |
    |----------------------------------|------------|
    | `kill-server` + `new-session`    | 30 / 500 (6 %) |
    | `apagar()` + `new-session`       | 0 / 1200   |

    El test es probabilista **solo en una dirección**: con `apagar()` puesto no
    falla nunca (0 de 1200 medidos), así que un rojo aquí siempre significa que
    la carrera ha vuelto. Con la espera quitada, 60 vueltas la cazan con ~97 %
    de probabilidad. Cuesta alrededor de un segundo.
    """
    for i in range(60):
        tmux_aislado.apagar()
        assert tmux_service.create_session(f"{nombre()}-{i}") is True, (
            f"la creación falló en la vuelta {i}: la carrera del kill-server "
            "ha vuelto (¿alguien cambió `apagar()` por un `kill-server` suelto?)"
        )


# ----------------------------------------------------------------------
# `start-server` una sola vez por proceso (US-019)
# ----------------------------------------------------------------------
#
# Antes, `list_sessions()` lanzaba `start-server` Y `list-sessions` en cada
# llamada. Con el refresco del frontend a 8 s eso son dos procesos cada 8 s
# **por pestaña abierta**, todo el día, para repetirle a tmux algo que ya
# sabe. Lo que se prueba aquí no es que el flag exista: es que se lanza un
# proceso menos por listado y que el panel sigue recuperándose si el servidor
# de tmux se muere por debajo.
#
# Se cuenta con un wrapper que registra cada invocación en un fichero, en vez
# de parchear `subprocess.run`. Es la misma decisión que documenta la cabecera
# del módulo: un mock probaría que sé escribir el mock. Aquí se cuentan los
# `exec` de verdad.


@pytest.fixture
def tmux_contador(
    _binario_prohibido: Path,
    _servidor_de_pruebas: ServidorDePruebas,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Como `tmux_aislado`, pero anotando cada invocación de tmux.

    Devuelve un objeto con `.invocaciones()` (la lista de subcomandos en
    orden) y `.contar(sub)`. No usa la fixture `tmux_aislado` para no
    contaminar la cuenta con el canario que aquella crea para verificar el
    aislamiento: el test quiere contar SUS llamadas y ninguna más.

    El aislamiento se hereda igual, porque este wrapper delega en el mismo
    wrapper con `-L` propio.
    """
    servidor = _servidor_de_pruebas
    registro = tmp_path / "invocaciones.log"
    contador = tmp_path / "tmux-contador"
    contador.write_text(
        "#!/bin/sh\n"
        # Solo el primer argumento: es el subcomando, que es lo que se cuenta.
        f'echo "$1" >> {shlex.quote(str(registro))}\n'
        f'exec {shlex.quote(str(servidor.wrapper))} "$@"\n'
    )
    contador.chmod(0o755)
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", str(contador))
    monkeypatch.setattr(config, "TMUX_BINARY", str(contador))

    class Contador:
        wrapper = contador

        def invocaciones(self) -> list[str]:
            if not registro.is_file():
                return []
            return registro.read_text().split()

        def contar(self, sub: str) -> int:
            return self.invocaciones().count(sub)

        def limpiar(self) -> None:
            registro.write_text("")

    yield Contador()

    servidor.apagar()


@sin_tmux
def test_diez_listados_lanzan_un_start_server_y_diez_list_sessions(
    tmux_contador,
) -> None:
    """El criterio de la historia, contado y no supuesto.

    Antes: 10 llamadas = 10 `start-server` + 10 `list-sessions` = 20 procesos.
    Ahora: 1 + 10 = 11. La cuenta de `list-sessions` tiene que seguir siendo
    10: el objetivo es no relanzar el servidor, **no** cachear el listado.
    """
    for _ in range(10):
        tmux_service.list_sessions()

    assert tmux_contador.contar("start-server") == 1, (
        f"se lanzó start-server {tmux_contador.contar('start-server')} veces; "
        "el arranque del servidor es una vez por proceso, no por listado"
    )
    assert tmux_contador.contar("list-sessions") == 10, (
        "el listado tiene que seguir siendo fresco: esto no es una caché"
    )
    assert len(tmux_contador.invocaciones()) == 11


@sin_tmux
def test_varios_hilos_a_la_vez_tampoco_lanzan_dos_start_server(
    tmux_contador,
) -> None:
    """El flag sin lock no vale: los endpoints corren en un threadpool.

    Sin el lock (o sin la doble comprobación dentro), varios hilos pasan a la
    vez por el `if _server_started` en frío y lanzan un `start-server` cada
    uno, que es justo el proceso de más que esta historia viene a quitar.
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: tmux_service.list_sessions(), range(8)))

    assert tmux_contador.contar("start-server") == 1, (
        f"{tmux_contador.contar('start-server')} start-server con 8 hilos: "
        "el flag no está protegido por el lock"
    )
    assert tmux_contador.contar("list-sessions") == 8


@sin_tmux
def test_si_el_servidor_muere_por_debajo_el_panel_se_recupera(
    tmux_contador,
) -> None:
    """El riesgo de recordar algo: que deje de ser verdad.

    El usuario hace `tmux kill-server` con el panel abierto. El flag sigue
    diciendo "ya está arrancado", y aun así el panel tiene que seguir
    funcionando: listar da la lista vacía (que es la verdad) y crear una
    sesión vuelve a levantar el servidor.

    Lo que este test **no** exige es un `start-server` de rescate, y no por
    dejadez. `exit-empty` viene `on` por defecto en tmux: un servidor sin
    sesiones se apaga solo, así que relanzarlo aquí sería gastar un proceso
    para levantar algo que muere en el acto. Quien de verdad levanta el
    servidor es el `new-session` de las líneas de abajo, que es como se
    recuperaba el panel también antes de esta historia.
    """
    tmux_service.create_session(nombre())
    assert len(tmux_service.list_sessions()) == 1

    # El usuario mata su servidor de tmux con el panel abierto.
    subprocess.run(
        [str(tmux_contador.wrapper), "kill-server"], capture_output=True, timeout=10
    )
    tmux_contador.limpiar()

    # Listar no puede lanzar: la lista vacía es la respuesta correcta.
    assert tmux_service.list_sessions() == []
    assert tmux_contador.contar("start-server") == 0, (
        "se relanzó el servidor al ver 'no server running', que es también la "
        "respuesta normal cuando no hay sesiones: eso devuelve el gasto de "
        "dos procesos por sondeo que esta historia viene a quitar"
    )

    # Y el panel vuelve a funcionar sin reiniciar nada.
    creada = nombre()
    assert tmux_service.create_session(creada) is True
    assert [s.name for s in tmux_service.list_sessions()] == [creada]


@sin_tmux
def test_un_panel_sin_sesiones_tampoco_relanza_el_servidor_en_cada_sondeo(
    tmux_contador,
) -> None:
    """El caso que hacía inútil la primera versión de este arreglo.

    Un panel recién arrancado no tiene sesiones, y sin sesiones tmux no
    mantiene servidor (`exit-empty on`): los diez sondeos ven "no server
    running". Si el módulo tomara eso por "se ha muerto, hay que relanzarlo",
    volveríamos a dos procesos por sondeo justo en el estado más común al
    empezar el día. Diez listados, once procesos, y ni uno más.
    """
    for _ in range(10):
        assert tmux_service.list_sessions() == []

    assert tmux_contador.contar("start-server") == 1
    assert tmux_contador.contar("list-sessions") == 10


@sin_tmux
def test_un_arranque_fallido_no_marca_el_flag_y_se_reintenta(
    _binario_prohibido: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """El criterio con más riesgo de toda la historia.

    Marcar el flag antes de saber si funcionó deja el panel muerto hasta el
    próximo reinicio del backend por un fallo que a lo mejor duró un segundo.
    Aquí `start-server` falla dos veces y funciona a la tercera: si el flag se
    marcara igualmente, la tercera llamada no lo reintentaría.
    """
    intentos = tmp_path / "intentos"
    intentos.write_text("")
    guion = tmp_path / "tmux-que-falla-al-principio"
    guion.write_text(
        "#!/bin/sh\n"
        f'echo x >> {shlex.quote(str(intentos))}\n'
        f'n=$(wc -l < {shlex.quote(str(intentos))})\n'
        # Las dos primeras invocaciones fallan; de la tercera en adelante, ok.
        '[ "$n" -le 2 ] && { echo "fallo transitorio" >&2; exit 1; }\n'
        "exit 0\n"
    )
    guion.chmod(0o755)
    monkeypatch.setattr(tmux_service, "TMUX_BINARY", str(guion))

    assert tmux_service._ensure_tmux_server() is True
    assert tmux_service._server_started is False, (
        "el flag se marcó con un start-server que devolvió error: un fallo "
        "transitorio dejaría el panel sin servidor hasta reiniciar el backend"
    )

    assert tmux_service._ensure_tmux_server() is True
    assert tmux_service._server_started is False

    # Tercera: esta sí funciona, y ahora sí se recuerda.
    assert tmux_service._ensure_tmux_server() is True
    assert tmux_service._server_started is True

    # Y a partir de aquí ya no se vuelve a lanzar.
    antes = intentos.stat().st_size
    assert tmux_service._ensure_tmux_server() is False
    assert intentos.stat().st_size == antes
