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
  - servidor -> cliente  (frame BINARIO): bytes de salida del terminal (stdout).
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


def _spawn_attach(name: str) -> tuple[int, int]:
    """Lanza `tmux attach -t <name>` sobre un PTY nuevo. Devuelve `(pid, fd)`.

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
    # Tamaño de arranque del PTY. El cliente (xterm.js) manda el tamaño real
    # del tile en cuanto abre el WebSocket; esto es solo el valor inicial.
    #
    # Se fija DESDE EL HIJO y no solo desde el padre porque `os.forkpty()` no
    # acepta un `winsize` (la libc sí, la envoltura de Python no) y deja el PTY
    # a 0x0. El padre lo ajusta también, justo después del fork, pero eso es
    # una carrera con el `exec`: medido, el padre gana siempre, y "siempre" en
    # una carrera medida no es una garantía. Con esta línea, tmux no puede
    # arrancar viendo 0x0 ni aunque el padre llegue tarde.
    winsize = struct.pack("HHHH", 24, 80, 0, 0)

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
    return pid, fd


async def bridge(websocket: WebSocket, name: str) -> None:
    """Transmite bytes entre el WebSocket y un `tmux attach` sobre un PTY."""
    loop = asyncio.get_running_loop()

    try:
        pid, master = _spawn_attach(name)
    except OSError:
        # Ni PTYs libres ni descriptores: no hay terminal que servir.
        await websocket.close(code=1011)
        return

    # También desde el padre, para el caso —imposible de descartar del todo—
    # de que el hijo no llegara a ejecutar su ioctl.
    try:
        _set_winsize(master, 24, 80)
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
    try:
        while True:
            recepcion = asyncio.ensure_future(websocket.receive())
            terminadas, _ = await asyncio.wait(
                {recepcion, out_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if out_task in terminadas:
                break
            msg = recepcion.result()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data is not None:
                os.write(master, data)
                continue
            text = msg.get("text")
            if text is not None:
                try:
                    ctl = json.loads(text)
                except ValueError:
                    continue
                if ctl.get("type") == "resize":
                    try:
                        _set_winsize(master, int(ctl["rows"]), int(ctl["cols"]))
                    except Exception:
                        # Un resize con valores basura del cliente se descarta:
                        # tirar la terminal entera por un mensaje mal formado
                        # sería peor. Se registra porque, si empieza a pasar,
                        # es un bug del frontend y aquí es donde se ve.
                        _log.debug("resize descartado: %r", text, exc_info=True)
    except WebSocketDisconnect:
        pass
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
