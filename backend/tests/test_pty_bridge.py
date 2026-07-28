"""El puente PTY: `os.forkpty()` en lugar de `preexec_fn` (US-021, hallazgo S11).

## Qué se prueba y por qué así

El riesgo de este cambio no es que no funcione: es que funcione **el 99 % de
las veces**. El modo de fallo que se quiere descartar —un hijo que se queda
bloqueado entre el `fork` y el `exec` porque otro hilo tenía un lock cogido—
no da error, da una terminal en blanco. Un test que abra una terminal y
compruebe que va no distingue eso de que vaya siempre.

Por eso aquí hay tres cosas, y no una:

1. **Eco de verdad**, por el WebSocket, contra tmux: se escribe y se lee lo
   escrito. Es el "funciona".
2. **Repetición y paralelismo**: abrir y cerrar muchas terminales seguidas, y
   varias a la vez, con el backend haciendo trabajo en otros hilos. Es lo
   único que puede cazar un fallo probabilista.
3. **Contabilidad de recursos**: descriptores abiertos y procesos zombis antes
   y después. Un puente que funciona pero deja un fd o un hijo sin cosechar
   por cada terminal cerrada tumba el panel a las pocas horas de uso.

## El aislamiento

Igual que en `test_tmux_service.py`: un wrapper ejecutable con su propio
socket (`-L`), de modo que nada de lo que pase aquí pueda alcanzar el
servidor de tmux del usuario. La diferencia es que aquí el binario lo lee
`config.TMUX_BINARY` (el puente lo consulta por atributo en cada llamada), no
una copia hecha al importar.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

import config
import pty_bridge

TMUX_REAL = shutil.which("tmux")

sin_tmux = pytest.mark.skipif(
    TMUX_REAL is None,
    reason="tmux no está instalado en esta máquina (falta en el PATH)",
)


# ----------------------------------------------------------------------
# Andamiaje
# ----------------------------------------------------------------------


class _WebSocketFalso:
    """Lo mínimo de la interfaz de Starlette que usa `bridge`.

    No es un mock del puente: es el **otro extremo del cable**. `bridge` habla
    con él exactamente igual que con el WebSocket real —`receive`,
    `send_bytes`, `close`— y lo que se comprueba son los bytes que salen del
    PTY de verdad. Montar un servidor ASGI completo aquí añadiría el
    handshake, la autenticación y el bucle de uvicorn a un test cuyo objeto es
    el `fork`.
    """

    def __init__(self) -> None:
        self.entrada: asyncio.Queue[dict] = asyncio.Queue()
        self.salida = bytearray()
        self.cerrado_con: int | None = None
        self.recibido = asyncio.Event()

    # --- lo que usa `bridge` ---
    async def receive(self) -> dict:
        return await self.entrada.get()

    async def send_bytes(self, data: bytes) -> None:
        self.salida += data
        self.recibido.set()

    async def close(self, code: int = 1000) -> None:
        self.cerrado_con = code

    # --- lo que usa el test ---
    def teclear(self, data: bytes) -> None:
        self.entrada.put_nowait({"type": "websocket.receive", "bytes": data})

    def redimensionar(self, cols: int, rows: int) -> None:
        self.entrada.put_nowait(
            {
                "type": "websocket.receive",
                "text": f'{{"type":"resize","cols":{cols},"rows":{rows}}}',
            }
        )

    def colgar(self) -> None:
        self.entrada.put_nowait({"type": "websocket.disconnect"})

    async def esperar_algo(self, timeout: float = 10.0) -> bool:
        """Espera a que el PTY escupa cualquier cosa.

        Es la señal de que el hijo llegó al `exec` y tmux está pintando: no se
        puede esperar un texto concreto porque el prompt del usuario que corra
        la suite es el que sea.
        """
        try:
            await asyncio.wait_for(self.recibido.wait(), timeout)
        except asyncio.TimeoutError:
            return False
        return bool(self.salida)

    async def esperar_texto(self, texto: str, timeout: float = 10.0) -> bool:
        """Espera a que `texto` aparezca en lo que ha salido del PTY."""
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if texto.encode() in bytes(self.salida):
                return True
            await asyncio.sleep(0.02)
        return False


@pytest.fixture(scope="module")
def servidor_tmux(tmp_path_factory: pytest.TempPathFactory):
    """Un servidor de tmux propio, con su socket, que muere con el módulo."""
    if TMUX_REAL is None:
        pytest.skip("tmux no está instalado")

    base = tmp_path_factory.mktemp("pty")
    socket = f"muxspace-pty-{uuid.uuid4().hex[:8]}"
    wrapper = base / "tmux"
    wrapper.write_text(
        "#!/bin/sh\n"
        # La suite puede estar corriendo DENTRO de una sesión de tmux del
        # usuario, y esa variable apunta a su socket.
        "unset TMUX\n"
        f"TMUX_TMPDIR={shlex.quote(str(base))}\n"
        "export TMUX_TMPDIR\n"
        f'exec {shlex.quote(TMUX_REAL)} -L {shlex.quote(socket)} "$@"\n'
    )
    wrapper.chmod(0o755)

    ruta_socket = base / f"tmux-{os.getuid()}" / socket
    assert len(str(ruta_socket).encode()) < 100, (
        f"la ruta del socket es demasiado larga ({ruta_socket}): un socket "
        "unix no pasa de ~108 bytes y tmux fallaría por algo que no tiene "
        "nada que ver con lo que se prueba"
    )

    yield wrapper

    subprocess.run([str(wrapper), "kill-server"], capture_output=True, timeout=10)


@pytest.fixture
def tmux_aislado(servidor_tmux: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Apunta el puente al servidor de pruebas y lo verifica de verdad.

    La comprobación no es "el atributo vale lo que le he puesto" (tautología):
    se crea una sesión por el wrapper y se comprueba que **no** aparece en el
    servidor por defecto, que es donde el usuario tiene su trabajo.
    """
    monkeypatch.setattr(config, "TMUX_BINARY", str(servidor_tmux))

    canario = f"muxspace-canario-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [str(servidor_tmux), "new-session", "-d", "-s", canario],
        capture_output=True,
        timeout=10,
        check=True,
    )
    del_usuario = subprocess.run(
        [TMUX_REAL, "list-sessions", "-F", "#S"], capture_output=True, text=True
    ).stdout
    if canario in del_usuario:
        subprocess.run([TMUX_REAL, "kill-session", "-t", canario], capture_output=True)
        pytest.fail(
            "AISLAMIENTO ROTO: la sesión de prueba ha aparecido en el servidor "
            "de tmux del usuario. Ningún test de este archivo puede correr así."
        )
    subprocess.run([str(servidor_tmux), "kill-session", "-t", canario],
                   capture_output=True)
    return servidor_tmux


