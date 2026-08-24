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

## El puente de continuidad

Medir solo con el foco del panel deja fuera el trabajo que se hace en OTRA
ventana sin dejar el proyecto: mirar un token en el servidor, tocar los
secretos del repositorio, leer una documentación. En cuanto el panel pierde
el foco deja de latir, así que ese rato desaparece entero.

Por eso, **al leer**, se rellenan los huecos cortos entre dos ranuras del
mismo espacio: si a las 16:00 y a las 16:08 estabas en el mismo proyecto y en
medio ningún otro espacio reclamó nada, esos ocho minutos fueron ese
proyecto. La vuelta es la prueba — sin ranura posterior no hay puente, así
que irse y no volver no puede inflar nada.

Se hace derivando y no escribiendo ranuras a propósito: cambiar el tope
recalcula todo el histórico al instante, y una ranura de puente escrita en la
base ya no se distinguiría de una medida.

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

import config
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

# Cómo se supo que esa ranura era trabajo:
#   'auto'   — medido: el panel tenía el foco y hubo entrada del usuario.
#   'manual' — declarado: el usuario encendió el cronómetro para trabajar
#              FUERA del panel (probar la app que construye, por ejemplo).
#   'bridge' — inferido: nadie lo latió, lo rellena el puente de continuidad
#              al leer (ver el docstring del módulo). NUNCA se guarda en la
#              base; solo existe en la salida de `bloques()` y `resumen()`.
# Se guardan juntos pero se pueden mirar por separado, y eso no es un adorno:
# si algún día el total no cuadra con lo que uno recuerda, lo primero que hay
# que poder saber es qué parte se midió, qué parte se declaró y qué parte se
# dedujo.
FUENTES = ("auto", "manual")

# Tope por defecto del puente, en minutos. Sale de la distribución real de
# huecos: por debajo de 10 min son saltos de ventana encadenados dentro de una
# misma sesión de trabajo, y los huecos que de verdad son ausencias (comer,
# irse) están todos por encima de la media hora. Entre 10 y 20 el total apenas
# se mueve, así que el valor no es delicado.
PUENTE_MINUTOS = config.WORKLOG_BRIDGE_MIN


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
        _migrar(con)
        yield con
        con.commit()
    finally:
        con.close()


def _migrar(con: sqlite3.Connection) -> None:
    """Añade columnas nuevas a una base que ya existe.

    El registro es el único dato del panel que **no se puede reconstruir**:
    borrarlo y empezar de cero cuesta el histórico entero. Así que las
    columnas se añaden en sitio, con su valor por defecto para lo ya escrito.
    """
    columnas = {fila[1] for fila in con.execute("PRAGMA table_info(work_slots)")}
    if "source" not in columnas:
        # Lo anterior a esta columna se midió con foco y entrada: 'auto'.
        con.execute(
            "ALTER TABLE work_slots ADD COLUMN source TEXT NOT NULL DEFAULT 'auto'"
        )


def slot_de(instante: float) -> int:
    """Ranura a la que pertenece un instante (epoch en segundos)."""
    return int(instante) // SLOT_SECONDS * SLOT_SECONDS


def registrar(
    space: str,
    session: str | None = None,
    command: str | None = None,
    ahora: float | None = None,
    source: str = "auto",
) -> int:
    """Anota la ranura actual como trabajada. Devuelve su inicio.

    La marca de tiempo la pone el SERVIDOR, nunca el cliente: un navegador con
    la hora mal metería horas en el día equivocado y no habría forma de
    detectarlo después.

    Si la ranura ya estaba tomada no se toca (`INSERT OR IGNORE`): la primera
    pestaña que la reclama se la queda, y las demás no pueden inflar el total.
    """
    inicio = slot_de(time.time() if ahora is None else ahora)
    if source not in FUENTES:
        source = "auto"
    with _conexion() as con:
        con.execute(
            "INSERT OR IGNORE INTO work_slots"
            " (slot_start, space, session, command, source) VALUES (?, ?, ?, ?, ?)",
            (inicio, space, session, command, source),
        )
    return inicio


def _rango(desde: float | None, hasta: float | None) -> tuple[int, int]:
    inicio = 0 if desde is None else slot_de(desde)
    fin = 2**62 if hasta is None else slot_de(hasta) + SLOT_SECONDS
    return inicio, fin


