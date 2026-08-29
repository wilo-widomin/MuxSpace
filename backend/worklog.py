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

## Dos modos de contar el día

Todo lo anterior describe el modo `measured`, y ese modo se queda corto de una
forma que no se veía hasta medirla: **3 h 25 apuntadas de una jornada real de
8 h 30**. No es un error de calibración, es el modelo — pregunta «¿tocaste
algo hace menos de tres minutos?» y con un agente construyendo la respuesta es
que no casi todo el rato.

El modo `workday` invierte la carga de la prueba: la jornada cuenta entera
entre la primera y la última señal del día. Las señales —latidos y transcripts
de Claude— dejan de decidir *si* trabajaste y pasan a decidir sobre todo *en
qué proyecto*. Ver `MODOS`.

Con una excepción, que es lo que impide que la jornada apunte de más: un hueco
sin **ninguna** señal —ni una tecla, ni una línea de agente— más largo que
`AUSENCIA_MIN` no se cuenta. Irse a comer, o dejar el panel abierto toda la
tarde, deja un rastro reconocible: nada en absoluto durante media hora. Lo que
sí es excepcional —una tarde de pizarra, una reunión con el portátil cerrado—
se reclama con un clic desde la vista de tiempos, y ese reclamo sí se guarda
(`work_claims`). Se declara lo raro, no lo normal.

Los dos modos leen exactamente los mismos datos: elegir uno u otro no escribe
nada distinto, así que se pueden comparar el mismo día y volver atrás sin
perder nada.

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