def crear_sesion(wrapper: Path, nombre: str) -> None:
    subprocess.run(
        [str(wrapper), "new-session", "-d", "-s", nombre],
        capture_output=True,
        timeout=10,
        check=True,
    )


def fds_abiertos() -> set[str]:
    """Los descriptores del proceso actual, por su destino."""
    propio = Path(f"/proc/{os.getpid()}/fd")
    abiertos = set()
    for entrada in propio.iterdir():
        try:
            abiertos.add(f"{entrada.name}->{os.readlink(entrada)}")
        except OSError:
            continue
    return abiertos


def zombis() -> list[int]:
    """PIDs de hijos nuestros en estado zombi."""
    muertos = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            estado = (proc / "stat").read_text()
            campos = estado.rsplit(")", 1)[1].split()
            if campos[0] == "Z" and int(campos[1]) == os.getpid():
                muertos.append(int(proc.name))
        except (OSError, IndexError, ValueError):
            continue
    return muertos


# ----------------------------------------------------------------------
# Que funcione
# ----------------------------------------------------------------------


@sin_tmux
def test_se_abre_la_terminal_y_el_eco_llega_de_vuelta(tmux_aislado: Path) -> None:
    """El "funciona": se escribe en la terminal y vuelve lo escrito.

    Contra tmux de verdad y por el mismo camino que usa el panel. Es el test
    que se cae si el `exec` del hijo no llega a ocurrir.
    """
    async def _correr() -> None:
        nombre = f"eco-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()

        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        assert await ws.esperar_texto("$", timeout=10) or ws.salida, (
            "el PTY no ha escupido nada: el hijo no llegó a ejecutar tmux"
        )

        marca = f"hola-{uuid.uuid4().hex[:6]}"
        ws.teclear(f"echo {marca}\n".encode())

        assert await ws.esperar_texto(marca), (
            f"no ha vuelto el eco de {marca!r}; salida: {bytes(ws.salida)[-400:]!r}"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_el_redimensionado_llega_al_pty_y_tmux_lo_ve(
    tmux_aislado: Path,
) -> None:
    """`TIOCSWINSZ` sigue llegando: es lo que rompía quitar el `login_tty`.

    Se pregunta el tamaño a **tmux**, no al PTY. Comprobarlo con un
    `TIOCGWINSZ` sobre el master solo diría que el ioctl del test funcionó;
    lo que importa es que el cliente de tmux recibiera su SIGWINCH y se
    redibujara, que es la razón de que este código necesite una terminal
    controladora.
    """
    async def _correr() -> None:
        nombre = f"resize-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()

        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)  # que el attach se establezca
        ws.redimensionar(cols=132, rows=43)

        def ancho_segun_tmux() -> str:
            return subprocess.run(
                [str(tmux_aislado), "display-message", "-p", "-t", nombre,
                 "#{client_width}x#{client_height}"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()

        limite = time.monotonic() + 10
        visto = ""
        while time.monotonic() < limite:
            visto = ancho_segun_tmux()
            if visto == "132x43":
                break
            await asyncio.sleep(0.05)

        assert visto == "132x43", (
            f"tmux sigue viendo {visto!r}: el resize no llegó al cliente, que es "
            "el fallo que produce una terminal clavada en 80x24"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_matar_la_sesion_de_tmux_cierra_la_terminal(
    tmux_aislado: Path,
) -> None:
    """Como antes: si la sesión muere, el puente se entera y termina solo."""
    async def _correr() -> None:
        nombre = f"kill-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()

        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        subprocess.run([str(tmux_aislado), "kill-session", "-t", nombre],
                       capture_output=True, timeout=10)

        # Sin tocar el WebSocket: el puente tiene que terminar por su cuenta al
        # ver el EOF del PTY. Antes de US-021 esto se quedaba colgado hasta que
        # el usuario pulsara una tecla, porque el fin del PTY solo se miraba
        # después de un `receive`.
        await asyncio.wait_for(puente, timeout=10)
        assert ws.cerrado_con is None, (
            "el puente cerró el WebSocket por su cuenta: eso lo decide quien "
            "lo llama, no este código"
        )

    asyncio.run(_correr())


@sin_tmux
def test_si_el_binario_no_existe_el_hijo_muere_y_no_se_queda_colgado(
    monkeypatch: pytest.MonkeyPatch, servidor_tmux: Path
) -> None:
    """El camino del `os._exit(127)`.

    Con `Popen` esto era un `FileNotFoundError` en el padre. Con `forkpty` el
    `exec` falla **dentro del hijo**, y si ese hijo no se muriera con
    `os._exit` habría dos intérpretes corriendo el backend. El puente tiene
    que terminar, no quedarse esperando bytes que no van a llegar.
    """
    async def _correr() -> None:
        monkeypatch.setattr(config, "TMUX_BINARY", "/no/existe/tmux-de-mentira")
        ws = _WebSocketFalso()

        await asyncio.wait_for(pty_bridge.bridge(ws, "da-igual"), timeout=10)

        assert zombis() == [], "el hijo del exec fallido quedó sin cosechar"

    asyncio.run(_correr())


# ----------------------------------------------------------------------
# Que funcione SIEMPRE: repetición, paralelismo y contabilidad
# ----------------------------------------------------------------------


@sin_tmux
def test_veinte_terminales_seguidas_no_dejan_fds_ni_zombis(
    tmux_aislado: Path,
) -> None:
    """Abrir y cerrar en serie, mirando los recursos antes y después.

    Un puente que funciona pero se deja un descriptor por terminal tumba el
    panel al llegar al límite de fds del proceso, y el síntoma —"no abre
    ninguna terminal más"— no apunta a este código.
    """
    async def _correr() -> None:
        nombre = f"serie-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)

        fds_antes = fds_abiertos()

        for i in range(20):
            ws = _WebSocketFalso()
            puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
            assert await ws.esperar_algo(), f"vuelta {i}: el PTY no habló"
            ws.colgar()
            await asyncio.wait_for(puente, timeout=10)

        fds_despues = fds_abiertos()
        assert fds_despues == fds_antes, (
            f"fds filtrados tras 20 terminales: "
            f"{sorted(fds_despues - fds_antes)}"
        )
        assert zombis() == [], "hijos sin cosechar tras 20 terminales"

    asyncio.run(_correr())


@sin_tmux
def test_diez_terminales_a_la_vez_abren_todas(tmux_aislado: Path) -> None:
    """El paralelismo, que es donde vivía el riesgo del `fork` multihilo.

    Diez puentes concurrentes: si alguno se quedara bloqueado entre el `fork`
    y el `exec`, su PTY no diría nada y su `esperar_texto` se agotaría. El
    test afirma que hablaron **los diez**, no "alguno".
    """
    async def _correr() -> None:
        nombre = f"paralelo-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)

        fds_antes = fds_abiertos()
        websockets = [_WebSocketFalso() for _ in range(10)]
        puentes = [
            asyncio.create_task(pty_bridge.bridge(ws, nombre)) for ws in websockets
        ]

        hablaron = await asyncio.gather(
            *(ws.esperar_algo() for ws in websockets)
        )
        assert all(hablaron), (
            f"{hablaron.count(False)} de 10 terminales no llegaron a arrancar: es "
            "el síntoma exacto del hijo bloqueado entre el fork y el exec"
        )

        for ws in websockets:
            ws.colgar()
        await asyncio.wait_for(asyncio.gather(*puentes), timeout=20)

        assert fds_abiertos() == fds_antes, "fds filtrados con 10 puentes en paralelo"
        assert zombis() == [], "hijos sin cosechar con 10 puentes en paralelo"

    asyncio.run(_correr())