# Hueco máximo, en ranuras, que NO parte un bloque de trabajo. Uno de más
# porque un latido puede perderse (pestaña que tarda, red que falla) y eso no
# significa que el usuario se levantara: partir el bloque ahí llenaría la
# lista de tramos falsos de dos minutos.
_TOLERANCIA_RANURAS = 2


def _puente_segundos(minutos: int | None) -> int:
    """Tope del puente en segundos, acotado. `None` = el de la configuración."""
    if minutos is None:
        minutos = PUENTE_MINUTOS
    return max(0, min(int(minutos), 60)) * 60


def _ranuras(
    desde: float | None,
    hasta: float | None,
    puente_min: int | None,
) -> list[tuple[int, str, str | None, str | None, str]]:
    """Ranuras del periodo, ya con los huecos cortos rellenados.

    Es el único sitio donde se aplica el puente: `bloques()` y `resumen()`
    parten de aquí, así que no pueden dar totales distintos por descuido.

    El recorrido es GLOBAL, sin filtrar por espacio, y de ahí sale gratis la
    condición que hace honesto el puente: como `slot_start` es clave primaria,
    dos ranuras consecutivas de esta lista no pueden tener nada en medio. Si
    entre las dos hubo otro espacio, ya no son consecutivas y no se puentea.
    Filtrar en SQL por espacio rompería justo eso.

    Las ranuras inferidas heredan sesión y comando de la anterior: es la mejor
    prueba que hay de qué se estaba mirando, y sin ella el tiempo "con agente
    delante" encogería como fracción del total cada vez que se subiera el
    puente.
    """
    inicio, fin = _rango(desde, hasta)
    with _conexion() as con:
        filas = list(
            con.execute(
                "SELECT slot_start, space, session, command, source FROM work_slots"
                " WHERE slot_start >= ? AND slot_start < ? ORDER BY slot_start",
                (inicio, fin),
            )
        )

    tope = _puente_segundos(puente_min)
    if not tope:
        return filas

    salida: list[tuple] = []
    for fila in filas:
        if salida:
            slot_previo, espacio_previo, sesion, comando, _ = salida[-1]
            hueco = fila[0] - (slot_previo + SLOT_SECONDS)
            if espacio_previo == fila[1] and 0 < hueco <= tope:
                for slot in range(slot_previo + SLOT_SECONDS, fila[0], SLOT_SECONDS):
                    salida.append((slot, espacio_previo, sesion, comando, "bridge"))
        salida.append(fila)
    return salida


def bloques(
    desde: float | None = None,
    hasta: float | None = None,
    space: str | None = None,
    puente_min: int | None = None,
) -> list[dict]:
    """Tramos de trabajo continuos: cuándo empezó y cuándo acabó cada uno.

    Las ranuras no se guardan como tramos a propósito (ver el docstring del
    módulo: un tramo abierto sobrevive mal a un portátil que se cierra), así
    que los tramos se **derivan** al leer: ranuras consecutivas del mismo
    espacio, permitiendo un hueco de `_TOLERANCIA_RANURAS`.

    El filtro por espacio se aplica DESPUÉS del puente, no en la consulta: un
    espacio filtrado en SQL parecería tener ranuras contiguas donde en realidad
    hubo otro proyecto en medio (ver `_ranuras`).

    El fin de un bloque es el fin de su última ranura, no su principio: una
    ranura representa el tiempo que cubre.
    """
    filas = [
        fila for fila in _ranuras(desde, hasta, puente_min)
        if not space or fila[1] == space
    ]

    salida: list[dict] = []
    actual: dict | None = None
    for slot, espacio, sesion, comando, fuente in filas:
        continua = (
            actual is not None
            and actual["space"] == espacio
            and slot - actual["_ultima"] <= SLOT_SECONDS * _TOLERANCIA_RANURAS
        )
        if not continua:
            actual = {
                "space": espacio,
                "start": slot,
                "end": slot + SLOT_SECONDS,
                "seconds": 0,
                "claude_seconds": 0,
                # Cuánto del tramo es tiempo declarado a mano (ver FUENTES).
                "manual_seconds": 0,
                # Y cuánto lo puso el puente de continuidad: tiempo inferido,
                # no medido. Separado para que se pueda auditar de un vistazo
                # cuánto del tramo es deducción.
                "bridge_seconds": 0,
                # Qué se estuvo mirando en el tramo, en orden de aparición.
                "sessions": [],
                # Y con qué se estuvo trabajando ('claude', 'zsh', 'vim'…).
                # Es lo que la sesión no dice: en un panel donde cada sesión
                # se llama como su espacio, el nombre repite la primera
                # columna y el programa es la información nueva.
                "commands": [],
                "_ultima": slot,
            }
            salida.append(actual)
        actual["_ultima"] = slot
        actual["end"] = slot + SLOT_SECONDS
        actual["seconds"] += SLOT_SECONDS
        if comando == "claude":
            actual["claude_seconds"] += SLOT_SECONDS
        if fuente == "manual":
            actual["manual_seconds"] += SLOT_SECONDS
        if fuente == "bridge":
            actual["bridge_seconds"] += SLOT_SECONDS
        if sesion and sesion not in actual["sessions"]:
            actual["sessions"].append(sesion)
        if comando and comando not in actual["commands"]:
            actual["commands"].append(comando)

    for bloque in salida:
        bloque.pop("_ultima", None)
    return salida


