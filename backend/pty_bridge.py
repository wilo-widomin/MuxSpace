"""Puente PTY <-> WebSocket para servir terminales de tmux con xterm.js propio.

Sustituye al frontend embebido de ttyd (una caja negra que impedía copiar al
portapapeles dentro del iframe). Aquí abrimos un pseudo-terminal que ejecuta
`tmux attach -t <sesión>` y transmitimos los bytes en ambos sentidos por
WebSocket. El cliente (nuestro componente xterm.js) controla la selección y la
copia con `navigator.clipboard`, así que el problema de copiado desaparece.

Protocolo WebSocket:
  - cliente -> servidor  (frame BINARIO): bytes de entrada del teclado (stdin).
  - cliente -> servidor  (frame TEXTO):   JSON de control, p. ej.
        {"type": "resize", "cols": 120, "rows": 40}
        {"type": "scroll", "lines": 3}      (positivo = hacia el historial)
        {"type": "scroll-to", "position": 120}
        {"type": "scroll-query"}
        {"type": "scroll-exit"}
        {"type": "search", "text": "error", "direction": "up"}
  - servidor -> cliente  (frame BINARIO): bytes de salida del terminal (stdout).
  - servidor -> cliente  (frame TEXTO):   JSON de estado,
        {"type": "scroll-state", "position": …, "history": …, "height": …}
        {"type": "search-result", "matches": …}
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import shutil
import signal
import struct
import subprocess
import termios
import time

from fastapi import WebSocket, WebSocketDisconnect

import config
import logs

_log = logs.obtener(__name__)

# Tamaño de un PTY cuando no se puede saber el de la ventana. Es el clásico
# 80x24: solo se usa si tmux no responde, y el navegador lo corrige enseguida.
_TAMANO_POR_DEFECTO = (24, 80)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Ajusta el tamaño del PTY (filas/columnas) para que tmux redibuje bien."""
    rows = max(1, min(rows, 1000))
    cols = max(1, min(cols, 1000))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _prepare_session(name: str) -> None:
    """Opciones de tmux (best-effort) para que el portapapeles funcione fino.

    - `allow-passthrough on`: deja pasar secuencias DCS envueltas (algunas apps
      modernas envían así el OSC 52). tmux 3.3+ lo bloquea por defecto.
    - `set-clipboard on`: permite que las apps dentro de tmux fijen el
      portapapeles vía OSC 52, que nuestro cliente xterm.js sabe interpretar.
    Si tmux es viejo y no conoce alguna opción, se ignora el error.
    """
    for opt, val in (("allow-passthrough", "on"), ("set-clipboard", "on")):
        try:
            subprocess.run(  # noqa: S603 — argv, nunca shell
                [config.TMUX_BINARY, "set-option", "-t", name, opt, val],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except Exception:
            # Un tmux viejo puede no conocer la opción, y eso NO debe impedir
            # abrir la terminal: es el caso que describe el docstring. A
            # DEBUG y no a WARNING porque en esos tmux pasaría en CADA sesión,
            # y un aviso que sale siempre deja de leerse.
            _log.debug("no se pudo fijar %s en la sesión %s", opt, name,
                       exc_info=True)


# ---------------------------------------------------------------------------
# Scroll del historial
#
# tmux corre en la PANTALLA ALTERNATIVA del terminal, así que el scrollback de
# xterm.js está siempre vacío: el historial vive dentro de tmux y solo se
# alcanza desde su copy-mode. Por eso la rueda del ratón no movía nada y no
# había barra que enseñar.
#
# La otra salida sería `set -g mouse on`, y está descartada a conciencia: con
# el ratón capturado por tmux, el arrastre deja de generar una selección de
# xterm y se rompe el copiar-al-seleccionar del cliente (fue un bug real de
# este panel). Así que el ratón sigue en off y es el cliente quien traduce el
# gesto: manda `scroll`/`scroll-to` por este canal y aquí lo convertimos en
# órdenes de copy-mode.
# ---------------------------------------------------------------------------

# `scroll_position` viene vacío cuando el panel NO está en copy-mode.
#
# `alternate_on` es la pieza que reparte el trabajo: vale 1 cuando el programa
# del panel ocupa SU propia pantalla alternativa (Claude Code, vim, less…).
# Esos programas no dejan nada en el historial de tmux —se repintan encima— y
# se scrollean ellos solos, así que ahí el cliente no debe interceptar la
# rueda: se la deja a xterm.js, que la traduce a flechas para el programa.
_FORMATO_SCROLL = (
    "#{pane_in_mode}\t#{scroll_position}\t#{history_size}\t#{pane_height}"
    "\t#{alternate_on}"
)

# Tope de líneas por gesto: un `deltaY` disparatado del navegador no debe
# convertirse en un `send-keys -N` gigante que tmux tarde en procesar.
_MAX_LINEAS_SCROLL = 500


async def _tmux(*args: str) -> str:
    """Ejecuta `tmux <args>` sin bloquear el bucle de eventos. '' si falla.

    Se usa para las órdenes de copy-mode, que ocurren en cada gesto de rueda:
    un `subprocess.run` aquí congelaría TODAS las demás terminales durante la
    llamada.
    """
    try:
        proc = await asyncio.create_subprocess_exec(  # noqa: S603 — argv, sin shell
            config.TMUX_BINARY,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return ""
    try:
        salida, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except (asyncio.TimeoutError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return ""
    return salida.decode(errors="replace").strip()


async def _estado_scroll(name: str) -> dict[str, int]:
    """Posición actual en el historial del panel activo de la sesión."""
    crudo = await _tmux("display-message", "-p", "-t", name, "-F", _FORMATO_SCROLL)
    partes = crudo.split("\t")

    def _entero(indice: int) -> int:
        try:
            return int(partes[indice])
        except (IndexError, ValueError):
            return 0

    return {
        "inMode": _entero(0),
        # 0 = pegado abajo (en vivo); N = N líneas subidas hacia el historial.
        "position": _entero(1),
        "history": _entero(2),
        "height": _entero(3),
        "alternate": _entero(4),
    }


async def _salir_copy_mode(name: str, estado: dict[str, int] | None = None) -> None:
    """Vuelve al final del historial (el cliente lo pide al teclear)."""
    if estado is None:
        estado = await _estado_scroll(name)
    if estado["inMode"]:
        await _tmux("send-keys", "-t", name, "-X", "cancel")


async def _scroll(name: str, lineas: int) -> None:
    """Mueve el historial `lineas` (positivo = hacia atrás)."""
    lineas = max(-_MAX_LINEAS_SCROLL, min(lineas, _MAX_LINEAS_SCROLL))
    if lineas == 0:
        return
    estado = await _estado_scroll(name)
    if not estado["inMode"]:
        # Ya estamos abajo del todo: bajar más no tiene sentido, y entrar en
        # copy-mode para nada dejaría el panel en un modo que el usuario no ha
        # pedido.
        if lineas < 0:
            return
        if not estado["history"]:
            return
        # Programa en pantalla alternativa: su copy-mode enseñaría la pantalla
        # del programa, no historial. El scroll ahí lo hace el propio programa.
        if estado["alternate"]:
            return
        # `-e` hace que tmux salga solo del copy-mode al llegar abajo, así el
        # panel vuelve a estar "en vivo" sin que nadie tenga que cancelarlo.
        await _tmux("copy-mode", "-e", "-t", name)
    orden = "scroll-up" if lineas > 0 else "scroll-down"
    await _tmux("send-keys", "-t", name, "-X", "-N", str(abs(lineas)), orden)


# Metacaracteres de una expresión regular POSIX extendida, que es lo que
# entiende la búsqueda de tmux. El usuario escribe texto literal, no un
# patrón: sin escaparlos, buscar `total (1)` o `a[0]` no encontraría nada.
_META_REGEX = set(r".[]()*+?{}|^$\\")


def _patron_sin_mayusculas(texto: str) -> str:
    """Convierte texto literal en un patrón que ignora mayúsculas.

    tmux usa *smartcase*: si el patrón lleva una sola mayúscula, exige
    coincidencia exacta, así que buscar `Error` no encontraba `ERROR`. No hay
    opción de tmux para desactivarlo, pero sí se puede pedir explícitamente
    las dos formas de cada letra: `Error` -> `[Ee][Rr][Rr][Oo][Rr]`.
    """
    partes = []
    for ch in texto:
        if ch.isalpha() and ch.lower() != ch.upper():
            partes.append(f"[{ch.lower()}{ch.upper()}]")
        elif ch in _META_REGEX:
            partes.append("\\" + ch)
        else:
            partes.append(ch)
    return "".join(partes)


async def _contar_coincidencias(name: str, texto: str) -> int:
    """Cuántas veces aparece `texto` en TODO el historial del panel.

    tmux no dice si encontró algo: cuando no hay coincidencia se queda quieto
    y en silencio, que desde fuera es idéntico a "sí la encontró". Contarlas
    aquí es lo que permite decir «3 coincidencias» o «sin resultados».
    """
    volcado = await _tmux("capture-pane", "-p", "-S", "-", "-t", name)
    if not volcado:
        return 0
    return volcado.lower().count(texto.lower())


async def _buscar(name: str, texto: str, hacia_atras: bool = True) -> int:
    """Busca `texto` en el historial del panel. Devuelve cuántas veces está.

    Se apoya en la búsqueda del copy-mode de tmux, no en la de xterm.js: el
    buffer del cliente está vacío (pantalla alternativa), así que ahí no hay
    nada que buscar. tmux además resalta las coincidencias por su cuenta
    (`copy-mode-match-style`), o sea que el resaltado sale gratis.

    Cada llamada repite la búsqueda desde donde quedó el cursor, así que
    pulsar Enter varias veces va saltando de coincidencia en coincidencia.
    """
    texto = texto[:200]  # una aguja más larga que esto no busca a nadie
    if not texto:
        return 0
    estado = await _estado_scroll(name)
    if not estado["inMode"]:
        if estado["alternate"] or not estado["history"]:
            return 0
        await _tmux("copy-mode", "-e", "-t", name)
    orden = "search-backward" if hacia_atras else "search-forward"
    await _tmux("send-keys", "-t", name, "-X", orden, _patron_sin_mayusculas(texto))
    return await _contar_coincidencias(name, texto)


async def _scroll_a(name: str, posicion: int) -> None:
    """Salta a una posición absoluta del historial (arrastre de la barra)."""
    estado = await _estado_scroll(name)
    historia = estado["history"]
    posicion = max(0, min(posicion, historia))
    if posicion == 0:
        await _salir_copy_mode(name, estado)
        return
    if not estado["inMode"] and (not historia or estado["alternate"]):
        return

    # No hay una orden de "ir a la posición N" del historial, así que se ancla
    # arriba del todo (el `-N` de más se recorta solo) y se baja lo que falte.
    #
    # Las tres órdenes van ENCADENADAS en una sola invocación (el `;` es un
    # argumento más para tmux). Arrastrando la barra esto se ejecuta muchas
    # veces por segundo: con una llamada por orden eran tres `fork`+`exec`
    # por cada píxel de arrastre, y se notaba.
    ordenes: list[str] = []
    if not estado["inMode"]:
        ordenes += ["copy-mode", "-e", "-t", name, ";"]
    ordenes += ["send-keys", "-t", name, "-X", "-N", str(historia + 1), "scroll-up"]
    bajar = historia - posicion
    if bajar > 0:
        ordenes += [
            ";", "send-keys", "-t", name, "-X", "-N", str(bajar), "scroll-down",
        ]
    await _tmux(*ordenes)


def _lineas_de_estado(valor: str) -> int:
    """Cuántas filas ocupa la barra de estado de tmux. `on` es una."""
    if valor in ("", "off", "0"):
        return 0
    if valor == "on":
        return 1
    try:
        return max(0, min(5, int(valor)))
    except ValueError:
        return 1


def _tamano_para_engancharse(name: str) -> tuple[int, int]:
    """Filas y columnas que debe tener el PTY para no cambiarle nada a tmux.

    El PTY del attach arrancaba fijo a 80x24. Con `window-size latest` —el
    valor por defecto de tmux—, la ventana se encoge a ese tamaño en cuanto el
    cliente se engancha y se estira otra vez ~300 ms después, cuando llega el
    tamaño real del navegador. Son dos SIGWINCH seguidos, y el shell reimprime
    su prompt en cada uno: de ahí las líneas repetidas que aparecen al abrir
    una terminal (medido en vivo: 80x24 -> 215x63 en 260 ms).

    El tamaño que se busca es el del CLIENTE, que no es el de la ventana: la
    barra de estado se lleva sus filas, así que un cliente de 63 filas deja una
    ventana de 62. Si ya hay alguien enganchado se copia su tamaño tal cual; si
    no, se le suman a la ventana las filas de la barra.
    """
    try:
        salida = subprocess.run(  # noqa: S603 — argv, nunca shell
            [
                config.TMUX_BINARY, "display-message", "-p", "-t", name,
                "#{window_height} #{window_width} #{client_height} #{status}",
            ],
            capture_output=True, text=True, timeout=2, check=False,
        ).stdout.split()
        alto_ventana, ancho = int(salida[0]), int(salida[1])
        alto_cliente = int(salida[2]) if salida[2].isdigit() else 0
        estado = salida[3] if len(salida) > 3 else "on"
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return _TAMANO_POR_DEFECTO
    filas = alto_cliente or (alto_ventana + _lineas_de_estado(estado))
    # Una ventana de 0 filas no existe, y un valor absurdo no se propaga.
    if not (1 <= filas <= 1000 and 1 <= ancho <= 1000):
        return _TAMANO_POR_DEFECTO
    return filas, ancho


def _spawn_attach(name: str) -> tuple[int, int, tuple[int, int]]:
    """Lanza `tmux attach -t <name>` sobre un PTY nuevo.

    Devuelve `(pid, fd, (filas, columnas))`: el tamaño va de vuelta para que
    el padre pueda repetir el ioctl con el MISMO valor que fijó el hijo.

    Aquí vivía un `subprocess.Popen(..., preexec_fn=lambda: os.login_tty(slave))`
    (hallazgo S11). El problema: los endpoints síncronos de FastAPI corren en un
    threadpool, así que el `fork` ocurre en un proceso **multihilo**, y entre el
    `fork` y el `exec` el hijo solo puede llamar a funciones async-signal-safe.
    `preexec_fn` ejecuta Python arbitrario justo ahí: si otro hilo tenía cogido
    un lock del intérprete o del asignador en el instante del fork, el hijo se
    bloquea intentando cogerlo y **nunca llega al exec**. Probabilidad baja,
    síntoma horrible: una terminal que no abre, en blanco, sin ningún error.

    `os.forkpty()` hace el `openpty` + `fork` + `login_tty` dentro de una sola
    llamada de la libc, así que esa ventana desaparece. Lo que queda del lado
    del hijo se ha reducido a lo mínimo:

    - `argv`, `env` y el `winsize` empaquetado se construyen **antes** del fork.
      Todo lo que se calcule después es trabajo que hacer en la ventana
      peligrosa, y esta función existe precisamente para no tener trabajo ahí.
    - `os.execve` con la ruta ya resuelta, no `execvpe`: la búsqueda por `PATH`
      es un bucle con concatenación de cadenas —o sea, asignación de memoria—
      en el peor sitio posible para hacerla.
    - El fallo del hijo sale por `os._exit`, **nunca** por una excepción. Una
      excepción que se propagara dejaría dos intérpretes ejecutando el mismo
      código, cada uno con su copia del `finally` de `bridge`.
    """
    binario = shutil.which(config.TMUX_BINARY) or config.TMUX_BINARY
    argv = [binario, "-u", "attach", "-t", name]
    env = {**os.environ, "TERM": "xterm-256color"}
    # Tamaño de arranque del PTY: el que deja la ventana como está, para que
    # engancharse no la encoja y la estire (ver `_tamano_para_engancharse`).
    # El cliente (xterm.js) manda el tamaño real del tile en cuanto abre el
    # WebSocket; este es solo el valor inicial.
    #
    # Se fija DESDE EL HIJO y no solo desde el padre porque `os.forkpty()` no
    # acepta un `winsize` (la libc sí, la envoltura de Python no) y deja el PTY
    # a 0x0. El padre lo ajusta también, justo después del fork, pero eso es
    # una carrera con el `exec`: medido, el padre gana siempre, y "siempre" en
    # una carrera medida no es una garantía. Con esta línea, tmux no puede
    # arrancar viendo 0x0 ni aunque el padre llegue tarde.
    filas, columnas = _tamano_para_engancharse(name)
    winsize = struct.pack("HHHH", filas, columnas, 0, 0)

    pid, fd = os.forkpty()
    if pid == 0:
        # ---- HIJO. A partir de aquí, lo mínimo y sin excepciones. ----
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)
            # noqa: S606 — argv explícito y ruta ya resuelta, nunca shell:
            # es justamente lo contrario de lo que avisa la regla.
            os.execve(binario, argv, env)  # noqa: S606
        except BaseException:  # noqa: S110, BLE001 — ver el docstring: aquí no
            # puede salir NADA hacia arriba, y el `pass` cae en el `os._exit`
            # de la línea siguiente. `BaseException` y no `Exception` porque un
            # KeyboardInterrupt entregado en este instante dejaría al hijo vivo
            # ejecutando el resto del backend.
            pass
        # Solo se llega si el exec falló. 127 es la convención del shell para
        # "orden no encontrada", y es lo que verá el padre en el waitpid.
        os._exit(127)
    # ---- PADRE ----
    return pid, fd, (filas, columnas)


async def bridge(websocket: WebSocket, name: str) -> None:
    """Transmite bytes entre el WebSocket y un `tmux attach` sobre un PTY."""
    loop = asyncio.get_running_loop()

    try:
        pid, master, tamano = _spawn_attach(name)
    except OSError:
        # Ni PTYs libres ni descriptores: no hay terminal que servir.
        await websocket.close(code=1011)
        return

    # También desde el padre, para el caso —imposible de descartar del todo—
    # de que el hijo no llegara a ejecutar su ioctl.
    try:
        _set_winsize(master, *tamano)
    except OSError:  # pragma: no cover — el fd acaba de crearse
        pass
    os.set_blocking(master, False)

    out_q: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _on_readable() -> None:
        try:
            data = os.read(master, 65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""  # PTY cerrado (tmux se separó / murió)
        out_q.put_nowait(data if data else None)

    loop.add_reader(master, _on_readable)

    async def _pump_out() -> None:
        while True:
            data = await out_q.get()
            if data is None:  # EOF del PTY
                break
            await websocket.send_bytes(data)

    out_task = asyncio.create_task(_pump_out())

    # La recepción del WebSocket compite con el fin del PTY, y no se comprueba
    # `out_task.done()` al principio de cada vuelta como antes. Motivo: con
    # `Popen`, un `tmux` inexistente daba `FileNotFoundError` en el PADRE y
    # `bridge` cerraba y volvía en el acto. Con `forkpty` ese fallo ocurre en
    # el hijo (`os._exit(127)`), así que aquí solo se ve como un PTY que
    # termina; comprobándolo únicamente después de un `receive` que nunca
    # llega, el puente se quedaba colgado para siempre. De paso, matar la
    # sesión de tmux cierra ahora la terminal sin esperar a que el usuario
    # pulse una tecla.
    recepcion: asyncio.Task | None = None
    # Si el usuario está mirando el historial (copy-mode), la próxima tecla
    # tiene que devolverlo al final. Se guarda aquí para no preguntárselo a
    # tmux en cada pulsación.
    en_historial = False
    # Por qué acabó el puente. Se registra al salir porque una terminal que se
    # reconecta sola —visto en vivo: clientes que se van y vuelven 300 ms
    # después sin que nadie toque nada— se diagnostica distinto según quién
    # cuelgue: el navegador o el `tmux attach`.
    motivo = "desconocido"
    try:
        while True:
            recepcion = asyncio.ensure_future(websocket.receive())
            terminadas, _ = await asyncio.wait(
                {recepcion, out_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if out_task in terminadas:
                motivo = "el PTY terminó (tmux se separó o murió)"
                break
            msg = recepcion.result()
            if msg.get("type") == "websocket.disconnect":
                motivo = f"el cliente cerró el WebSocket (code={msg.get('code')})"
                break
            data = msg.get("bytes")
            if data is not None:
                # Teclear mientras se está mirando el historial vuelve al
                # final, como haría cualquier terminal: si no, las teclas se
                # las comería el copy-mode de tmux y el usuario no entendería
                # por qué "no escribe". Se hace ANTES de inyectar los bytes, y
                # el orden se conserva porque este bucle procesa los mensajes
                # de uno en uno.
                if en_historial:
                    await _salir_copy_mode(name)
                    en_historial = False
                os.write(master, data)
                continue
            text = msg.get("text")
            if text is not None:
                try:
                    ctl = json.loads(text)
                except ValueError:
                    continue
                tipo = ctl.get("type")
                if tipo == "resize":
                    try:
                        _set_winsize(master, int(ctl["rows"]), int(ctl["cols"]))
                    except Exception:
                        # Un resize con valores basura del cliente se descarta:
                        # tirar la terminal entera por un mensaje mal formado
                        # sería peor. Se registra porque, si empieza a pasar,
                        # es un bug del frontend y aquí es donde se ve.
                        _log.debug("resize descartado: %r", text, exc_info=True)
                elif tipo in (
                    "scroll", "scroll-to", "scroll-query", "scroll-exit", "search"
                ):
                    try:
                        if tipo == "scroll":
                            await _scroll(name, int(ctl.get("lines", 0)))
                        elif tipo == "scroll-to":
                            await _scroll_a(name, int(ctl.get("position", 0)))
                        elif tipo == "search":
                            coincidencias = await _buscar(
                                name,
                                str(ctl.get("text", "")),
                                hacia_atras=ctl.get("direction", "up") != "down",
                            )
                            await websocket.send_text(json.dumps({
                                "type": "search-result",
                                "matches": coincidencias,
                            }))
                        elif tipo == "scroll-exit":
                            await _salir_copy_mode(name)
                        estado = await _estado_scroll(name)
                        en_historial = bool(estado["inMode"])
                        await websocket.send_text(
                            json.dumps({"type": "scroll-state", **estado})
                        )
                    except (ValueError, TypeError):
                        # Mismo criterio que el resize: un mensaje mal formado
                        # no tumba la terminal.
                        _log.debug("scroll descartado: %r", text, exc_info=True)
    except WebSocketDisconnect:
        motivo = "el cliente se desconectó (WebSocketDisconnect)"
    except Exception:
        # El puente muere con la conexión: cualquier error aquí significa que
        # el WebSocket o el PTY ya no están, y el `finally` de abajo es quien
        # cierra los descriptores pase lo que pase. Lo que sí se hace ahora es
        # decir POR QUÉ murió: era el "queda pendiente de Q6" de US-021.
        _log.info("el puente de %s terminó por un error", name, exc_info=True)
    finally:
        loop.remove_reader(master)
        if recepcion is not None:
            # Si se sale por el PTY, queda un `receive()` en vuelo esperando
            # bytes que ya no interesan: sin cancelarlo, asyncio se queja de
            # una tarea destruida y la conexión no se suelta hasta el GC.
            recepcion.cancel()
        _log.info("puente cerrado para %r: %s", name, motivo)
        out_task.cancel()
        try:
            os.close(master)
        except OSError:
            pass
        await _terminar_hijo(pid)


async def _terminar_hijo(pid: int, espera: float = 2.0) -> None:
    """SIGTERM al `tmux attach` y **cosecharlo siempre** con `waitpid`.

    Terminar el attach solo separa a este cliente: la sesión de tmux, y lo que
    corre dentro, siguen vivas. Eso no cambia respecto de antes.

    Lo que sí cambia es de quién es la responsabilidad. Con `subprocess.Popen`
    el `waitpid` lo hacía la biblioteca por su cuenta; con `os.forkpty()` el
    hijo es nuestro y nadie va a recogerlo. Sin esto, cada terminal que se
    cierra deja un **zombi** en la tabla de procesos hasta que muera el
    backend, y un panel se abre y se cierra decenas de veces al día.
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # ya había muerto (un `kill-session` sobre la sesión, p. ej.)

    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        try:
            recogido, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return  # ya no es hijo nuestro: alguien lo recogió antes
        if recogido == pid:
            return
        # `asyncio.sleep` y no `time.sleep`: esto corre en el bucle de eventos,
        # y dormirlo dos segundos congelaría TODAS las demás terminales.
        await asyncio.sleep(0.01)

    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except (ProcessLookupError, ChildProcessError, OSError):
        pass
