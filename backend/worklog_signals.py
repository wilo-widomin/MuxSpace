"""Señales de actividad sacadas de los transcripts de Claude Code.

## Por qué hacen falta

El panel solo sabe que trabajas si tocas algo con su pestaña delante. La forma
real de trabajar es otra: le pides algo a un agente y te vas a mirar otra cosa
mientras construye. Medido sobre un día completo, el panel veía el 32 % del
tiempo que el usuario recordaba haber trabajado.

El transcript de Claude Code arregla justo esa parte. Cada línea del `.jsonl`
lleva **hora, `cwd` y `sessionId`**, así que prueba que un proyecto estaba
vivo aunque tú estuvieras mirando otra ventana. Y es una prueba mejor que la
salida del terminal: la escribe la conversación, no el ruido de un PTY.

## Por qué se indexa y no se lee al vuelo

Son 263 MB en 177 archivos. Releerlos en cada consulta del dashboard es
inviable, así que se **indexan a ranuras** —la misma rejilla de 30 s que usan
los latidos— y se guarda cuánto se leyó de cada archivo. Un escaneo posterior
solo lee lo que se ha añadido al final.

## Lo que NO decide este módulo

Aquí no se decide si trabajaste: solo **dónde** había actividad. Cuánto cuenta
el día lo decide `worklog.py`.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import claude_transcript
import library_store
import logs

_log = logs.obtener(__name__)

# Las señales viven en la misma base que los latidos: se consultan juntas en
# cada lectura, y separarlas obligaría a coordinar dos archivos para nada.
_ESQUEMA = """
CREATE TABLE IF NOT EXISTS transcript_slots (
    slot_start INTEGER NOT NULL,
    space      TEXT NOT NULL,
    -- ¿Alguno de los eventos de esa ranura lo escribiste TÚ? Es lo que
    -- desempata cuando dos agentes trabajan a la vez: la ranura se la lleva
    -- el proyecto al que le hablaste más recientemente, no el que más ruido
    -- hace.
    is_user    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (slot_start, space)
);
CREATE INDEX IF NOT EXISTS idx_transcript_slots_space ON transcript_slots(space);

-- Cuánto se leyó ya de cada transcript. Sin esto, cada escaneo releería los
-- 263 MB enteros.
CREATE TABLE IF NOT EXISTS transcript_files (
    path   TEXT PRIMARY KEY,
    offset INTEGER NOT NULL,
    mtime  REAL NOT NULL
);
"""


def _mapa_espacios() -> list[tuple[str, str]]:
    """Rutas de proyecto y su espacio, de la más específica a la más general.

    Se ordena por longitud descendente porque un transcript puede estar en un
    SUBdirectorio del proyecto (`muxspace/frontend`): gana la ruta más larga
    que sea ancestro, que es el proyecto más concreto que lo contiene.
    """
    salida = []
    for proyecto in library_store.list_projects():
        espacio = getattr(proyecto, "space", None) or ""
        cwd = getattr(proyecto, "cwd", "") or ""
        if not espacio or not cwd:
            continue
        try:
            ruta = str(Path(cwd).expanduser().resolve())
        except OSError:
            continue
        salida.append((ruta, espacio))
    salida.sort(key=lambda x: -len(x[0]))
    return salida


def _espacio_de(cwd: str, mapa: list[tuple[str, str]]) -> str | None:
    """Espacio al que pertenece un `cwd`, o None si no es de ningún proyecto."""
    if not cwd:
        return None
    for ruta, espacio in mapa:
        if cwd == ruta or cwd.startswith(ruta + "/"):
            return espacio
    return None


def _es_tuyo(entrada: dict) -> bool:
    """¿Lo escribió el usuario? Los resultados de herramienta llegan como
    `user` en el `.jsonl` y no son un mensaje suyo."""
    if entrada.get("type") != "user":
        return False
    contenido = entrada.get("message", {}).get("content")
    if isinstance(contenido, list):
        return not any(
            isinstance(p, dict) and p.get("type") == "tool_result" for p in contenido
        )
    return True


def _instante(entrada: dict) -> float | None:
    marca = entrada.get("timestamp")
    if not isinstance(marca, str):
        return None
    try:
        # `fromisoformat` no acepta la 'Z' de estos timestamps hasta 3.11.
        from datetime import datetime

        return datetime.fromisoformat(marca.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def indexar(con: sqlite3.Connection, slot_seconds: int) -> int:
    """Lee lo nuevo de cada transcript y lo convierte en ranuras.

    Devuelve cuántas ranuras se añadieron. Es incremental: de cada archivo se
    recuerda hasta qué byte se leyó, así que un escaneo normal solo toca la
    cola de las conversaciones vivas.

    Un archivo que ENCOGE se releé entero: significa que se reescribió, y
    seguir leyendo desde el offset viejo daría líneas partidas.
    """
    con.executescript(_ESQUEMA)
    raiz = claude_transcript.RAIZ_PROYECTOS
    if not raiz.is_dir():
        return 0

    mapa = _mapa_espacios()
    leidos = {
        fila[0]: (fila[1], fila[2])
        for fila in con.execute("SELECT path, offset, mtime FROM transcript_files")
    }

    nuevas = 0
    for archivo in raiz.glob("*/*.jsonl"):
        try:
            info = archivo.stat()
        except OSError:
            continue
        clave = str(archivo)
        offset, mtime = leidos.get(clave, (0, 0.0))
        if info.st_size == offset and info.st_mtime == mtime:
            continue
        if info.st_size < offset:
            offset = 0

        ranuras: dict[tuple[int, str], int] = {}
        try:
            with archivo.open("rb") as fh:
                fh.seek(offset)
                datos = fh.read()
                fin = offset + len(datos)
                # La última línea puede estar a medio escribir: se deja para
                # el siguiente escaneo en vez de descartarla.
                corte = datos.rfind(b"\n")
                if corte == -1:
                    continue
                fin = offset + corte + 1
                for linea in datos[: corte + 1].splitlines():
                    if not linea.strip():
                        continue
                    try:
                        entrada = json.loads(linea)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if not isinstance(entrada, dict):
                        continue
                    instante = _instante(entrada)
                    if instante is None:
                        continue
                    espacio = _espacio_de(entrada.get("cwd", ""), mapa)
                    if not espacio:
                        continue
                    slot = int(instante) // slot_seconds * slot_seconds
                    clave_slot = (slot, espacio)
                    tuyo = 1 if _es_tuyo(entrada) else 0
                    ranuras[clave_slot] = max(ranuras.get(clave_slot, 0), tuyo)
        except OSError:
            continue

        for (slot, espacio), tuyo in ranuras.items():
            cur = con.execute(
                "INSERT INTO transcript_slots (slot_start, space, is_user)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(slot_start, space) DO UPDATE SET"
                "   is_user = max(is_user, excluded.is_user)",
                (slot, espacio, tuyo),
            )
            nuevas += cur.rowcount or 0
        con.execute(
            "INSERT INTO transcript_files (path, offset, mtime) VALUES (?, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET offset = excluded.offset,"
            "   mtime = excluded.mtime",
            (clave, fin, info.st_mtime),
        )

    return nuevas


def señales(
    con: sqlite3.Connection, inicio: int, fin: int
) -> list[tuple[int, str, int]]:
    """Ranuras con actividad de transcript en el periodo: (slot, space, is_user)."""
    con.executescript(_ESQUEMA)
    return list(
        con.execute(
            "SELECT slot_start, space, is_user FROM transcript_slots"
            " WHERE slot_start >= ? AND slot_start < ? ORDER BY slot_start",
            (inicio, fin),
        )
    )