def _dia_local(slot: int, tz_offset_min: int) -> str:
    """Día LOCAL (aaaa-mm-dd) al que pertenece una ranura UTC.

    El desfase llega en minutos desde el cliente porque el servidor no tiene
    por qué correr en la zona del usuario, y agrupar por UTC partiría la
    jornada a las 02:00.
    """
    return time.strftime("%Y-%m-%d", time.gmtime(slot + tz_offset_min * 60))


def resumen(
    desde: float | None = None,
    hasta: float | None = None,
    tz_offset_min: int = 0,
    puente_min: int | None = None,
) -> dict:
    """Totales del periodo: general, por espacio y por día local.

    Todo sale de contar ranuras y multiplicar por su duración. No hay ningún
    acumulado que mantener.

    Se agrega en Python y no en SQL porque las ranuras del puente no existen
    en la base: un `GROUP BY` sobre la tabla y un puente aplicado aparte darían
    dos totales distintos para la misma pregunta.
    """
    filas = _ranuras(desde, hasta, puente_min)

    por_espacio: dict[str, dict] = {}
    por_dia: dict[str, int] = {}
    por_dia_espacio: dict[tuple[str, str], int] = {}
    total = manual = puenteado = 0

    for slot, espacio, _sesion, comando, fuente in filas:
        acumulado = por_espacio.setdefault(
            espacio,
            {
                "space": espacio,
                "seconds": 0,
                # Horas con un agente delante, dentro del total del espacio.
                "claude_seconds": 0,
                # Y cuánto de ese total es tiempo declarado, no medido...
                "manual_seconds": 0,
                # ...o inferido por el puente de continuidad.
                "bridge_seconds": 0,
            },
        )
        acumulado["seconds"] += SLOT_SECONDS
        if comando == "claude":
            acumulado["claude_seconds"] += SLOT_SECONDS
        if fuente == "manual":
            acumulado["manual_seconds"] += SLOT_SECONDS
            manual += SLOT_SECONDS
        if fuente == "bridge":
            acumulado["bridge_seconds"] += SLOT_SECONDS
            puenteado += SLOT_SECONDS
        dia = _dia_local(slot, tz_offset_min)
        por_dia[dia] = por_dia.get(dia, 0) + SLOT_SECONDS
        clave = (dia, espacio)
        por_dia_espacio[clave] = por_dia_espacio.get(clave, 0) + SLOT_SECONDS
        total += SLOT_SECONDS

    with _conexion() as con:
        primera = con.execute("SELECT MIN(slot_start) FROM work_slots").fetchone()[0]

    return {
        "slot_seconds": SLOT_SECONDS,
        "total_seconds": total,
        # Del total, cuánto se declaró a mano en vez de medirse...
        "manual_seconds": manual,
        # ...y cuánto lo rellenó el puente de continuidad, con el tope que se
        # usó. Van juntos a propósito: el número sin el tope que lo produjo no
        # se puede interpretar.
        "bridge_seconds": puenteado,
        "bridge_minutes": _puente_segundos(puente_min) // 60,
        "by_space": sorted(
            por_espacio.values(), key=lambda e: e["seconds"], reverse=True
        ),
        "by_day": [
            {"day": dia, "seconds": segundos}
            for dia, segundos in sorted(por_dia.items())
        ],
        "by_day_space": [
            {"day": dia, "space": espacio, "seconds": segundos}
            for (dia, espacio), segundos in sorted(por_dia_espacio.items())
        ],
        # Desde cuándo hay datos: sin esto, un total pequeño no se distingue de
        # "el registro se activó ayer".
        "since": primera,
    }
