"""Preferencia de campanilla del aviso de atención: qué suena y a qué volumen.

El sonido se **sintetiza en el navegador** (`frontend/src/lib/chime.js`), así
que lo que se guarda aquí no es audio: es la receta. Tres formas de decirla,
excluyentes, en el campo `mode`:

- `preset` — uno de los sonidos que trae el panel, por su id.
- `custom` — una lista de notas escrita por el usuario en el editor.
- `file` — un audio propio subido a `data/chime/`, que sí son bytes.

**Por qué en el servidor y no en `localStorage`.** El panel se abre desde el
portátil, la tablet y el móvil, y elegir la campanilla tres veces es elegirla
mal dos. La marca de atención vive en el servidor porque es un hecho
compartido (ver `attention_store`); esto vive aquí por lo contrario, porque es
una preferencia de la persona y la persona es una sola.

A diferencia de los avisos, esto **se persiste en disco**: un ajuste que se
borra al reiniciar el backend no es un ajuste.

**Un solo worker.** El `Lock` es de hilos, no de procesos, y cada guardado
reescribe el JSON entero. Ver `docs/un-solo-worker.md`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from threading import Lock

from datafiles import ensure_dir, write_private
from errors import AppError

_DATA_DIR = Path(__file__).resolve().parent / "data"
_STORE_PATH = _DATA_DIR / "chime.json"
AUDIO_DIR = _DATA_DIR / "chime"

_lock = Lock()

MODES = ("preset", "custom", "file")

# El id del preset NO se valida contra una lista de ids conocidos: los
# presets los define el frontend, que es quien sabe sintetizarlos, y
# repetir aquí esa lista garantizaría que un día no coincidan. Se valida la
# FORMA (un slug corto), y el frontend cae al sonido por defecto si recibe
# un id que no conoce. El daño máximo de un id inventado es que suene el
# de siempre.
_PRESET_RE = re.compile(r"^[a-z0-9-]{1,32}$")

DEFAULT_PRESET = "bell"

# Topes del editor de notas. No son de seguridad —el audio lo sintetiza el
# navegador del propio usuario— sino de sensatez: una campanilla de cien
# notas ya no es un aviso, es una canción, y un aviso que dura más que la
# paciencia de quien lo oye deja de avisar.
MAX_NOTES = 16
MIN_FREQ = 20.0
MAX_FREQ = 12000.0
MAX_DELAY = 5.0
MIN_DURATION = 0.02
MAX_DURATION = 5.0

TIMBRES = ("sine", "bell")

# Tipos de audio que aceptamos para una campanilla propia, con su extensión.
AUDIO_EXT = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}

# Un aviso es corto por definición; 2 MB dan de sobra para varios segundos en
# cualquiera de esos formatos.
AUDIO_MAX_BYTES = 2 * 1024 * 1024

# Solo hay UNA campanilla propia a la vez: subir otra sustituye la anterior.
# Un historial aquí no serviría para nada —nadie colecciona campanillas— y
# obligaría a inventar retención.
_AUDIO_STEM = "custom"


class ChimeError(AppError):
    """Ajuste de campanilla inválido.

    Lleva su propio `status` porque no todos los rechazos son un 400: un
    formato de audio que no aceptamos es un 415, y perder esa distinción
    obligaría al endpoint a adivinarla por el código de error.
    """

    def __init__(self, status: int, code: str, **params) -> None:
        self.status = status
        super().__init__(code, params)


def _default() -> dict:
    return {
        "mode": "preset",
        "preset": DEFAULT_PRESET,
        "volume": 0.3,
        "muted": False,
        "notes": [],
        "timbre": "bell",
        "file": None,
    }


def _audio_path() -> Path | None:
    """Ruta del audio propio subido, o None si no hay ninguno."""
    if not AUDIO_DIR.is_dir():
        return None
    for path in sorted(AUDIO_DIR.glob(f"{_AUDIO_STEM}.*")):
        if path.is_file():
            return path
    return None


def _load() -> dict:
    """Lee el ajuste de disco. Ausente o corrupto => el de fábrica.

    Leer NUNCA lanza: un JSON a medias no puede dejar el panel sin sonido de
    aviso ni, peor, sin arrancar.
    """
    base = _default()
    if not _STORE_PATH.is_file():
        return base
    try:
        data = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return base
    if not isinstance(data, dict):
        return base
    try:
        # Se valida al leer y no solo al escribir: el fichero se puede editar
        # a mano, y un `volume: 40` guardado ahí reventaría los oídos de
        # alguien.
        return _clean(data)
    except ChimeError:
        return base


def _num(value, lo: float, hi: float, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChimeError(400, code)
    number = float(value)
    if number != number or number < lo or number > hi:  # NaN incluido
        raise ChimeError(400, code)
    return number


def _clean_notes(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ChimeError(400, "err.chime_bad_notes")
    if len(raw) > MAX_NOTES:
        raise ChimeError(400, "err.chime_too_many_notes", max=MAX_NOTES)
    notes = []
    for item in raw:
        if not isinstance(item, dict):
            raise ChimeError(400, "err.chime_bad_notes")
        notes.append(
            {
                "freq": _num(item.get("freq"), MIN_FREQ, MAX_FREQ, "err.chime_bad_freq"),
                "delay": _num(item.get("delay"), 0.0, MAX_DELAY, "err.chime_bad_delay"),
                "duration": _num(
                    item.get("duration"),
                    MIN_DURATION,
                    MAX_DURATION,
                    "err.chime_bad_duration",
                ),
            }
        )
    return notes


def _clean(raw: dict) -> dict:
    """Normaliza y valida un ajuste completo. Lanza `ChimeError` si no vale."""
    out = _default()

    mode = raw.get("mode", "preset")
    if mode not in MODES:
        raise ChimeError(400, "err.chime_bad_mode")
    out["mode"] = mode

    preset = raw.get("preset") or DEFAULT_PRESET
    if not isinstance(preset, str) or not _PRESET_RE.match(preset):
        raise ChimeError(400, "err.chime_bad_preset")
    out["preset"] = preset

    out["volume"] = _num(raw.get("volume", 0.3), 0.0, 1.0, "err.chime_bad_volume")
    out["muted"] = bool(raw.get("muted", False))

    timbre = raw.get("timbre", "bell")
    if timbre not in TIMBRES:
        raise ChimeError(400, "err.chime_bad_timbre")
    out["timbre"] = timbre

    out["notes"] = _clean_notes(raw.get("notes") or [])

    # El modo `custom` sin una sola nota sonaría a silencio, y un aviso mudo
    # se confunde con uno roto.
    if out["mode"] == "custom" and not out["notes"]:
        raise ChimeError(400, "err.chime_no_notes")

    # El nombre del audio NO se toma de la petición: se mira qué hay en disco.
    # Así el ajuste no puede apuntar a un fichero que no existe (ni a uno de
    # fuera del directorio).
    existing = _audio_path()
    out["file"] = existing.name if existing else None
    if out["mode"] == "file" and not out["file"]:
        raise ChimeError(400, "err.chime_no_audio")

    return out


def _save(cfg: dict) -> None:
    write_private(_STORE_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))


def get() -> dict:
    """Ajuste actual, ya normalizado."""
    with _lock:
        return _load()


def save(raw: dict) -> dict:
    """Valida y persiste un ajuste. Devuelve el guardado."""
    with _lock:
        cfg = _clean(raw if isinstance(raw, dict) else {})
        _save(cfg)
        return cfg


def save_audio(data: bytes, content_type: str) -> dict:
    """Guarda el audio propio (sustituyendo el anterior) y lo deja elegido.

    Subir un sonido y que no suene hasta darle a otro sitio sería una trampa:
    el modo pasa a `file` en el mismo gesto.
    """
    ext = AUDIO_EXT.get(content_type)
    if ext is None:
        raise ChimeError(415, "err.chime_audio_format")
    if not data:
        raise ChimeError(400, "err.chime_audio_missing")
    with _lock:
        ensure_dir(AUDIO_DIR)
        for old in AUDIO_DIR.glob(f"{_AUDIO_STEM}.*"):
            try:
                old.unlink()
            except OSError:
                pass
        write_private(AUDIO_DIR / f"{_AUDIO_STEM}{ext}", data)
        cfg = _load()
        cfg["mode"] = "file"
        cfg = _clean(cfg)
        _save(cfg)
        return cfg


def delete_audio() -> dict:
    """Borra el audio propio y, si estaba elegido, vuelve al preset."""
    with _lock:
        for old in AUDIO_DIR.glob(f"{_AUDIO_STEM}.*") if AUDIO_DIR.is_dir() else []:
            try:
                old.unlink()
            except OSError:
                pass
        cfg = _load()
        if cfg["mode"] == "file":
            cfg["mode"] = "preset"
        cfg = _clean(cfg)
        _save(cfg)
        return cfg


def audio_file() -> Path | None:
    """Ruta del audio propio para servirlo, o None."""
    with _lock:
        return _audio_path()
