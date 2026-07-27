"""El guardián del aislamiento: comprueba que los tests no tocan datos reales.

Este archivo no prueba nada del producto. Prueba el `conftest.py`, que es de
quien dependen todos los demás tests del backend: si el aislamiento se rompe,
lo que se pierde es la biblioteca de comandos del usuario y su historial de
subidas, no un test en rojo.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import auth
import config
import dir_suggestions
import library_store
import main
import space_store
import upload_store

from conftest import ORIGIN, USERNAME

# La lista se DECLARA aquí y no se importa del conftest, a propósito. Es
# contabilidad por partida doble: si el guardián leyera la misma lista que el
# conftest usa para parchear, borrar un `monkeypatch.setattr` reduciría
# también lo que este test comprueba y la suite seguiría en verde. Al
# duplicarla, quitar un parche deja el test hablando de un atributo que ya
# nadie redirige, y salta.
RUTAS = [
    ("library_store", "_STORE_PATH"),
    ("space_store", "_STORE_PATH"),
    ("upload_store", "_STORE_PATH"),
    ("auth", "_FAILURES_PATH"),
    ("auth", "_BANNED_PATH"),
    ("main", "_PASTE_DIR"),
    ("main", "_DATA_DIR"),
]

_MODULOS = {
    "auth": auth,
    "library_store": library_store,
    "main": main,
    "space_store": space_store,
    "upload_store": upload_store,
}

# Se recalcula aquí, sin importarlo del conftest, por el mismo motivo que RUTAS.
DATOS_REALES = (Path(config.__file__).resolve().parent / "data").resolve()

_IDS = [f"{modulo}.{atributo}" for modulo, atributo in RUTAS]

# Un PNG de 1x1 real: al endpoint le basta el Content-Type, pero un fichero
# con cabecera válida hace que el fallo, si lo hay, sea del aislamiento y no
# de un futuro chequeo de formato.
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _ruta(modulo: str, atributo: str) -> Path:
    return getattr(_MODULOS[modulo], atributo)


def _huella(raiz: Path) -> dict[str, tuple[int, int]]:
    """Ruta -> (mtime_ns, tamaño) de todo lo que cuelga de `raiz`."""
    if not raiz.exists():
        return {}
    huella: dict[str, tuple[int, int]] = {}
    for p in [raiz, *raiz.rglob("*")]:
        try:
            st = p.lstat()
        except OSError:
            continue
        huella[str(p)] = (st.st_mtime_ns, st.st_size)
    return huella


@pytest.mark.parametrize(("modulo", "atributo"), RUTAS, ids=_IDS)
def test_ninguna_ruta_cae_bajo_backend_data(modulo: str, atributo: str) -> None:
    """Ninguna ruta de escritura apunta a los datos reales del usuario."""
    ruta = _ruta(modulo, atributo).resolve()
    assert not ruta.is_relative_to(DATOS_REALES), (
        f"{modulo}.{atributo} apunta a {ruta}, dentro de los datos reales"
    )


@pytest.mark.parametrize(("modulo", "atributo"), RUTAS, ids=_IDS)
def test_todas_las_rutas_caen_bajo_tmp(
    modulo: str, atributo: str, tmp_path: Path
) -> None:
    """La comprobación positiva, que es la fuerte.

    "No está bajo backend/data/" también lo cumpliría `/etc/passwd`. Lo que
    hace falta saber es que está donde debe: dentro del `tmp_path` de este
    test, que pytest borra solo.
    """
    # `.resolve()` en los dos lados: /tmp es un symlink en más de una distro,
    # y comparar la forma resuelta con la sin resolver daría un falso negativo.
    ruta = _ruta(modulo, atributo).resolve()
    assert ruta.is_relative_to(tmp_path.resolve()), (
        f"{modulo}.{atributo} apunta a {ruta}, fuera del tmp_path del test"
    )


def test_las_raices_no_alcanzan_el_home(allowed_root: Path) -> None:
    """Las sugerencias de directorio no llegan al home del usuario.

    No compara rutas: llama a la puerta real, `resolve_within_roots`, que es
    por donde pasa toda escritura de la subida de archivos. Es el escenario
    que US-004 va a atacar con symlinks, y tiene que rebotar aquí.
    """
    assert dir_suggestions.resolve_within_roots("~") is None
    assert dir_suggestions.resolve_within_roots(str(Path.home())) is None
    assert dir_suggestions.suggest("~") == []
    # Y la comprobación positiva: la raíz que sí vale es la de tmp. Sin ella
    # el test pasaría igual con las raíces apuntando a cualquier sitio
    # inexistente, que es justo lo que queda si se cae el parche del conftest.
    assert dir_suggestions.resolve_within_roots("") == allowed_root.resolve()


def test_escribir_en_todos_los_stores_no_toca_backend_data(
    client_auth, data_dir: Path
) -> None:
    """El test con dientes: se ejercita CADA escritor y se mide el resultado.

    Los tests de arriba miran rutas; este escribe de verdad, incluyendo el
    camino HTTP completo de `/api/paste-image`, y luego comprueba las dos
    mitades: que `backend/data/` está intacto y que los ficheros SÍ
    aparecieron en tmp. Sin la segunda mitad, un aislamiento que simplemente
    no escribiera nada en ningún sitio pasaría por la vía barata.
    """
    antes = _huella(DATOS_REALES)

    library_store.add_command("Prueba", "echo hola")
    space_store.create_space("Espacio de prueba")
    upload_store.add("archivo.txt", str(data_dir / "archivo.txt"), "~")
    auth.register_login_failure("203.0.113.9")
    resp = client_auth.post(
        "/api/paste-image", content=PNG_1X1, headers={"content-type": "image/png"}
    )
    assert resp.status_code == 200, resp.text

    assert _huella(DATOS_REALES) == antes

    assert (data_dir / "library.json").is_file()
    assert (data_dir / "spaces.json").is_file()
    assert (data_dir / "upload_history.json").is_file()
    assert (data_dir / "login_failures.json").is_file()
    assert list((data_dir / "pastes").glob("paste-*")), "la captura no llegó a tmp"
    # La ruta que devuelve el endpoint es la que el usuario copia y pega: si
    # apuntara a los datos reales, la huella de arriba no lo vería (el fichero
    # se habría creado, pero también se habría creado en tmp).
    assert Path(resp.json()["path"]).is_relative_to(data_dir)


def test_la_config_viene_del_entorno_de_test_y_no_del_env_del_usuario() -> None:
    """`backend/.env` es el despliegue real: los tests no heredan nada de él."""
    assert config.AUTH_MODE == "env"
    assert config.AUTH_USERNAME == USERNAME
    assert config.CORS_ORIGINS == [ORIGIN]
    assert config.COOKIE_SECURE is False


def test_auth_arranca_sin_estado_previo() -> None:
    """Ni sesiones de otro test ni el histórico de IPs atacantes reales."""
    assert auth._sessions == {}
    assert auth._login_failures == {}


def test_los_dos_clientes_hacen_lo_que_prometen(client, request) -> None:
    """`client` autentica y `client_no_auth` no; US-002 y US-005 usan ambos."""
    assert client.get("/api/me").status_code == 401
    # `client_no_auth` se pide a mano y DESPUÉS de la aserción anterior:
    # apagar la auth es cambiar un global del módulo, compartido por los dos
    # clientes. Pedirlo en la firma lo apagaría antes de empezar el test y el
    # 401 de arriba nunca llegaría a ocurrir.
    sin_auth = request.getfixturevalue("client_no_auth")
    assert sin_auth.get("/api/me").json() == {"user": "anonymous"}
