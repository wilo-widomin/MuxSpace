"""Token con el que un script de esta máquina usa la biblioteca del panel.

Un proceso programado (el receptor de entrevistas) tiene que crear un
proyecto, lanzarlo y borrarlo al terminar. No tiene cookie, y con el panel en
modo `pam` la alternativa sería dejar en un fichero la contraseña del sistema.

Este módulo solo responde a «¿este token vale?» y lleva la cuenta de los
fallos. Lo que el token permite hacer está en `script_policy.py` y en
`main._script_auth`, y sus rutas, enumeradas en `test_auth_contract.py`.

**En disco solo hay huellas.** El token nace aquí, se imprime una vez y no se
guarda: quien lea `data/` no lo obtiene. Tiene 256 bits de azar, así que un
SHA-256 basta; un hash lento solo se justifica con contraseñas, que tienen
poca entropía.

**Dos a la vez, para rotar sin parar nada.** `generate` deja el nuevo y
conserva el anterior; cuando el receptor ya usa el nuevo, `retire-previous`
retira el otro. El panel relee el archivo cuando cambia, como la lista de
baneos de `auth.py`, así que nada de esto pide reiniciar.

**Es aparte del de `attention_store` a propósito:** aquel lo leen los hooks de
todas las sesiones y solo marca avisos; este no debe llegarles.

Uso, desde la raíz del repositorio:

    backend/venv/bin/python backend/script_token.py generate
    backend/venv/bin/python backend/script_token.py retire-previous
    backend/venv/bin/python backend/script_token.py status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import sys
import time
from pathlib import Path
from threading import Lock

from datafiles import write_private

_HASHES_PATH = Path(__file__).resolve().parent / "data" / "script_token_hashes.json"

# Lo que identifica a un token en la auditoría: un trozo de su huella. Basta
# para distinguir los dos activos y no sirve para reconstruir nada.
_FINGERPRINT_CHARS = 8

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

_lock = Lock()
_signature: tuple[int, int, int] | None = None
_hashes: tuple[str, ...] = ()

# Intentos fallidos: clave -> ventana actual y bloqueo. Aparte del contador
# del login a propósito, para que un token mal copiado no deje a Willy sin
# entrar con su contraseña. Vive en memoria porque quien llega hasta aquí ya
# está en la máquina y un reinicio del panel no está a su alcance por la red.
_MAX_FAILURES = 5
_WINDOW_SECONDS = 60
# Sin prolongarse con cada fallo: el receptor legítimo vuelve solo a los cinco
# minutos aunque otro proceso siga equivocándose.
_BLOCK_SECONDS = 300
_MAX_TRACKED = 256

_failures: dict[str, dict[str, float]] = {}
_failures_lock = Lock()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


def _read_store() -> dict:
    """Las huellas guardadas. Ausente o corrupto => ninguna: no abre nada."""
    try:
        data = json.loads(_HASHES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid(value: object) -> str | None:
    return value if isinstance(value, str) and _HASH_RE.match(value) else None


def _active_hashes() -> tuple[str, ...]:
    """Las huellas activas, releídas solo si el archivo ha cambiado.

    El inodo entra en la firma porque `write_private` sustituye el archivo:
    dos escrituras en el mismo instante de reloj siguen distinguiéndose.
    """
    global _signature, _hashes
    with _lock:
        try:
            st = _HASHES_PATH.stat()
        except OSError:
            _signature, _hashes = None, ()
            return ()
        signature = (st.st_mtime_ns, st.st_ino, st.st_size)
        if signature != _signature:
            store = _read_store()
            found = (_valid(store.get("current")), _valid(store.get("previous")))
            _hashes = tuple(h for h in found if h)
            _signature = signature
        return _hashes


def match(candidate: str | None) -> str | None:
    """Prefijo de la huella del token que coincide, o None si no vale ninguno.

    Recorre siempre todas las huellas, sin salir al acertar, para que el
    tiempo no diga con cuál ha casado.
    """
    if not candidate:
        return None
    digest = _digest(candidate)
    found = None
    for stored in _active_hashes():
        if secrets.compare_digest(digest, stored):
            found = stored
    return found[:_FINGERPRINT_CHARS] if found else None


# ----------------------------------------------------------------------
# Intentos fallidos
# ----------------------------------------------------------------------
def _now() -> float:
    """El reloj, en una función propia para poder simularlo en los tests."""
    return time.time()


def _forget_stale_locked(now: float) -> None:
    for key, rec in list(_failures.items()):
        if now >= rec["blocked_until"] and now - rec["window_start"] > _WINDOW_SECONDS:
            del _failures[key]


def attempts_allowed(key: str) -> bool:
    """False mientras esa clave esté bloqueada por acumular fallos."""
    now = _now()
    with _failures_lock:
        _forget_stale_locked(now)
        rec = _failures.get(key)
        return rec is None or now >= rec["blocked_until"]


def register_failure(key: str) -> None:
    """Cuenta un token equivocado. El quinto en la ventana bloquea."""
    now = _now()
    with _failures_lock:
        _forget_stale_locked(now)
        rec = _failures.get(key)
        if rec is None or now - rec["window_start"] > _WINDOW_SECONDS:
            rec = {"count": 0, "window_start": now, "blocked_until": 0.0}
            _failures[key] = rec
        rec["count"] += 1
        if rec["count"] >= _MAX_FAILURES:
            rec["blocked_until"] = now + _BLOCK_SECONDS
        while len(_failures) > _MAX_TRACKED:
            oldest = min(_failures, key=lambda k: _failures[k]["window_start"])
            del _failures[oldest]


# ----------------------------------------------------------------------
# Comandos
# ----------------------------------------------------------------------
def generate() -> tuple[str, str | None]:
    """Crea un token nuevo y guarda su huella, conservando la del anterior.

    Devuelve el token en claro, que ya no se podrá recuperar, y la huella que
    sale de la rotación si había dos activos.
    """
    token = secrets.token_urlsafe(32)
    store = _read_store()
    current = _valid(store.get("current"))
    dropped = _valid(store.get("previous"))
    write_private(
        _HASHES_PATH,
        json.dumps({"current": _digest(token), "previous": current}, indent=2) + "\n",
    )
    return token, dropped


def retire_previous() -> bool:
    """Deja solo el token actual. False si no había anterior que retirar."""
    store = _read_store()
    current = _valid(store.get("current"))
    if _valid(store.get("previous")) is None:
        return False
    write_private(
        _HASHES_PATH,
        json.dumps({"current": current, "previous": None}, indent=2) + "\n",
    )
    return True


def status() -> dict[str, str | None]:
    """Prefijo de la huella de cada token activo, para saber cuál es cuál."""
    store = _read_store()
    return {
        name: value[:_FINGERPRINT_CHARS] if (value := _valid(store.get(name))) else None
        for name in ("current", "previous")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gestiona el token de scripts de MuxSpace."
    )
    parser.add_argument(
        "command",
        choices=["generate", "retire-previous", "status"],
        help=(
            "generate: crea uno nuevo, lo imprime una vez y conserva el anterior; "
            "retire-previous: retira el anterior; "
            "status: muestra qué tokens hay activos"
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "generate":
        token, dropped = generate()
        # El token va solo a la salida estándar, para poder redirigirlo a su
        # archivo; los avisos, a la de errores.
        print(token)
        print("Guárdalo ahora: no se puede volver a ver.", file=sys.stderr)
        if dropped:
            print(
                f"Había dos activos: el de huella {dropped[:_FINGERPRINT_CHARS]} "
                "ha dejado de valer.",
                file=sys.stderr,
            )
    elif args.command == "retire-previous":
        retired = retire_previous()
        print("Token anterior retirado." if retired else "No había token anterior.")
    else:
        for name, fingerprint in status().items():
            print(f"{name}: {fingerprint or '-'}")
    return 0


if __name__ == "__main__":  # pragma: no cover — se prueba llamando a `main`.
    sys.exit(main())
