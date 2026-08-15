"""Registro del tiempo de trabajo por espacio, en ranuras de tiempo.

## Qué mide y qué NO mide

Mide **horas del usuario**, no horas transcurridas. La forma de trabajar que
hay que medir es: abrir un espacio por proyecto, lanzar un agente y, mientras
construye, irse a otro espacio. El tiempo que un proyecto está *abierto* no
tiene nada que ver con el tiempo que se le dedica.

Por eso **la salida del terminal NO es actividad**. Cuando el agente trabaja,
el WebSocket del PTY escupe texto durante minutos con el usuario en otra
pestaña; si esos bytes contaran, el registro mediría exactamente las horas que
no se trabaja y el dato quedaría invertido. Solo cuenta entrada del usuario
(teclado, ratón, scroll), y eso lo decide el cliente: aquí no llega ni un byte
del puente PTY.

## Ranuras, no tramos ni contadores

El cliente manda un **latido** mientras está activo. El servidor redondea el
instante a una ranura de `SLOT_SECONDS` y la guarda **una sola vez**: la
ranura es la clave primaria.

Eso resuelve tres problemas de golpe:

- **Cierres sucios.** Con eventos de inicio/fin, cerrar el portátil deja un
  tramo abierto que o se pierde entero o cuenta ocho horas. Con ranuras, lo
  máximo que se pierde es una.
- **Doble conteo.** Dos pestañas, dos navegadores o la tableta y el portátil a
  la vez colapsan en la misma ranura. El invariante «la suma de todos los
  espacios nunca supera el tiempo transcurrido» no es algo que un test vigile:
  es algo que el esquema **impide**.
- **Desincronización.** No se guardan acumulados. El total se deriva contando
  ranuras al leer; un contador que hay que mantener a mano se desincroniza y
  nadie se entera.

## Precisión

El objetivo es ±15 %: distinguir un proyecto de 40 h de uno de 100 h, no saber
si fueron 58 o 64. Hay dos sesgos conocidos y **se compensan**: leer sin tocar
nada durante más del tiempo de inactividad resta, y seguir contando hasta ese
mismo tiempo tras la última tecla suma. Afinar uno solo de los dos empeora el
dato.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import datafiles
import logs

_log = logs.obtener(__name__)

# Duración de una ranura. Es también el intervalo del latido del cliente: si
# el cliente latiera más rápido, solo escribiría en la misma ranura; si latiera
# más lento, dejaría huecos que no se pueden recuperar.
SLOT_SECONDS = 30

_DB_PATH = Path(__file__).resolve().parent / "data" / "worklog.db"

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS work_slots (
    -- Inicio de la ranura en segundos epoch (UTC), múltiplo de SLOT_SECONDS.
    -- PRIMARY KEY a propósito: una ranura de reloj solo puede trabajarse una
    -- vez, y eso hace estructural el invariante de no superar el tiempo real.
    slot_start INTEGER PRIMARY KEY,
    space      TEXT NOT NULL,
    -- Sesión de tmux mirada en esa ranura y programa que corría en su panel
    -- ('claude', 'zsh'...). Permite separar horas con un agente delante de
    -- horas de terminal a secas. Pueden ser NULL: el espacio puede estar
    -- vacío o la sesión haber muerto.
    session    TEXT,
    command    TEXT
);
CREATE INDEX IF NOT EXISTS idx_work_slots_space ON work_slots(space);
"""


def _ruta() -> Path:
    return _DB_PATH


@contextmanager
def _conexion() -> Iterator[sqlite3.Connection]:
    ruta = _ruta()
    datafiles.ensure_dir(ruta.parent)
    nuevo = not ruta.exists()
    con = sqlite3.connect(ruta, timeout=5)
    try:
        if nuevo:
            # Los datos son del usuario y de nadie más, igual que el resto de
            # `backend/data/` (ver datafiles.py).
            try:
                os.chmod(ruta, datafiles.FILE_MODE)
            except OSError:
                pass
        con.executescript(_ESQUEMA)
        yield con
        con.commit()
    finally:
        con.close()