CREATE TABLE IF NOT EXISTS work_pauses (
    -- Inicio de la pausa en segundos epoch (UTC). Clave primaria: dos pausas
    -- no pueden empezar en el mismo instante, y así reabrir una pausa ya
    -- marcada la corrige en vez de duplicarla.
    start INTEGER PRIMARY KEY,
    -- NULL mientras la pausa sigue abierta. Una pausa abierta NO se cierra
    -- sola al leer: cerrarla a ojo apuntaría trabajo que quizá no existió,
    -- y el tope de jornada ya acota el daño del olvido.
    end   INTEGER,
    -- 'manual' (la marcaste al irte) o 'answer' (declarada a posteriori
    -- desde la vista de tiempos).
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS work_claims (
    -- Hueco largo reclamado como trabajo: la excepción a la regla de que un
    -- rato sin ninguna señal es ausencia. Se guarda el reclamo y no la
    -- ausencia porque las ausencias son la norma y se deducen solas; lo que
    -- no se puede deducir es la tarde de pizarra sin tocar el teclado.
    start INTEGER PRIMARY KEY,
    end   INTEGER NOT NULL
);
"""

# Cómo se supo que esa ranura era trabajo:
#   'auto'   — medido: el panel tenía el foco y hubo entrada del usuario.
#   'manual' — declarado: el usuario encendió el cronómetro para trabajar
#              FUERA del panel (probar la app que construye, por ejemplo).
#   'bridge' — inferido: nadie lo latió, lo rellena el puente de continuidad
#              al leer (ver el docstring del módulo). NUNCA se guarda en la
#              base; solo existe en la salida de `bloques()` y `resumen()`.
#   'signal' — probado por el transcript de Claude: el agente de ese proyecto
#              estaba trabajando (ver worklog_signals.py).
#   'day'    — cubierto por la jornada continua: dentro del horario del día y
#              fuera de toda pausa, aunque nadie latiera (ver MODOS).
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

# Hueco sin ninguna señal a partir del cual la jornada deja de contar sola, en
# MINUTOS. Ver config.WORKLOG_ABSENCE_MIN. 0 lo apaga.
AUSENCIA_MIN = config.WORKLOG_ABSENCE_MIN


# Cómo se decide cuánto dura el día.
#
#   'measured' — el de siempre: solo cuenta lo que dejó rastro. Sesga a la
#                baja de forma brutal (medido: 3 h 25 en un día de 8 h 30),
#                porque el rato en el que un agente construye y tú miras otra
#                ventana no deja rastro en ninguna parte.
#   'workday'  — la jornada cuenta entera entre la primera y la última señal
#                del día, MENOS las pausas marcadas. Las señales dejan de
#                decidir *si* trabajaste y pasan a decidir solo *en qué
#                proyecto*, que es lo único que saben de verdad.
#
# Se elige por consulta y no se guarda nada distinto según el modo: los dos
# salen de los mismos datos, así que se pueden comparar el mismo día y volver
# atrás sin perder nada.
MODOS = ("measured", "workday")
MODO_POR_DEFECTO = config.WORKLOG_MODE

# Tope de una jornada, en horas. Es la red para el día en que se olvide marcar
# la pausa: sin él, irse el viernes dejando el panel abierto apuntaría el fin
# de semana entero.
JORNADA_MAX_HORAS = config.WORKLOG_MAX_DAY_HOURS


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


# --- Pausas -------------------------------------------------------------
#
# Son el único dato que el panel no puede deducir. La duración de un hueco no
# dice si fue trabajo: medido sobre un día real, un hueco de 87 minutos fue
# mitad trabajo, uno de 60 fue trabajo entero y uno de 89 fue casi todo
# ausencia. Ningún umbral separa esos tres casos, así que lo decide el usuario.


def pausar(ahora: float | None = None, source: str = "manual") -> int:
    """Abre una pausa. Devuelve su inicio.

    Si ya hay una abierta no se toca: pulsar dos veces «me voy» no puede
    perder el inicio real de la ausencia.
    """
    inicio = slot_de(time.time() if ahora is None else ahora)
    with _conexion() as con:
        abierta = con.execute(
            "SELECT start FROM work_pauses WHERE end IS NULL ORDER BY start DESC"
        ).fetchone()
        if abierta:
            return int(abierta[0])
        con.execute(
            "INSERT OR IGNORE INTO work_pauses (start, end, source)"
            " VALUES (?, NULL, ?)",
            (inicio, source if source in ("manual", "answer") else "manual"),
        )
    return inicio


def reanudar(ahora: float | None = None) -> dict | None:
    """Cierra la pausa abierta. Devuelve la pausa cerrada, o None si no había."""
    fin = slot_de(time.time() if ahora is None else ahora) + SLOT_SECONDS
    with _conexion() as con:
        abierta = con.execute(
            "SELECT start FROM work_pauses WHERE end IS NULL ORDER BY start DESC"
        ).fetchone()
        if not abierta:
            return None
        inicio = int(abierta[0])
        # Una pausa que acabaría antes de empezar solo puede venir de un reloj
        # tocado a mano: se cierra en su propio inicio y dura cero.
        fin = max(fin, inicio)
        con.execute("UPDATE work_pauses SET end = ? WHERE start = ?", (fin, inicio))
    return {"start": inicio, "end": fin}


def marcar_pausa(inicio: float, fin: float, source: str = "answer") -> dict:
    """Anota una pausa YA pasada: la respuesta a «¿estabas fuera?».

    Existe porque nadie se acuerda de marcar la pausa antes de levantarse. Lo
    que sí se puede es responder al volver, y entonces el rato se recorta con
    la hora real en vez de con una regla inventada.
    """
    ini = slot_de(inicio)
    final = max(slot_de(fin) + SLOT_SECONDS, ini)
    with _conexion() as con:
        con.execute(
            "INSERT INTO work_pauses (start, end, source) VALUES (?, ?, ?)"
            " ON CONFLICT(start) DO UPDATE SET end = excluded.end,"
            "   source = excluded.source",
            (ini, final, source if source in ("manual", "answer") else "answer"),
        )
    return {"start": ini, "end": final}


def borrar_pausa(inicio: float) -> bool:
    """Quita una pausa. Marcar de más tiene que poder deshacerse."""
    with _conexion() as con:
        cur = con.execute("DELETE FROM work_pauses WHERE start = ?", (slot_de(inicio),))
    return cur.rowcount > 0


def pausas(desde: float | None = None, hasta: float | None = None) -> list[dict]:
    """Pausas que tocan el periodo, la abierta incluida (con `end` a None)."""
    inicio, fin = _rango(desde, hasta)
    with _conexion() as con:
        filas = list(
            con.execute(
                "SELECT start, end, source FROM work_pauses"
                " WHERE (end IS NULL OR end > ?) AND start < ? ORDER BY start",
                (inicio, fin),
            )
        )
    return [
        {"start": f[0], "end": f[1], "source": f[2], "open": f[1] is None}
        for f in filas
    ]


def ultima_ranura() -> int | None:
    """Inicio de la última ranura registrada, o None si no hay ninguna.

    El panel la usa para saber cuánto lleva sin haber actividad. Detectar la
    ausencia por el salto del reloj no basta: solo cazaría el portátil que se
    suspende, y la ausencia normal —irse dejando el panel abierto— no mueve
    ningún reloj.
    """
    with _conexion() as con:
        fila = con.execute("SELECT MAX(slot_start) FROM work_slots").fetchone()
    return int(fila[0]) if fila and fila[0] is not None else None


def _en_pausa(slot: int, tramos: list[tuple[int, int]]) -> bool:
    return any(a <= slot < b for a, b in tramos)


def _ranuras(
    desde: float | None,
    hasta: float | None,
    puente_min: int | None,
    modo: str | None = None,
    tz_offset_min: int = 0,
) -> list[tuple[int, str, str | None, str | None, str]]:
    """Ranuras del periodo, ya con los huecos cortos rellenados.

    Es el único sitio donde se decide qué cuenta: `bloques()` y `resumen()`
    parten de aquí, así que no pueden dar totales distintos por descuido. Y es
    también donde se bifurcan los dos modos (ver `MODOS`) — en 'workday' el
    puente sobra, porque la jornada ya cubre los huecos que no son pausa.

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
    if (modo or MODO_POR_DEFECTO) == "workday":
        return _ranuras_jornada(desde, hasta, tz_offset_min)

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
    modo: str | None = None,
    tz_offset_min: int = 0,
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
        fila for fila in _ranuras(desde, hasta, puente_min, modo, tz_offset_min)
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


def _cargar_señales(
    inicio: int, fin: int
) -> tuple[list[tuple], list[tuple[int, int]], list[tuple[int, int]]]:
    """Todo lo que el modo 'workday' necesita leer: señales, pausas y reclamos.

    Sale a una función propia porque lo leen dos caminos —el cálculo de las
    ranuras y el listado de ausencias del panel— y si cada uno cargara lo suyo
    acabarían enseñando huecos que el total no descuenta.

    Una señal es `(slot, space, session, command, source, es_tuyo)`. Los
    latidos cuentan como tuyos porque son entrada real del usuario; las líneas
    del transcript, solo cuando las escribiste tú.
    """
    import worklog_signals

    with _conexion() as con:
        worklog_signals.indexar(con, SLOT_SECONDS)
        latidos = list(
            con.execute(
                "SELECT slot_start, space, session, command, source FROM work_slots"
                " WHERE slot_start >= ? AND slot_start < ? ORDER BY slot_start",
                (inicio, fin),
            )
        )
        transcritas = worklog_signals.señales(con, inicio, fin)
        tramos_pausa = [
            (int(f[0]), int(f[1]) if f[1] is not None else 2**62)
            for f in con.execute(
                "SELECT start, end FROM work_pauses WHERE (end IS NULL OR end > ?)"
                " AND start < ?",
                (inicio, fin),
            )
        ]
        reclamos = [
            (int(f[0]), int(f[1]))
            for f in con.execute(
                "SELECT start, end FROM work_claims WHERE end > ? AND start < ?",
                (inicio, fin),
            )
        ]

    señales: list[tuple] = [(f[0], f[1], f[2], f[3], f[4], True) for f in latidos]
    conocidas = {(f[0], f[1]) for f in latidos}
    for slot, espacio, es_tuyo in transcritas:
        if (slot, espacio) not in conocidas:
            señales.append((slot, espacio, None, "claude", "signal", bool(es_tuyo)))
    señales.sort(key=lambda s: s[0])
    return señales, tramos_pausa, reclamos


def _umbral_ausencia(minutos: int | None) -> int:
    """Umbral de ausencia en segundos. `None` = el de la configuración."""
    if minutos is None:
        minutos = AUSENCIA_MIN
    return max(0, min(int(minutos), 24 * 60)) * 60


def _ausencias(
    señales: list[tuple], tz_offset_min: int, umbral_min: int | None = None
) -> list[tuple[int, int]]:
    """Huecos del día sin NINGUNA señal más largos que el umbral.

    Es la corrección al modelo de «la jornada cuenta entera»: contarla entera
    de verdad apunta la comida, la siesta y la tarde en que el panel se quedó
    abierto. Un hueco así se reconoce sin preguntar nada — durante media hora
    no hubo ni una tecla ni una línea de agente en NINGÚN proyecto —, y lo
    excepcional (una tarde de pizarra) se reclama a mano.

    Solo se miran huecos DENTRO de un mismo día local: la noche entre dos días
    no es un hueco que descontar, es que la jornada se acabó.
    """
    umbral = _umbral_ausencia(umbral_min)
    if not umbral:
        return []
    huecos: list[tuple[int, int]] = []
    for previa, siguiente in zip(señales, señales[1:], strict=False):
        principio = previa[0] + SLOT_SECONDS
        final = siguiente[0]
        if final - principio < umbral:
            continue
        if _dia_local(principio, tz_offset_min) != _dia_local(final, tz_offset_min):
            continue
        huecos.append((principio, final))
    return huecos


def huecos(
    desde: float | None = None,
    hasta: float | None = None,
    tz_offset_min: int = 0,
    umbral_min: int | None = None,
) -> list[dict]:
    """Las ausencias deducidas del periodo, con lo que se haya reclamado.

    Es lo que sustituye a la pregunta al volver: en vez de interrumpir para
    cobrar una respuesta que se pulsa sin leer, el panel descuenta el hueco y
    lo enseña en la vista de tiempos, donde se ve junto al resto del día y se
    puede recuperar de un clic.
    """
    inicio, fin = _rango(desde, hasta)
    señales, _, reclamos = _cargar_señales(inicio, fin)
    salida = []
    for principio, final in _ausencias(señales, tz_offset_min, umbral_min):
        recuperados = sum(
            max(0, min(final, b) - max(principio, a)) for a, b in reclamos
        )
        salida.append(
            {
                "start": principio,
                "end": final,
                "seconds": final - principio,
                # Parcial cuando el reclamo cubre solo un trozo: pasa al bajar
                # el umbral, que parte en dos un hueco ya reclamado.
                "claimed_seconds": recuperados,
                "claimed": recuperados >= final - principio,
            }
        )
    return salida


def reclamar_hueco(inicio: float, fin: float) -> dict:
    """Cuenta como trabajo un hueco que se había descontado por ausencia.

    UPSERT por inicio, igual que las pausas: reclamar dos veces el mismo hueco
    corrige, no duplica.
    """
    ini = slot_de(inicio)
    final = max(slot_de(fin), ini)
    with _conexion() as con:
        con.execute(
            "INSERT INTO work_claims (start, end) VALUES (?, ?)"
            " ON CONFLICT(start) DO UPDATE SET end = excluded.end",
            (ini, final),
        )
    return {"start": ini, "end": final}


def borrar_reclamo(inicio: float) -> bool:
    """Devuelve el hueco a ser ausencia: reclamar de más se deshace igual."""
    with _conexion() as con:
        cur = con.execute("DELETE FROM work_claims WHERE start = ?", (slot_de(inicio),))
    return cur.rowcount > 0


def _ranuras_jornada(
    desde: float | None,
    hasta: float | None,
    tz_offset_min: int,
    tope_horas: int | None = None,
    umbral_min: int | None = None,
) -> list[tuple[int, str, str | None, str | None, str]]:
    """Ranuras del modo 'workday': el día entero menos pausas y ausencias.

    El reparto por proyecto se hace por **cercanía**: cada ranura se la lleva
    aquella cuya señal más próxima en el tiempo sea suya, con las tuyas —un
    mensaje que escribiste— ganando los empates. Las señales son los latidos
    del panel Y los transcripts de Claude, que es lo que permite atribuir el
    rato en que un agente construye y tú miras otra ventana.

    No se cuenta lo que cae en una pausa marcada ni en una **ausencia**: un
    hueco largo sin ninguna señal (ver `_ausencias`), salvo que se haya
    reclamado como trabajo desde la vista de tiempos.

    La jornada se calcula **por día local**: si el rango se tomara entero, la
    noche entre dos días contaría como trabajo.

    Una ranura sigue teniendo un único dueño, así que el invariante de siempre
    —la suma de los espacios nunca supera el tiempo real— se mantiene.
    """
    import bisect

    inicio, fin = _rango(desde, hasta)
    tope = max(1, min(int(JORNADA_MAX_HORAS if tope_horas is None else tope_horas), 24))

    señales, tramos_pausa, reclamos = _cargar_señales(inicio, fin)
    if not señales:
        return []
    tiempos = [s[0] for s in señales]
    ausencias = _ausencias(señales, tz_offset_min, umbral_min)

    # La jornada de cada día local: de su primera señal a su última.
    dias: dict[str, list[int]] = {}
    for s in señales:
        dias.setdefault(_dia_local(s[0], tz_offset_min), []).append(s[0])

    por_slot: dict[int, tuple] = {}
    for s in señales:
        # Con dos señales en la misma ranura gana la tuya: es lo que impide
        # que el ruido de un agente le quite la ranura al proyecto que estabas
        # mirando de verdad.
        previa = por_slot.get(s[0])
        if previa is None or (s[5] and not previa[5]):
            por_slot[s[0]] = s

    salida: list[tuple] = []
    for slots in dias.values():
        principio, final = min(slots), max(slots) + SLOT_SECONDS
        # El tope se mide sobre lo CONTADO, no sobre el horario: aplicado al
        # horario castigaría justo a quien marca sus pausas —una jornada de
        # 11 h con 2 h de pausa son 9 h de trabajo, no 10— y el olvido que la
        # red pretende cubrir seguiría pasando.
        restantes = tope * 3600 // SLOT_SECONDS
        for slot in range(principio, final, SLOT_SECONDS):
            if restantes <= 0:
                break
            if slot < inicio or slot >= fin:
                continue
            if _en_pausa(slot, tramos_pausa):
                continue
            # La ausencia solo tapa lo que nadie latió: una ranura con señal
            # propia no puede caer dentro de un hueco «sin ninguna señal», así
            # que este descuento nunca borra tiempo medido.
            if _en_pausa(slot, ausencias) and not _en_pausa(slot, reclamos):
                continue
            restantes -= 1
            propia = por_slot.get(slot)
            if propia is not None:
                salida.append(propia[:5])
                continue
            # Sin señal en esta ranura: se la queda la más cercana.
            i = bisect.bisect_left(tiempos, slot)
            candidatas = [j for j in (i - 1, i) if 0 <= j < len(señales)]
            if not candidatas:
                continue
            j = min(
                candidatas,
                key=lambda k: (abs(tiempos[k] - slot), not señales[k][5]),
            )
            _, espacio, sesion, comando, _, _ = señales[j]
            salida.append((slot, espacio, sesion, comando, "day"))

    salida.sort(key=lambda s: s[0])
    return salida
def resumen(
    desde: float | None = None,
    hasta: float | None = None,
    tz_offset_min: int = 0,
    puente_min: int | None = None,
    space: str | None = None,
    modo: str | None = None,
) -> dict:
    """Totales del periodo: general, por espacio y por día local.

    Todo sale de contar ranuras y multiplicar por su duración. No hay ningún
    acumulado que mantener.

    Con `space`, TODO el resumen es de ese espacio: el total, los días y la
    media. Filtrar solo la lista de tramos y dejar las cifras de arriba
    globales es peor que no filtrar, porque la pantalla mezcla dos preguntas
    distintas sin decirlo.

    El filtro va DESPUÉS del puente, igual que en `bloques()`: aplicado antes,
    dos ranuras separadas por otro proyecto parecerían contiguas.

    Se agrega en Python y no en SQL porque las ranuras del puente no existen
    en la base: un `GROUP BY` sobre la tabla y un puente aplicado aparte darían
    dos totales distintos para la misma pregunta.
    """
    filas = [
        fila for fila in _ranuras(desde, hasta, puente_min, modo, tz_offset_min)
        if not space or fila[1] == space
    ]

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

    # Desde cuándo hay datos DE LO QUE SE PREGUNTA: con un espacio filtrado,
    # la fecha del registro entero contestaría otra cosa ("el panel lleva
    # midiendo desde marzo" cuando el espacio se creó en agosto).
    with _conexion() as con:
        if space:
            primera = con.execute(
                "SELECT MIN(slot_start) FROM work_slots WHERE space = ?", (space,)
            ).fetchone()[0]
        else:
            primera = con.execute(
                "SELECT MIN(slot_start) FROM work_slots"
            ).fetchone()[0]

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
