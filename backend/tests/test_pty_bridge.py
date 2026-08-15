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
import fcntl
import json
import os
import shlex
import shutil
import signal
import struct
import subprocess
import termios
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
        self.control: list[dict] = []
        self.cerrado_con: int | None = None
        self.recibido = asyncio.Event()

    # --- lo que usa `bridge` ---
    async def receive(self) -> dict:
        return await self.entrada.get()

    async def send_bytes(self, data: bytes) -> None:
        self.salida += data
        self.recibido.set()

    async def send_text(self, data: str) -> None:
        # El canal de control del backend hacia el cliente (hoy solo el estado
        # del scroll). Se guarda aparte de `salida` porque confundir estado con
        # bytes del terminal es justo lo que el protocolo evita.
        self.control.append(json.loads(data))

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

    def pedir(self, msg: dict) -> None:
        """Manda un mensaje de control cualquiera (scroll, scroll-to, …)."""
        self.entrada.put_nowait({"type": "websocket.receive", "text": json.dumps(msg)})

    async def esperar_estado(self, timeout: float = 10.0) -> dict:
        """Espera al siguiente `scroll-state` y lo devuelve.

        Se filtra por tipo a propósito: una búsqueda manda además un
        `search-result`, y quedarse con "el último mensaje" hacía que el test
        leyera el que no era según cuál llegara primero.
        """
        cuantos = len(self.control)
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            for msg in self.control[cuantos:]:
                if msg.get("type") == "scroll-state":
                    return msg
            await asyncio.sleep(0.02)
        raise AssertionError("el backend no mandó ningún scroll-state")

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


def sembrar_historial(wrapper: Path, nombre: str, lineas: int) -> None:
    """Llena el scrollback de la sesión con `lineas` líneas numeradas."""
    subprocess.run(
        [str(wrapper), "send-keys", "-t", nombre,
         f"seq 1 {lineas}", "Enter"],
        capture_output=True, timeout=10, check=True,
    )


def historial_de(wrapper: Path, nombre: str) -> int:
    salida = subprocess.run(
        [str(wrapper), "display-message", "-p", "-t", nombre, "#{history_size}"],
        capture_output=True, text=True, timeout=10,
    ).stdout.strip()
    return int(salida or 0)