def slot_de(instante: float) -> int:
    """Ranura a la que pertenece un instante (epoch en segundos)."""
    return int(instante) // SLOT_SECONDS * SLOT_SECONDS


def registrar(
    space: str,
    session: str | None = None,
    command: str | None = None,
    ahora: float | None = None,
) -> int:
    """Anota la ranura actual como trabajada. Devuelve su inicio.

    La marca de tiempo la pone el SERVIDOR, nunca el cliente: un navegador con
    la hora mal metería horas en el día equivocado y no habría forma de
    detectarlo después.

    Si la ranura ya estaba tomada no se toca (`INSERT OR IGNORE`): la primera
    pestaña que la reclama se la queda, y las demás no pueden inflar el total.
    """
    inicio = slot_de(time.time() if ahora is None else ahora)
    with _conexion() as con:
        con.execute(
            "INSERT OR IGNORE INTO work_slots (slot_start, space, session, command)"
            " VALUES (?, ?, ?, ?)",
            (inicio, space, session, command),
        )
    return inicio


def _rango(desde: float | None, hasta: float | None) -> tuple[int, int]:
    inicio = 0 if desde is None else slot_de(desde)
    fin = 2**62 if hasta is None else slot_de(hasta) + SLOT_SECONDS
    return inicio, fin


# Expresión SQL que convierte una ranura UTC en su día LOCAL. El desfase llega
# en minutos desde el cliente porque el servidor no tiene por qué correr en la
# zona del usuario, y agrupar por UTC partiría la jornada a las 02:00.
_DIA_LOCAL = "date((slot_start + ? * 60), 'unixepoch')"


def resumen(
    desde: float | None = None,
    hasta: float | None = None,
    tz_offset_min: int = 0,
) -> dict:
    """Totales del periodo: general, por espacio y por día local.

    Todo sale de contar ranuras y multiplicar por su duración. No hay ningún
    acumulado que mantener.
    """
    inicio, fin = _rango(desde, hasta)
    with _conexion() as con:
        por_espacio = [
            {
                "space": fila[0],
                "seconds": fila[1] * SLOT_SECONDS,
                # Horas con un agente delante, dentro del total del espacio.
                "claude_seconds": fila[2] * SLOT_SECONDS,
            }
            for fila in con.execute(
                "SELECT space, COUNT(*),"
                "       SUM(CASE WHEN command = 'claude' THEN 1 ELSE 0 END)"
                "  FROM work_slots WHERE slot_start >= ? AND slot_start < ?"
                " GROUP BY space ORDER BY COUNT(*) DESC",
                (inicio, fin),
            )
        ]
        por_dia = [
            {"day": fila[0], "seconds": fila[1] * SLOT_SECONDS}
            for fila in con.execute(
                f"SELECT {_DIA_LOCAL} AS dia, COUNT(*)"
                "  FROM work_slots WHERE slot_start >= ? AND slot_start < ?"
                " GROUP BY dia ORDER BY dia",
                (tz_offset_min, inicio, fin),
            )
        ]
        por_dia_espacio = [
            {"day": fila[0], "space": fila[1], "seconds": fila[2] * SLOT_SECONDS}
            for fila in con.execute(
                f"SELECT {_DIA_LOCAL} AS dia, space, COUNT(*)"
                "  FROM work_slots WHERE slot_start >= ? AND slot_start < ?"
                " GROUP BY dia, space ORDER BY dia",
                (tz_offset_min, inicio, fin),
            )
        ]
        total = con.execute(
            "SELECT COUNT(*) FROM work_slots WHERE slot_start >= ? AND slot_start < ?",
            (inicio, fin),
        ).fetchone()[0]
        primera = con.execute("SELECT MIN(slot_start) FROM work_slots").fetchone()[0]

    return {
        "slot_seconds": SLOT_SECONDS,
        "total_seconds": total * SLOT_SECONDS,
        "by_space": por_espacio,
        "by_day": por_dia,
        "by_day_space": por_dia_espacio,
        # Desde cuándo hay datos: sin esto, un total pequeño no se distingue de
        # "el registro se activó ayer".
        "since": primera,
    }
