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
import struct
import subprocess
import termios

from fastapi import WebSocket, WebSocketDisconnect

import config


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
            subprocess.run(
                [config.TMUX_BINARY, "set-option", "-t", name, opt, val],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except Exception:
            pass


async def bridge(websocket: WebSocket, name: str) -> None:
    """Transmite bytes entre el WebSocket y un `tmux attach` sobre un PTY."""
    loop = asyncio.get_running_loop()

    master, slave = os.openpty()
    # Tamaño inicial del PTY antes de lanzar tmux. El cliente (xterm.js) envía
    # el tamaño real del tile en cuanto abre el WebSocket; esto es solo el
    # valor de arranque hasta ese primer resize.
    _set_winsize(master, 24, 80)
    env = {
        **os.environ,
        "TERM": "xterm-256color",
    }
    try:
        proc = subprocess.Popen(
            [config.TMUX_BINARY, "-u", "attach", "-t", name],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            # `login_tty` hace setsid + TIOCSCTTY: convierte el PTY esclavo en
            # la TERMINAL CONTROLADORA de tmux. Sin esto, los resize en caliente
            # (TIOCSWINSZ sobre el master) no generan SIGWINCH para tmux y la
            # terminal se queda clavada en el tamaño inicial (80x24): "no se
            # adapta al tamaño disponible". Reemplaza a start_new_session=True
            # (login_tty ya hace el setsid).
            preexec_fn=lambda: os.login_tty(slave),
            env=env,
            close_fds=True,
        )
    except FileNotFoundError:
        os.close(master)
        os.close(slave)
        await websocket.close(code=1011)
        return
    # El proceso hijo ya tiene su copia del esclavo; nosotros no lo usamos.
    os.close(slave)
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

    try:
        while True:
            # Si el PTY terminó, cerramos la vista.
            if out_task.done():
                break
            msg = await websocket.receive()
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
                        pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        loop.remove_reader(master)
        out_task.cancel()
        try:
            os.close(master)
        except OSError:
            pass
        # Terminar el `tmux attach` solo separa a este cliente; la sesión de
        # tmux (y lo que corre dentro) sigue viva.
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