@sin_tmux
def test_la_rueda_sube_por_el_historial_de_tmux(tmux_aislado: Path) -> None:
    """El gesto de rueda mueve el historial DE TMUX y el cliente se entera.

    Es la prueba de que el scroll no depende del scrollback de xterm.js: ese
    buffer está siempre vacío porque tmux ocupa la pantalla alternativa. Lo
    que se comprueba es que un `scroll` por el canal de control acaba en un
    copy-mode desplazado, y que la posición vuelve al cliente para que pueda
    pintar la barra.
    """
    async def _correr() -> None:
        nombre = f"scroll-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()
        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        sembrar_historial(tmux_aislado, nombre, 300)
        limite = time.monotonic() + 10
        while historial_de(tmux_aislado, nombre) < 100 and time.monotonic() < limite:
            await asyncio.sleep(0.05)

        ws.pedir({"type": "scroll", "lines": 40})
        estado = await ws.esperar_estado()
        assert estado["type"] == "scroll-state"
        assert estado["history"] >= 100, "no se sembró historial suficiente"
        assert estado["position"] > 0, (
            "la rueda no movió el historial de tmux: sin esto el usuario no "
            "puede subir a ver lo que ya ha pasado"
        )
        assert estado["height"] > 0

        arriba = estado["position"]
        ws.pedir({"type": "scroll", "lines": -10})
        estado = await ws.esperar_estado()
        assert estado["position"] < arriba, "bajar con la rueda no hizo nada"

        # Saltar a una posición absoluta: es lo que hace arrastrar la barra.
        ws.pedir({"type": "scroll-to", "position": estado["history"]})
        estado = await ws.esperar_estado()
        assert estado["position"] == estado["history"], (
            "arrastrar la barra hasta arriba no llegó al principio del historial"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_la_busqueda_salta_a_la_coincidencia_del_historial(
    tmux_aislado: Path,
) -> None:
    """El ⌘F busca en el historial de TMUX y deja el panel sobre el resultado.

    Es lo que no puede hacer el buscador de xterm.js: su buffer está vacío
    porque tmux ocupa la pantalla alternativa. Se comprueba con una aguja
    empujada lejos del final: si la posición no se mueve, la búsqueda no ha
    saltado a ningún sitio.
    """
    async def _correr() -> None:
        nombre = f"buscar-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()
        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        aguja = f"AGUJA{uuid.uuid4().hex[:6].upper()}"
        subprocess.run(
            [str(tmux_aislado), "send-keys", "-t", nombre, f"echo {aguja}", "Enter"],
            capture_output=True, timeout=10, check=True,
        )
        # Empujar la aguja bien arriba: si estuviera en pantalla, saltar a ella
        # no movería la posición y el test no probaría nada.
        sembrar_historial(tmux_aislado, nombre, 300)
        limite = time.monotonic() + 10
        while historial_de(tmux_aislado, nombre) < 300 and time.monotonic() < limite:
            await asyncio.sleep(0.05)

        ws.pedir({"type": "search", "text": aguja, "direction": "up"})
        estado = await ws.esperar_estado()
        assert estado["position"] > 0, (
            "la búsqueda no llevó el panel a la coincidencia: con la aguja 300 "
            "líneas más arriba, quedarse en el final es no haber buscado"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_la_busqueda_ignora_mayusculas_y_dice_cuantas_hay(
    tmux_aislado: Path,
) -> None:
    """Dos defectos que hacían parecer rota una búsqueda que funcionaba.

    - tmux es *smartcase*: una aguja con mayúsculas exigía coincidencia
      exacta, así que `MIAGUJA` no encontraba `MiAguja`.
    - Y cuando no hay coincidencia se queda quieto **y en silencio**, que
      desde fuera es idéntico a haberla encontrado.
    """
    async def _correr() -> None:
        nombre = f"caso-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()
        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        sufijo = uuid.uuid4().hex[:6]
        aguja = f"MiAguja{sufijo}"
        subprocess.run(
            [str(tmux_aislado), "send-keys", "-t", nombre, f"echo {aguja}", "Enter"],
            capture_output=True, timeout=10, check=True,
        )
        sembrar_historial(tmux_aislado, nombre, 300)
        limite = time.monotonic() + 10
        while historial_de(tmux_aislado, nombre) < 300 and time.monotonic() < limite:
            await asyncio.sleep(0.05)

        # En MAYÚSCULAS: antes no encontraba nada.
        ws.pedir({"type": "search", "text": aguja.upper(), "direction": "up"})
        estado = await ws.esperar_estado()
        assert estado["position"] > 0, (
            "buscar en mayúsculas no encontró la aguja: el smartcase de tmux "
            "sigue mandando"
        )
        resultado = next(m for m in ws.control if m["type"] == "search-result")
        assert resultado["matches"] >= 1, "encontró la aguja pero dijo que no había"

        # Y algo que no está tiene que decirse.
        ws.pedir({"type": "search", "text": f"no-existe-{sufijo}", "direction": "up"})
        await ws.esperar_estado()
        ultimo = [m for m in ws.control if m["type"] == "search-result"][-1]
        assert ultimo["matches"] == 0, (
            "una búsqueda sin resultados no se distingue de una con ellos"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_en_pantalla_alternativa_el_scroll_se_deja_al_programa(
    tmux_aislado: Path,
) -> None:
    """Con un programa en su pantalla alternativa, el puente NO scrollea.

    Claude Code, vim o less se repintan en su propia pantalla: tmux no guarda
    ni una línea de eso, así que meter el panel en copy-mode enseñaría la
    pantalla del programa y no historial. El cliente necesita saberlo
    (`alternate`) para dejarle la rueda al programa, que es quien sí puede
    scrollear. Antes de esto, la rueda dentro de Claude dejó de funcionar.
    """
    async def _correr() -> None:
        nombre = f"alt-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()
        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        sembrar_historial(tmux_aislado, nombre, 300)
        limite = time.monotonic() + 10
        while historial_de(tmux_aislado, nombre) < 100 and time.monotonic() < limite:
            await asyncio.sleep(0.05)

        # `?1049h` es justo lo que emite un programa al tomar la pantalla
        # alternativa; no hace falta arrastrar un vim al test para reproducir
        # la condición que importa.
        subprocess.run(
            [str(tmux_aislado), "send-keys", "-t", nombre,
             r"printf '\033[?1049h'", "Enter"],
            capture_output=True, timeout=10, check=True,
        )
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            alterna = subprocess.run(
                [str(tmux_aislado), "display-message", "-p", "-t", nombre,
                 "#{alternate_on}"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if alterna == "1":
                break
            await asyncio.sleep(0.05)
        assert alterna == "1", "no se pudo poner el panel en pantalla alternativa"

        ws.pedir({"type": "scroll", "lines": 40})
        estado = await ws.esperar_estado()
        assert estado["alternate"] == 1, (
            "el cliente no se entera de que el programa manda en la pantalla, "
            "así que se quedaría con la rueda en vez de pasársela"
        )
        assert estado["position"] == 0, (
            "el puente metió el panel en copy-mode sobre una pantalla "
            "alternativa: ahí no hay historial que mirar"
        )

        ws.colgar()
        await asyncio.wait_for(puente, timeout=10)

    asyncio.run(_correr())


@sin_tmux
def test_teclear_mientras_se_mira_el_historial_vuelve_al_final(
    tmux_aislado: Path,
) -> None:
    """Escribir cancela el copy-mode, como en cualquier terminal.

    Sin esto las teclas se las come el copy-mode de tmux (y algunas hacen
    cosas raras, porque ahí son atajos), y el usuario solo ve que "la terminal
    no escribe".
    """
    async def _correr() -> None:
        nombre = f"scrollkey-{uuid.uuid4().hex[:6]}"
        crear_sesion(tmux_aislado, nombre)
        ws = _WebSocketFalso()
        puente = asyncio.create_task(pty_bridge.bridge(ws, nombre))
        await asyncio.sleep(0.5)

        sembrar_historial(tmux_aislado, nombre, 300)
        limite = time.monotonic() + 10
        while historial_de(tmux_aislado, nombre) < 100 and time.monotonic() < limite:
            await asyncio.sleep(0.05)

        ws.pedir({"type": "scroll", "lines": 40})
        estado = await ws.esperar_estado()
        assert estado["position"] > 0

        ws.teclear(b"x")
        limite = time.monotonic() + 10
        en_modo = "1"
        while time.monotonic() < limite:
            en_modo = subprocess.run(
                [str(tmux_aislado), "display-message", "-p", "-t", nombre,
                 "#{pane_in_mode}"],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if en_modo == "0":
                break
            await asyncio.sleep(0.05)
        assert en_modo == "0", (
            "el panel sigue en copy-mode tras teclear: las pulsaciones no "
            "estarían llegando al programa"
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


# ----------------------------------------------------------------------
# El hijo, mirado de cerca
# ----------------------------------------------------------------------
#
# Los dos tests de abajo se añadieron porque la verificación por mutación los
# echó de menos: romper el `winsize` del hijo y quitarle el `os._exit(127)`
# dejaba la suite entera en verde. Son dos afirmaciones que el código hace en
# sus comentarios y que nadie estaba comprobando.


def leer_winsize(fd: int) -> tuple[int, int]:
    """Filas y columnas que tiene ahora mismo el PTY."""
    crudo = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
    filas, columnas, _, _ = struct.unpack("HHHH", crudo)
    return filas, columnas


@sin_tmux
def test_el_pty_arranca_con_un_tamano_de_verdad_y_no_a_cero(
    tmux_aislado: Path,
) -> None:
    """`os.forkpty()` deja el PTY a 0x0 si nadie lo remedia.

    La envoltura de Python no acepta un `winsize` (la libc sí), así que el
    hijo lo fija él mismo antes del `exec`. Se prueba llamando a
    `_spawn_attach` en directo y NO por `bridge`, porque `bridge` lo ajusta
    también desde el padre: por ahí no se distinguiría quién de los dos hizo
    el trabajo, y el del padre es una carrera contra el `exec`.
    """
    nombre = f"winsize-{uuid.uuid4().hex[:6]}"
    crear_sesion(tmux_aislado, nombre)

    pid, fd = pty_bridge._spawn_attach(nombre)
    try:
        limite = time.monotonic() + 5
        visto = (0, 0)
        while time.monotonic() < limite:
            visto = leer_winsize(fd)
            if visto != (0, 0):
                break
            time.sleep(0.01)
        assert visto == (24, 80), (
            f"el PTY arrancó a {visto[0]}x{visto[1]}: con 0x0 tmux puede "
            "arrancar sin saber dónde pintar"
        )
    finally:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        os.close(fd)


def test_si_el_exec_falla_el_hijo_sale_con_127_y_no_sigue_vivo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El `os._exit(127)`, que es la línea más importante del hijo.

    Sin ella, el hijo vuelve de `_spawn_attach` con `pid == 0` y **sigue
    ejecutando el backend**: dos intérpretes corriendo el mismo código, cada
    uno con su copia del `finally` de `bridge`, y un `os.kill(0, SIGTERM)`
    que apunta al grupo de procesos entero. No es un detalle de limpieza.

    127 es la convención del shell para "orden no encontrada".
    """
    monkeypatch.setattr(config, "TMUX_BINARY", "/no/existe/tmux-de-mentira")

    pid, fd = pty_bridge._spawn_attach("da-igual")
    assert pid > 0, (
        "`_spawn_attach` ha devuelto pid=0: estamos en el HIJO, o sea que no "
        "murió tras fallar el exec"
    )
    try:
        limite = time.monotonic() + 5
        estado = None
        while time.monotonic() < limite:
            recogido, st = os.waitpid(pid, os.WNOHANG)
            if recogido == pid:
                estado = st
                break
            time.sleep(0.01)
        assert estado is not None, "el hijo del exec fallido no terminó"
        assert os.WIFEXITED(estado), "el hijo no salió por os._exit"
        assert os.WEXITSTATUS(estado) == 127, (
            f"el hijo salió con {os.WEXITSTATUS(estado)} en vez de 127"
        )
    finally:
        os.close(fd)
