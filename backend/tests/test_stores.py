"""Los tres stores de `backend/data/`: CRUD, JSON roto y escritura atómica.

`library_store`, `space_store` y `upload_store` guardan lo único del panel que
no se puede regenerar: los comandos que el usuario ejecuta con un clic, cómo
tiene organizadas sus terminales y dónde dejó los últimos archivos que subió.
No hay copia de seguridad, no hay base de datos, no hay migración: hay un JSON
por store y el que lo escribe es el propio backend.

## La regla que unifica casi todo este archivo

**Leer nunca lanza. Escribir nunca deja el archivo a medias.**

Las dos mitades protegen del mismo desastre por caminos distintos. Si leer
lanzara, un solo byte corrupto —un disco lleno, un `kill -9` en el momento
justo, un editor que guardó mal— dejaría el panel devolviendo 500 en cada
carga en vez de arrancar vacío y dejar al usuario rehacer lo perdido. Si
escribir no fuera atómico, ese byte corrupto lo produciría el propio panel.

Cada test de aquí abajo comprueba una de las dos. Los de CRUD y validación
existen porque una lectura tolerante también tiene que **conservar lo bueno**:
un store que devolviera vacío siempre pasaría todos los tests de "JSON roto"
del archivo y habría perdido la biblioteca entera.

## Por qué el test de atomicidad es el importante

Los tres stores comparten hoy `datafiles.write_private` (tmp + `replace` +
0600). **Antes no**: `upload_store` y `space_store` reescribían el JSON en
sitio, con un `open(...,"w")` sobre el fichero bueno. Ese patrón no falla casi
nunca y, cuando falla, se lleva los datos: entre el `O_TRUNC` y el último byte
escrito el archivo del usuario está vacío o cortado por la mitad.

`test_si_falla_la_escritura_del_temporal_el_fichero_anterior_queda_intacto` es
el que impide volver ahí. Provoca el fallo de verdad —sustituye el `os` que ve
`datafiles` por uno cuyo `write` escribe unos bytes y revienta— y exige las dos
consecuencias del tmp + replace: el fichero anterior sigue byte a byte como
estaba, y no queda un `.tmp` huérfano. Con la escritura en sitio, ese mismo
sabotaje corrompe el fichero; lo demuestra el auto-test
`test_auto_con_la_escritura_en_sitio_de_antes_una_caida_corrompe_el_fichero`,
que ejecuta una réplica del código de entonces sobre el mismo escenario.

## El andamiaje y su trampa

El sabotaje sustituye **`datafiles.os`** (el atributo del módulo) por un proxy,
y NO `datafiles.os.fdopen`. La diferencia importa: `datafiles.py` hace
`import os`, así que `datafiles.os` **es** el módulo `os` del intérprete y
parchearle un atributo se lo parchearía a pytest, a httpx y a todo lo demás
—la misma trampa que documenta `test_auth.py` con `auth.time`—. Con el proxy,
el sabotaje solo lo ve `write_private`;
`test_auto_el_sabotaje_no_se_filtra_al_resto_del_proceso` lo comprueba.

## Qué se prueba y qué no

- Se prueba el **contrato público** (`add_command`, `create_space`,
  `list_recent`…), no `_load` ni `_persist`. La única excepción es el bloque de
  atomicidad, que necesita provocar el fallo a bajo nivel: eso no se puede
  observar desde fuera.
- No se prueba concurrencia. Los locks de los stores son de proceso a
  propósito (un solo worker, requisito documentado); dos procesos escribiendo
  a la vez es otra historia.
- No se prueban los endpoints HTTP que envuelven a los stores.

## Los dos huecos que destapó esta historia

La mitad "leer nunca lanza" tenía dos grietas, descubiertas al escribir estos
tests y fijadas en su día con `xfail(strict=True)` para que el arreglo no
pudiera colarse sin que nadie actualizara el test.

1. **UTF-8 cortado a media escritura, en los tres stores** (S15). Los tres
   leían con `read_text(encoding="utf-8")` y capturaban
   `(json.JSONDecodeError, OSError)`. `UnicodeDecodeError` no es ninguna de las
   dos —es hermana de `JSONDecodeError` bajo `ValueError`—, así que un JSON
   cortado en medio de un carácter multibyte hacía que la lectura lanzara y el
   panel devolviera 500 en cada carga. Y era el caso probable, no el exótico:
   se serializa con `ensure_ascii=False` y el propio `_default_label` mete una
   "…". Es exactamente el desperfecto contra el que existe el tmp + replace,
   visto desde el otro lado. **Corregido**: los tres capturan `ValueError`, y
   el `xfail` de abajo es hoy un test de regresión normal.

2. **`spaces.json` que es JSON válido pero no un objeto** (S16).
   `space_store._read()` llamaba a `raw.get("spaces")` sin comprobar antes que
   `raw` fuera un `dict`: una lista, un número o `null` hacían que
   `list_spaces()` lanzara `AttributeError`. `library_store` y `upload_store`
   sí comprobaban el tipo — era una asimetría, no una decisión. **Corregido**:
   `space_store` hace el mismo `isinstance`, y su `xfail` es hoy un test de
   regresión normal.

Con las dos cerradas, "leer nunca lanza" vuelve a ser cierto en los tres
stores para cualquier contenido de disco.
"""
from __future__ import annotations

import errno
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, NamedTuple

import pytest

import datafiles
import library_store
import space_store
import upload_store

# ----------------------------------------------------------------------
# Constantes del contrato, DECLARADAS aquí y no importadas de los módulos
# bajo prueba. Es contabilidad por partida doble, como en `test_upload.py`:
# leerlas del propio código haría que cambiar un límite actualizara a la vez
# el hecho y su comprobación, y la suite seguiría en verde sin que nadie lo
# revisara.
# ----------------------------------------------------------------------

# Longitud máxima del título de un espacio.
MAX_TITULO_ESPACIO = 60

# Longitud máxima de la etiqueta que se genera sola a partir de un comando.
MAX_ETIQUETA = 60

# Cuántas subidas recuerda el historial.
KEEP_SUBIDAS = 5

# Permisos que deben quedar en disco: nadie más que el dueño.
MODO_FICHERO = 0o600
MODO_DIRECTORIO = 0o700

# Bytes que el sabotaje deja escritos antes de reventar. Escribir ALGO (y no
# fallar de entrada) es lo que hace que el escenario distinga entre las dos
# implementaciones: con la escritura en sitio, esos bytes acaban en el fichero
# bueno y lo dejan cortado; con tmp + replace, en un temporal que se borra.
BYTES_ANTES_DE_REVENTAR = 8


# ======================================================================
# Andamiaje: sabotear la escritura sin sabotear el intérprete.
# ======================================================================


class _FicheroQueRevienta:
    """Fichero binario que escribe unos bytes y luego falla, como un disco lleno.

    Escribe DE VERDAD (y hace `flush`) antes de lanzar: lo que se simula no es
    "la escritura no ocurrió", que es el caso fácil, sino "la escritura ocurrió
    a medias", que es el que corrompe datos.
    """

    def __init__(self, fh, prefijo: int) -> None:
        self._fh = fh
        self._prefijo = prefijo

    def write(self, datos: bytes) -> int:
        self._fh.write(datos[: self._prefijo])
        self._fh.flush()
        raise OSError(errno.ENOSPC, "no queda espacio en el dispositivo")

    def __enter__(self) -> "_FicheroQueRevienta":
        return self

    def __exit__(self, *exc) -> bool:
        # Cerrar aquí es parte del contrato del `with` de `write_private`: sin
        # esto el descriptor quedaría abierto y el fallo del test sería un
        # ResourceWarning y no la aserción que interesa.
        self._fh.close()
        return False


class _OsConEscrituraRota:
    """Proxy del módulo `os` en el que solo `fdopen` está trucado.

    Todo lo demás (`open`, `chmod`, las constantes `O_*`) se delega al `os` de
    verdad: el objetivo es que `write_private` haga exactamente lo que hace
    siempre hasta el momento de escribir los bytes.
    """

    def __init__(self, real, prefijo: int) -> None:
        self._real = real
        self._prefijo = prefijo

    def __getattr__(self, nombre: str):
        return getattr(self._real, nombre)

    def fdopen(self, fd: int, *args, **kwargs) -> _FicheroQueRevienta:
        return _FicheroQueRevienta(
            self._real.fdopen(fd, *args, **kwargs), self._prefijo
        )


@contextmanager
def _escritura_del_temporal_rota(
    prefijo: int = BYTES_ANTES_DE_REVENTAR,
) -> Iterator[None]:
    """Hace que toda escritura de `datafiles` falle a mitad, y solo ahí.

    Se sustituye el ATRIBUTO `datafiles.os` entero, no `datafiles.os.fdopen`.
    `datafiles.py` hace `import os`, o sea que `datafiles.os` es el módulo
    global del intérprete: tocarle un atributo se lo tocaría también a pytest,
    a httpx y a cualquier otra cosa que esté corriendo. Ver el auto-test de más
    abajo, que mide precisamente eso.
    """
    real = datafiles.os
    datafiles.os = _OsConEscrituraRota(real, prefijo)
    try:
        yield
    finally:
        datafiles.os = real


def _escritura_en_sitio_como_antes(sistema, path: Path, datos: bytes) -> None:
    """Réplica de la escritura de `upload_store`/`space_store` ANTES del arreglo.

    Sin temporal: se trunca el fichero bueno y se escribe encima. Se copia
    aquí en vez de reutilizar nada de `datafiles` para que siga siendo la
    mutación que dice ser aunque `datafiles.py` cambie por dentro.

    `sistema` es el módulo `os` a usar; los tests le pasan `datafiles.os` para
    que el sabotaje —que solo afecta a ese atributo— también la alcance.
    """
    fd = sistema.open(path, sistema.O_WRONLY | sistema.O_CREAT | sistema.O_TRUNC, 0o600)
    with sistema.fdopen(fd, "wb") as fh:
        fh.write(datos)


@contextmanager
def _umask(valor: int) -> Iterator[int]:
    """Fija el umask del proceso y lo restaura pase lo que pase."""
    previo = os.umask(valor)
    try:
        yield previo
    finally:
        os.umask(previo)


def _modo(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _temporales(raiz: Path) -> list[Path]:
    return sorted(raiz.rglob("*.tmp"))


# ======================================================================
# Descriptor de los tres stores, para los tests transversales.
#
# El bloque de atomicidad y permisos dice lo mismo de los tres, y decirlo
# tres veces a mano invita a que el cuarto store que se añada se quede sin
# cubrir. Cada entrada trae lo mínimo para ejercitarlo por su CONTRATO
# PÚBLICO: cómo escribir algo reconocible y cómo volver a leerlo.
# ======================================================================


class Store(NamedTuple):
    nombre: str
    # El `_STORE_PATH` se lee tarde, con un lambda: el conftest lo reapunta a
    # `tmp_path` en cada test, así que capturarlo al importar daría la ruta
    # REAL del usuario.
    ruta: Callable[[], Path]
    escribir: Callable[[str], object]
    leer: Callable[[], dict]
    vacio: dict
    # Lo que sale por la puerta cuando la escritura falla. `space_store`
    # traduce el `OSError` a un error de dominio; los otros dos lo dejan pasar.
    error_al_fallar: type[BaseException]


STORES = [
    Store(
        nombre="library_store",
        ruta=lambda: library_store._STORE_PATH,
        escribir=lambda marca: library_store.add_command(marca, f"echo {marca}"),
        leer=lambda: {
            "commands": [c.label for c in library_store.list_commands()],
            "projects": [p.title for p in library_store.list_projects()],
        },
        vacio={"commands": [], "projects": []},
        error_al_fallar=OSError,
    ),
    Store(
        nombre="space_store",
        ruta=lambda: space_store._STORE_PATH,
        escribir=lambda marca: space_store.create_space(marca),
        leer=lambda: {
            "spaces": [s.title for s in space_store.list_spaces()],
            "assignments": space_store.assignments(),
        },
        vacio={"spaces": [], "assignments": {}},
        error_al_fallar=space_store.SpaceError,
    ),
    Store(
        nombre="upload_store",
        ruta=lambda: upload_store._STORE_PATH,
        escribir=lambda marca: upload_store.add(marca, f"/destino/{marca}", "/destino"),
        leer=lambda: {"recientes": [i["name"] for i in upload_store.list_recent()]},
        vacio={"recientes": []},
        error_al_fallar=OSError,
    ),
]

_IDS_STORES = [s.nombre for s in STORES]


def _con_marca(store: Store, marca: str) -> dict:
    """Cómo se ve `leer()` tras escribir una sola entrada llamada `marca`."""
    esperado = dict(store.vacio)
    for clave, valor in esperado.items():
        if isinstance(valor, list):
            esperado[clave] = [marca]
            break
    return esperado


# ======================================================================
# Auto-tests: que el andamiaje distingue lo que dice distinguir.
# ======================================================================


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_auto_los_tres_stores_escriben_dentro_del_tmp_del_test(
    store: Store, data_dir: Path, tmp_path: Path
) -> None:
    """La comprobación que va ANTES que cualquier otra cosa de este archivo.

    `library.json` son literalmente los comandos que el panel ejecuta. Un
    archivo de tests que los reescribiera en `backend/data/` sería peor que no
    tener tests. `test_aislamiento.py` ya vigila las rutas; aquí se comprueba
    el efecto para estos tres stores en concreto: se escribe de verdad y el
    fichero aparece en el tmp de ESTE test.
    """
    ruta = store.ruta()
    assert ruta.resolve().is_relative_to(tmp_path.resolve()), (
        f"{store.nombre}._STORE_PATH apunta a {ruta}, fuera del tmp del test"
    )
    assert not ruta.exists(), "el store arranca sin fichero, sin estado heredado"

    store.escribir("centinela")

    assert ruta.is_file()
    assert ruta.parent == data_dir
    assert "centinela" in ruta.read_text(encoding="utf-8")


def test_auto_el_sabotaje_no_se_filtra_al_resto_del_proceso(tmp_path: Path) -> None:
    """El proxy solo lo ve `datafiles`, y solo mientras dura el `with`.

    Si en vez del atributo `datafiles.os` se parcheara `os.fdopen`, dentro del
    bloque no podría escribir NADA el intérprete: ni pytest sus informes ni
    httpx sus buffers. Y si el proxy no se restaurara al salir, todos los tests
    posteriores del archivo estarían corriendo con la escritura rota.
    """
    testigo = tmp_path / "testigo.txt"

    with _escritura_del_temporal_rota():
        with pytest.raises(OSError):
            datafiles.write_private(tmp_path / "roto.json", b"x" * 100)
        # El `os` del resto del intérprete sigue escribiendo entero.
        fd = os.open(testigo, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(b"esto se escribe completo")

    assert testigo.read_bytes() == b"esto se escribe completo"

    # Y al salir del bloque, `datafiles` vuelve a la normalidad.
    datafiles.write_private(tmp_path / "bueno.json", b"contenido completo")
    assert (tmp_path / "bueno.json").read_bytes() == b"contenido completo"


def test_auto_con_la_escritura_en_sitio_de_antes_una_caida_corrompe_el_fichero(
    data_dir: Path,
) -> None:
    """La prueba de que el detector detecta.

    Ejecuta la réplica del código anterior al arreglo —un `O_TRUNC` sobre el
    fichero bueno— bajo el MISMO sabotaje que usan los tests de atomicidad, y
    comprueba que **sí** destroza el contenido anterior. Mientras esta aserción
    siga en verde, `test_si_falla_la_escritura_del_temporal...` no puede estar
    pasando por casualidad: el escenario distingue de verdad entre escribir en
    sitio y escribir en un temporal.
    """
    ruta = data_dir / "en-sitio.json"
    anterior = b'{"commands": [{"id": "abc", "label": "importante"}]}'
    ruta.write_bytes(anterior)
    nuevo = b'{"commands": [{"id": "abc", "label": "actualizado"}]}'

    with _escritura_del_temporal_rota():
        with pytest.raises(OSError):
            _escritura_en_sitio_como_antes(datafiles.os, ruta, nuevo)

    quedo = ruta.read_bytes()
    assert quedo != anterior, (
        "la réplica de la escritura en sitio ya no corrompe el fichero; el "
        "escenario ha dejado de discriminar y los tests de atomicidad de este "
        "archivo han perdido su valor"
    )
    assert quedo == nuevo[:BYTES_ANTES_DE_REVENTAR], "quedó cortado a media escritura"
    with pytest.raises(json.JSONDecodeError):
        json.loads(quedo)


# ======================================================================
# library_store · CRUD de comandos.
# ======================================================================


def test_biblioteca_el_ciclo_completo_de_un_comando(data_dir: Path) -> None:
    """Crear, listar, obtener, actualizar y borrar, comprobando el disco.

    Es el control positivo de todo el bloque de `library_store`: sin él, una
    biblioteca que no guardara nada pasaría todos los tests de "JSON roto →
    vacío" de más abajo.
    """
    creado = library_store.add_command("Desplegar", "make deploy")

    assert creado.label == "Desplegar"
    assert creado.command == "make deploy"
    assert creado.id, "todo comando nace con un id"
    assert library_store.list_commands() == [creado]
    assert library_store.get_command(creado.id) == creado

    actualizado = library_store.update_command(
        creado.id, "Desplegar a prod", "make prod"
    )

    assert actualizado is not None
    assert actualizado.id == creado.id, "actualizar no cambia el id"
    assert (actualizado.label, actualizado.command) == ("Desplegar a prod", "make prod")
    # Y se persistió: se relee de disco, no de un caché en memoria.
    assert library_store.get_command(creado.id) == actualizado

    assert library_store.delete_command(creado.id) is True
    assert library_store.list_commands() == []
    assert library_store.get_command(creado.id) is None
    # El fichero sigue ahí, con la biblioteca vacía: borrar no es "olvidar el
    # archivo", es dejarlo consistente.
    assert json.loads(library_store._STORE_PATH.read_text(encoding="utf-8")) == {
        "commands": [],
        "projects": [],
    }


def test_biblioteca_los_comandos_conservan_el_orden_de_insercion_y_no_repiten_id(
    data_dir: Path,
) -> None:
    """El orden es el que ve el usuario en el panel; el id es la clave."""
    creados = [library_store.add_command(f"C{i}", f"echo {i}") for i in range(5)]

    assert [c.label for c in library_store.list_commands()] == [
        "C0",
        "C1",
        "C2",
        "C3",
        "C4",
    ]
    ids = [c.id for c in creados]
    assert len(set(ids)) == len(ids), (
        "dos comandos con el mismo id se pisarían al borrar"
    )


def test_biblioteca_borrar_un_comando_inexistente_devuelve_false_sin_tocar_nada(
    data_dir: Path,
) -> None:
    """`False`, no una excepción: el panel lo traduce a un 404, no a un 500.

    Y lo que había sigue estando: un "borrar" que no encuentra su objetivo no
    puede llevarse por delante el resto de la biblioteca.
    """
    superviviente = library_store.add_command("Queda", "echo queda")
    antes = library_store._STORE_PATH.read_bytes()

    assert library_store.delete_command("id-que-no-existe") is False

    assert library_store.list_commands() == [superviviente]
    assert library_store._STORE_PATH.read_bytes() == antes, "reescribió el fichero"


def test_biblioteca_actualizar_un_comando_inexistente_devuelve_none(
    data_dir: Path,
) -> None:
    """Mismo criterio que borrar: `None`, y sin crear el comando de la nada."""
    superviviente = library_store.add_command("Queda", "echo queda")

    assert library_store.update_command("id-fantasma", "X", "echo x") is None

    assert library_store.list_commands() == [superviviente]


@pytest.mark.parametrize(
    "texto",
    ["", "   ", "\t\n ", None],
    ids=["vacio", "espacios", "blancos", "none"],
)
def test_biblioteca_un_comando_sin_texto_se_rechaza_y_no_escribe(
    data_dir: Path, texto
) -> None:
    """Un comando vacío es una fila en el panel que no hace nada al pulsarla.

    Se comprueba también que la validación ocurre ANTES de tocar disco: un
    rechazo que dejara el fichero creado (o modificado) sería medio rechazo.
    """
    with pytest.raises(library_store.LibraryError) as exc:
        library_store.add_command("Etiqueta", texto)

    assert exc.value.code == "err.command_empty"
    assert not library_store._STORE_PATH.exists(), "se escribió pese al rechazo"


def test_biblioteca_actualizar_con_un_comando_vacio_tampoco_pasa(
    data_dir: Path,
) -> None:
    """La validación es de las dos puertas, no solo de la de crear.

    Vaciar el texto de un comando existente es la vía por la que se colaría un
    comando vacío si solo se validara en `add_command`.
    """
    creado = library_store.add_command("Desplegar", "make deploy")

    with pytest.raises(library_store.LibraryError) as exc:
        library_store.update_command(creado.id, "Desplegar", "   ")

    assert exc.value.code == "err.command_empty"
    assert library_store.get_command(creado.id) == creado, "el original cambió"


def test_biblioteca_un_comando_sin_etiqueta_recibe_el_propio_comando_como_etiqueta(
    data_dir: Path,
) -> None:
    """Sin etiqueta la fila saldría en blanco: se usa el comando como nombre."""
    creado = library_store.add_command("", "git status")

    assert creado.label == "git status"
    assert library_store.get_command(creado.id).label == "git status"

    # También al actualizar, y también si la etiqueta es solo espacios.
    actualizado = library_store.update_command(creado.id, "   ", "git log")
    assert actualizado.label == "git log"


def test_biblioteca_una_etiqueta_generada_se_recorta_con_puntos_suspensivos(
    data_dir: Path,
) -> None:
    """El límite es de presentación: la etiqueta va en un botón, el comando no.

    La frontera está en `MAX_ETIQUETA`: exactamente ese largo entra entero, uno
    más se recorta. El recorte deja 57 caracteres + "…" (58 en total, dentro
    del máximo prometido) y NO toca el comando, que se guarda completo — que es
    lo importante: lo que se ejecuta no puede quedar truncado.
    """
    justo = "x" * MAX_ETIQUETA
    entero = library_store.add_command("", justo)
    assert entero.label == justo, "un comando en el límite no se recorta"

    largo = "y" * (MAX_ETIQUETA + 1)
    recortado = library_store.add_command("", largo)

    assert recortado.label.endswith("…")
    assert len(recortado.label) <= MAX_ETIQUETA
    assert recortado.label == largo[:57] + "…"
    assert recortado.command == largo, "el comando SÍ se guarda entero"
    # Y sobrevive al viaje por disco, que es donde se podría perder la "…".
    assert library_store.get_command(recortado.id).label == recortado.label


def test_biblioteca_una_etiqueta_dada_por_el_usuario_no_se_recorta(
    data_dir: Path,
) -> None:
    """El control negativo del recorte: el límite es de la etiqueta AUTOMÁTICA.

    Sin esto, un `strip` de 60 aplicado a todas las etiquetas pasaría el test
    anterior y estaría truncando en silencio lo que el usuario escribió.
    """
    etiqueta = "E" * 200
    creado = library_store.add_command(etiqueta, "echo x")

    assert creado.label == etiqueta
    assert library_store.get_command(creado.id).label == etiqueta


# ======================================================================
# library_store · CRUD de proyectos.
# ======================================================================


def test_biblioteca_el_ciclo_completo_de_un_proyecto(data_dir: Path) -> None:
    """Crear, listar, obtener, actualizar y borrar un proyecto."""
    creado = library_store.add_project("Panel", "/srv/panel", ["bun dev", "bun test"])

    assert (creado.title, creado.cwd, creado.commands) == (
        "Panel",
        "/srv/panel",
        ["bun dev", "bun test"],
    )
    assert library_store.list_projects() == [creado]
    assert library_store.get_project(creado.id) == creado

    actualizado = library_store.update_project(
        creado.id, "Panel v2", "/srv/panel2", ["bun run build"]
    )

    assert actualizado is not None
    assert actualizado.id == creado.id
    assert actualizado.commands == ["bun run build"]
    assert library_store.get_project(creado.id) == actualizado

    assert library_store.delete_project(creado.id) is True
    assert library_store.list_projects() == []
    assert library_store.get_project(creado.id) is None


def test_biblioteca_borrar_o_actualizar_un_proyecto_inexistente_no_lanza(
    data_dir: Path,
) -> None:
    """`False` y `None`, igual que con los comandos."""
    superviviente = library_store.add_project("Queda", None, ["echo x"])

    assert library_store.delete_project("id-fantasma") is False
    assert library_store.update_project("id-fantasma", "X", None, ["echo y"]) is None
    assert library_store.list_projects() == [superviviente]


@pytest.mark.parametrize(
    "titulo",
    ["", "   ", None],
    ids=["vacio", "espacios", "none"],
)
def test_biblioteca_un_proyecto_sin_titulo_se_rechaza_y_no_escribe(
    data_dir: Path, titulo
) -> None:
    """El título es lo único que identifica al proyecto en el panel."""
    with pytest.raises(library_store.LibraryError) as exc:
        library_store.add_project(titulo, "/srv", ["echo x"])

    assert exc.value.code == "err.project_title_required"
    assert not library_store._STORE_PATH.exists()


@pytest.mark.parametrize(
    "comandos",
    [[], ["", "   "], None, "no es una lista"],
    ids=["lista-vacia", "solo-blancos", "none", "no-es-lista"],
)
def test_biblioteca_un_proyecto_sin_comandos_se_rechaza_y_no_escribe(
    data_dir: Path, comandos
) -> None:
    """Un proyecto sin comandos es un botón "lanzar" que no lanza nada.

    Los blancos cuentan como ausencia: `["", "  "]` se normaliza a lista vacía
    antes de validar, no después.
    """
    with pytest.raises(library_store.LibraryError) as exc:
        library_store.add_project("Panel", "/srv", comandos)

    assert exc.value.code == "err.project_needs_command"
    assert not library_store._STORE_PATH.exists()


def test_biblioteca_actualizar_un_proyecto_con_datos_invalidos_no_lo_estropea(
    data_dir: Path,
) -> None:
    """La misma validación en la puerta de actualizar, y el original intacto."""
    creado = library_store.add_project("Panel", "/srv", ["bun dev"])

    for kwargs, codigo in (
        (
            dict(title="", cwd="/srv", commands=["bun dev"]),
            "err.project_title_required",
        ),
        (dict(title="Panel", cwd="/srv", commands=[]), "err.project_needs_command"),
    ):
        with pytest.raises(library_store.LibraryError) as exc:
            library_store.update_project(creado.id, **kwargs)
        assert exc.value.code == codigo

    assert library_store.get_project(creado.id) == creado


def test_biblioteca_el_cwd_en_blanco_se_normaliza_a_none(data_dir: Path) -> None:
    """`""` y `None` son lo mismo: "sin directorio", no "el directorio vacío".

    Si `""` llegara tal cual al disco, el lanzador acabaría haciendo `cd ""`.
    """
    for cwd in ("", "   ", None):
        creado = library_store.add_project(f"P{cwd!r}", cwd, ["echo x"])
        assert creado.cwd is None
        assert library_store.get_project(creado.id).cwd is None

    # Y el control positivo: un cwd de verdad se conserva con sus espacios.
    con_cwd = library_store.add_project("Con cwd", "/srv/mi panel", ["echo x"])
    assert library_store.get_project(con_cwd.id).cwd == "/srv/mi panel"


def test_biblioteca_los_comandos_de_un_proyecto_se_limpian_conservando_el_orden(
    data_dir: Path,
) -> None:
    """Se descartan los huecos, no se reordena ni se deduplica.

    El orden es la semántica: un proyecto ejecuta sus comandos en secuencia.
    Y repetir un comando es legítimo (`make clean`, `make`, `make clean`).
    """
    creado = library_store.add_project(
        "  Panel  ", "/srv", ["  bun dev  ", "", "   ", "bun test", "bun dev"]
    )

    assert creado.title == "Panel", "el título se recorta por los extremos"
    assert creado.commands == ["bun dev", "bun test", "bun dev"]


def test_biblioteca_comandos_y_proyectos_conviven_sin_pisarse(data_dir: Path) -> None:
    """Los dos CRUD escriben el MISMO fichero: borrar en uno no vacía el otro.

    Es el riesgo real de persistir dos colecciones en un solo JSON reescrito
    entero en cada mutación.
    """
    comando = library_store.add_command("Estado", "git status")
    proyecto = library_store.add_project("Panel", "/srv", ["bun dev"])

    assert library_store.list_commands() == [comando]
    assert library_store.list_projects() == [proyecto]

    library_store.delete_command(comando.id)

    assert library_store.list_commands() == []
    assert library_store.list_projects() == [proyecto], (
        "borrar un comando se llevó el proyecto"
    )


def test_biblioteca_el_formato_en_disco_es_el_declarado(data_dir: Path) -> None:
    """Contabilidad por partida doble sobre el JSON que queda en `data/`.

    Es el formato que tienen ya en su máquina los usuarios del panel: cambiarlo
    sin migración les vacía la biblioteca. Escrito a mano aquí para que tocarlo
    aparezca en el diff.
    """
    comando = library_store.add_command("Estado", "git status")
    proyecto = library_store.add_project("Panel", "/srv", ["bun dev"])

    assert json.loads(library_store._STORE_PATH.read_text(encoding="utf-8")) == {
        "commands": [{"id": comando.id, "label": "Estado", "command": "git status"}],
        "projects": [
            {
                "id": proyecto.id,
                "title": "Panel",
                "cwd": "/srv",
                "commands": ["bun dev"],
            }
        ],
    }


# ======================================================================
# library_store · leer nunca lanza.
# ======================================================================


def test_biblioteca_un_json_valido_escrito_a_mano_se_lee_entero(data_dir: Path) -> None:
    """El control positivo de todos los tests de "JSON roto" que vienen ahora.

    Sin este, un `_load_raw` que devolviera siempre vacío los pasaría todos y
    la biblioteca del usuario estaría perdida en cada arranque.
    """
    library_store._STORE_PATH.write_text(
        json.dumps(
            {
                "commands": [{"id": "c1", "label": "Estado", "command": "git status"}],
                "projects": [
                    {
                        "id": "p1",
                        "title": "Panel",
                        "cwd": "/srv",
                        "commands": ["bun dev"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    assert library_store.list_commands() == [
        library_store.Command(id="c1", label="Estado", command="git status")
    ]
    assert library_store.list_projects() == [
        library_store.Project(id="p1", title="Panel", cwd="/srv", commands=["bun dev"])
    ]


# Cada uno rompe el JSON de una forma distinta: truncado a media escritura (el
# síntoma clásico del `kill -9` sin tmp + replace), basura de texto, un fichero
# de cero bytes (el `O_TRUNC` que no llegó a escribir nada) y llaves de más.
# Todos son UTF-8 válido: el caso que NO lo es tiene su propio bloque al final
# del archivo, porque hoy no se tolera.
JSON_ILEGIBLE = [
    b'{"commands": [{"id": "c1", "lab',
    b"esto no es json ni de lejos",
    b"",
    b"{}}",
]
_IDS_ILEGIBLE = ["truncado", "texto-suelto", "vacio", "llaves-de-mas"]

# JSON perfectamente válido, pero que no es el objeto que el store espera.
# Que sea válido importa: pasa el `json.loads` y el fallo, si lo hay, ocurre
# después — al ir a leerle campos a algo que no los tiene.
JSON_QUE_NO_ES_UN_OBJETO = [b"[1, 2, 3]", b"42", b"null", b'"una cadena"', b"true"]
_IDS_NO_OBJETO = ["lista", "numero", "null", "cadena", "booleano"]


@pytest.mark.parametrize("contenido", JSON_ILEGIBLE, ids=_IDS_ILEGIBLE)
def test_biblioteca_un_json_ilegible_da_biblioteca_vacia_sin_lanzar(
    data_dir: Path, contenido: bytes
) -> None:
    """Arrancar vacío es recuperable; devolver 500 en cada carga no lo es."""
    library_store._STORE_PATH.write_bytes(contenido)

    assert library_store.list_commands() == []
    assert library_store.list_projects() == []
    assert library_store.get_command("c1") is None
    assert library_store.get_project("p1") is None


@pytest.mark.parametrize("contenido", JSON_QUE_NO_ES_UN_OBJETO, ids=_IDS_NO_OBJETO)
def test_biblioteca_un_json_que_no_es_un_objeto_da_biblioteca_vacia(
    data_dir: Path, contenido: bytes
) -> None:
    """`json.loads` lo acepta; el store tiene que comprobar el tipo igualmente."""
    library_store._STORE_PATH.write_bytes(contenido)

    assert library_store.list_commands() == []
    assert library_store.list_projects() == []


def test_biblioteca_las_entradas_malformadas_se_descartan_y_las_buenas_se_conservan(
    data_dir: Path,
) -> None:
    """EL test de la tolerancia: se tira lo roto, NO el archivo entero.

    Un `_load_raw` que devolviera vacío ante la primera entrada rara pasaría
    todos los tests de arriba y perdería la biblioteca por un solo registro
    corrupto. Aquí se mezclan las dos cosas a propósito.
    """
    library_store._STORE_PATH.write_text(
        json.dumps(
            {
                "commands": [
                    {"id": "ok1", "label": "Buena", "command": "echo ok"},
                    {"id": "sin-comando", "label": "Rota"},  # sin `command`
                    {"id": "comando-vacio", "label": "Rota", "command": "   "},
                    "esto no es un dict",
                    None,
                    ["tampoco"],
                    {
                        "id": "sin-etiqueta",
                        "command": "git status",
                    },  # etiqueta a medias
                    {"id": "ok2", "label": "Buena2", "command": "echo ok2"},
                ],
                "projects": [
                    {"id": "p-ok", "title": "Bueno", "cwd": "/srv", "commands": ["a"]},
                    {"id": "p-sin-titulo", "commands": ["a"]},  # sin `title`
                    {"id": "p-titulo-vacio", "title": "  ", "commands": ["a"]},
                    42,
                    {"id": "p-ok2", "title": "Bueno2", "commands": ["b", "", "c"]},
                ],
                "sobra": "una clave desconocida no molesta",
            }
        ),
        encoding="utf-8",
    )

    comandos = library_store.list_commands()
    assert [c.id for c in comandos] == ["ok1", "sin-etiqueta", "ok2"]
    # La entrada sin etiqueta no se descarta: se le genera una, como al crearla.
    assert comandos[1].label == "git status"

    proyectos = library_store.list_projects()
    assert [p.id for p in proyectos] == ["p-ok", "p-ok2"]
    assert proyectos[1].commands == ["b", "c"], "los comandos vacíos se limpian al leer"


def test_biblioteca_un_proyecto_sin_comandos_en_disco_se_conserva_vacio(
    data_dir: Path,
) -> None:
    """Documenta una asimetría deliberada entre escribir y leer.

    `add_project` exige al menos un comando, pero al LEER un proyecto sin
    comandos se conserva (con la lista vacía) en vez de descartarse. Es
    coherente con la regla del archivo —leer conserva todo lo que pueda— y se
    fija aquí para que cambiar de idea sea un acto consciente: descartarlo haría
    desaparecer del panel un proyecto que el usuario sí ve hoy.
    """
    library_store._STORE_PATH.write_text(
        json.dumps(
            {"projects": [{"id": "p1", "title": "Sin comandos", "commands": []}]}
        ),
        encoding="utf-8",
    )

    proyectos = library_store.list_projects()
    assert [p.id for p in proyectos] == ["p1"]
    assert proyectos[0].commands == []


def test_biblioteca_escribir_sobre_un_json_roto_lo_deja_consistente(
    data_dir: Path,
) -> None:
    """La otra mitad de "leer nunca lanza": el archivo se puede recuperar.

    Tolerar la basura no serviría de nada si el store se quedara atascado
    leyéndola para siempre. La primera escritura tiene que dejar un JSON válido.
    """
    library_store._STORE_PATH.write_bytes(b"{basura a medias")

    creado = library_store.add_command("Nuevo", "echo nuevo")

    assert library_store.list_commands() == [creado]
    assert json.loads(library_store._STORE_PATH.read_text(encoding="utf-8")) == {
        "commands": [creado.to_dict()],
        "projects": [],
    }


# ======================================================================
# space_store · crear, renombrar y borrar espacios.
# ======================================================================


def test_espacios_el_ciclo_completo_de_un_espacio(data_dir: Path) -> None:
    """Crear, listar, renombrar y borrar. El control positivo del bloque."""
    creado = space_store.create_space("Clientes")

    assert creado.title == "Clientes"
    assert creado.id.startswith("sp_"), "el prefijo distingue el id de un nombre"
    assert space_store.list_spaces() == [creado]

    renombrado = space_store.update_space(creado.id, "Clientes 2026")

    assert renombrado.id == creado.id, "renombrar no cambia el id"
    assert renombrado.title == "Clientes 2026"
    assert renombrado.order == creado.order, "ni el orden"
    assert space_store.list_spaces() == [renombrado]

    space_store.delete_space(creado.id)

    assert space_store.list_spaces() == []


def test_espacios_el_orden_se_asigna_solo_y_manda_en_el_listado(data_dir: Path) -> None:
    """`order` fija la posición en el selector; se autoincrementa al crear.

    Se comprueba con títulos en orden alfabético INVERSO al de creación: si el
    listado ordenara por título, este test lo cazaría.
    """
    primero = space_store.create_space("Zeta")
    segundo = space_store.create_space("Alfa")

    assert (primero.order, segundo.order) == (0, 1)
    assert [s.title for s in space_store.list_spaces()] == ["Zeta", "Alfa"]


def test_espacios_borrar_uno_inexistente_lanza_space_not_found(data_dir: Path) -> None:
    """Con el id en los params: el panel lo pinta en el mensaje traducido."""
    superviviente = space_store.create_space("Queda")

    with pytest.raises(space_store.SpaceError) as exc:
        space_store.delete_space("sp_fantasma")

    assert exc.value.code == "err.space_not_found"
    assert exc.value.params == {"id": "sp_fantasma"}
    assert space_store.list_spaces() == [superviviente], (
        "se llevó por delante otro espacio"
    )


def test_espacios_renombrar_uno_inexistente_lanza_space_not_found(
    data_dir: Path,
) -> None:
    """La otra puerta que busca por id, con el mismo criterio."""
    with pytest.raises(space_store.SpaceError) as exc:
        space_store.update_space("sp_fantasma", "Nombre nuevo")

    assert exc.value.code == "err.space_not_found"
    assert exc.value.params == {"id": "sp_fantasma"}
    assert space_store.list_spaces() == [], "creó el espacio en vez de fallar"


@pytest.mark.parametrize(
    "titulo", ["", "   ", "\t\n", None], ids=["vacio", "espacios", "blancos", "none"]
)
def test_espacios_un_titulo_vacio_se_rechaza_y_no_escribe(
    data_dir: Path, titulo
) -> None:
    """Un espacio sin nombre es una pestaña en blanco, y encima innombrable."""
    with pytest.raises(space_store.SpaceError) as exc:
        space_store.create_space(titulo)

    assert exc.value.code == "err.space_title_empty"
    assert not space_store._STORE_PATH.exists(), "se escribió pese al rechazo"


def test_espacios_un_titulo_demasiado_largo_se_rechaza_con_el_maximo_en_los_params(
    data_dir: Path,
) -> None:
    """El `max` viaja al cliente: el mensaje traducido dice cuánto sobra.

    Se prueban los dos lados de la frontera. Exactamente `MAX_TITULO_ESPACIO`
    entra —si no, un `>=` mal puesto pasaría desapercibido— y uno más no.
    """
    justo = "T" * MAX_TITULO_ESPACIO
    creado = space_store.create_space(justo)
    assert creado.title == justo

    with pytest.raises(space_store.SpaceError) as exc:
        space_store.create_space("T" * (MAX_TITULO_ESPACIO + 1))

    assert exc.value.code == "err.space_title_too_long"
    assert exc.value.params == {"max": MAX_TITULO_ESPACIO}
    assert [s.title for s in space_store.list_spaces()] == [justo]

    # Y la misma validación al renombrar, no solo al crear.
    with pytest.raises(space_store.SpaceError) as exc:
        space_store.update_space(creado.id, "T" * (MAX_TITULO_ESPACIO + 1))
    assert exc.value.code == "err.space_title_too_long"
    assert space_store.list_spaces() == [creado]


def test_espacios_el_titulo_se_recorta_por_los_extremos_antes_de_medirlo(
    data_dir: Path,
) -> None:
    """Los espacios de sobra no gastan cupo ni convierten un título en vacío."""
    creado = space_store.create_space("  " + "T" * MAX_TITULO_ESPACIO + "  ")

    assert creado.title == "T" * MAX_TITULO_ESPACIO


# ======================================================================
# space_store · asignación de sesiones.
# ======================================================================


def test_espacios_asignar_una_sesion_y_quitarle_la_asignacion(data_dir: Path) -> None:
    """El ciclo básico de la pertenencia. Control positivo del bloque."""
    espacio = space_store.create_space("Clientes")

    space_store.assign("sesion-1", espacio.id)

    assert space_store.assignments() == {"sesion-1": espacio.id}


@pytest.mark.parametrize(
    "sin_espacio",
    [None, "", space_store.UNASSIGNED],
    ids=["none", "cadena-vacia", "unassigned"],
)
def test_espacios_asignar_a_sin_asignar_quita_la_entrada(
    data_dir: Path, sin_espacio
) -> None:
    """ "Sin asignar" es virtual: no se guarda, se borra la entrada.

    Guardarlo como un id más haría que el espacio virtual apareciera en el JSON
    y que borrarlo fuera posible, que es justo lo que el diseño evita.
    """
    espacio = space_store.create_space("Clientes")
    space_store.assign("sesion-1", espacio.id)
    space_store.assign("sesion-2", espacio.id)

    space_store.assign("sesion-1", sin_espacio)

    assert space_store.assignments() == {"sesion-2": espacio.id}
    guardado = json.loads(space_store._STORE_PATH.read_text(encoding="utf-8"))
    assert space_store.UNASSIGNED not in guardado["assignments"].values()


def test_espacios_asignar_a_un_espacio_inexistente_lanza_y_no_deja_rastro(
    data_dir: Path,
) -> None:
    """Una asignación a un id fantasma haría desaparecer la sesión del panel.

    Quedaría en un espacio que no existe: no sale en "Sin asignar" (tiene
    entrada) ni en ningún espacio (no hay ninguno con ese id).
    """
    with pytest.raises(space_store.SpaceError) as exc:
        space_store.assign("sesion-1", "sp_fantasma")

    assert exc.value.code == "err.space_not_found"
    assert exc.value.params == {"id": "sp_fantasma"}
    assert not space_store._STORE_PATH.exists(), "escribió pese al rechazo"


def test_espacios_reasignar_una_sesion_la_mueve_y_no_la_duplica(data_dir: Path) -> None:
    """Cada sesión pertenece como mucho a un espacio: es carpetas, no etiquetas."""
    uno = space_store.create_space("Uno")
    dos = space_store.create_space("Dos")
    space_store.assign("sesion-1", uno.id)

    space_store.assign("sesion-1", dos.id)

    assert space_store.assignments() == {"sesion-1": dos.id}


def test_espacios_borrar_un_espacio_libera_sus_sesiones_y_no_toca_las_demas(
    data_dir: Path,
) -> None:
    """EL test del borrado: la operación destructiva de este store.

    Borrar una carpeta no destruye lo que hay dentro. Las sesiones del espacio
    borrado vuelven a "Sin asignar" (o sea: pierden su entrada) y las de los
    otros espacios se quedan exactamente donde estaban. Un borrado que vaciara
    `assignments` entero dejaría todas las terminales del usuario desordenadas.
    """
    borrado = space_store.create_space("A borrar")
    intacto = space_store.create_space("Intacto")
    space_store.assign("s1", borrado.id)
    space_store.assign("s2", borrado.id)
    space_store.assign("s3", intacto.id)

    space_store.delete_space(borrado.id)

    assert space_store.assignments() == {"s3": intacto.id}
    assert space_store.list_spaces() == [intacto]


def test_espacios_renombrar_una_sesion_arrastra_su_asignacion(data_dir: Path) -> None:
    """La pertenencia se indexa por NOMBRE de sesión, que tmux deja cambiar.

    Sin arrastrarla, renombrar en tmux sacaría la terminal de su espacio y
    dejaría en el JSON una entrada huérfana con el nombre viejo.
    """
    espacio = space_store.create_space("Clientes")
    otro = space_store.create_space("Otro")
    space_store.assign("vieja", espacio.id)
    space_store.assign("ajena", otro.id)

    space_store.rename_session("vieja", "nueva")

    assert space_store.assignments() == {"nueva": espacio.id, "ajena": otro.id}


def test_espacios_renombrar_una_sesion_sin_asignacion_no_escribe_nada(
    data_dir: Path,
) -> None:
    """Las sesiones de tmux creadas fuera del panel no tienen entrada.

    Renombrar una de ellas no puede inventarle una, ni crear el fichero: sería
    escribir en disco en cada `rename` de tmux para no guardar nada.
    """
    space_store.rename_session("desconocida", "otra")

    assert not space_store._STORE_PATH.exists()
    assert space_store.assignments() == {}


def test_espacios_renombrar_al_mismo_nombre_es_un_no_op(data_dir: Path) -> None:
    """Sin este atajo, el caso degenerado borraría y reescribiría la entrada."""
    espacio = space_store.create_space("Clientes")
    space_store.assign("sesion-1", espacio.id)
    antes = space_store._STORE_PATH.read_bytes()

    space_store.rename_session("sesion-1", "sesion-1")

    assert space_store.assignments() == {"sesion-1": espacio.id}
    assert space_store._STORE_PATH.read_bytes() == antes


def test_espacios_olvidar_una_sesion_borra_solo_la_suya(data_dir: Path) -> None:
    """`forget_session` se llama al matar una sesión: la entrada sobraría."""
    espacio = space_store.create_space("Clientes")
    space_store.assign("muerta", espacio.id)
    space_store.assign("viva", espacio.id)

    space_store.forget_session("muerta")

    assert space_store.assignments() == {"viva": espacio.id}
    # El espacio sigue existiendo aunque se quede sin sesiones.
    assert space_store.list_spaces() == [espacio]


def test_espacios_olvidar_una_sesion_desconocida_no_lanza_ni_escribe(
    data_dir: Path,
) -> None:
    """Se llama desde el camino de `kill-session`, que no sabe si estaba asignada."""
    space_store.forget_session("nunca-existio")

    assert not space_store._STORE_PATH.exists()


# ======================================================================
# space_store · leer nunca lanza.
# ======================================================================


def test_espacios_un_json_valido_escrito_a_mano_se_lee_entero(data_dir: Path) -> None:
    """El control positivo de los tests de "JSON roto" de este bloque."""
    space_store._STORE_PATH.write_text(
        json.dumps(
            {
                "spaces": [{"id": "sp_1", "title": "Clientes", "order": 3}],
                "assignments": {"sesion-1": "sp_1"},
            }
        ),
        encoding="utf-8",
    )

    assert space_store.list_spaces() == [space_store.Space("sp_1", "Clientes", 3)]
    assert space_store.assignments() == {"sesion-1": "sp_1"}


@pytest.mark.parametrize("contenido", JSON_ILEGIBLE, ids=_IDS_ILEGIBLE)
def test_espacios_un_json_ilegible_da_estructura_vacia_sin_lanzar(
    data_dir: Path, contenido: bytes
) -> None:
    """Sin espacios, pero con panel: las terminales siguen ahí, sin agrupar."""
    space_store._STORE_PATH.write_bytes(contenido)

    assert space_store.list_spaces() == []
    assert space_store.assignments() == {}


def test_espacios_las_claves_del_tipo_equivocado_se_ignoran(data_dir: Path) -> None:
    """`spaces` que no es lista, `assignments` que no es dict: se parte de vacío."""
    space_store._STORE_PATH.write_text(
        json.dumps({"spaces": "no es una lista", "assignments": [1, 2, 3]}),
        encoding="utf-8",
    )

    assert space_store.list_spaces() == []
    assert space_store.assignments() == {}


def test_espacios_las_entradas_malformadas_se_descartan_y_las_buenas_se_conservan(
    data_dir: Path,
) -> None:
    """Un espacio sin `id` o sin `title` no se puede pintar; los demás sí."""
    space_store._STORE_PATH.write_text(
        json.dumps(
            {
                "spaces": [
                    {"id": "sp_ok", "title": "Bueno", "order": 0},
                    {"id": "sp_sin_titulo"},
                    {"title": "Sin id"},
                    "no es un dict",
                    None,
                    {"id": "sp_ok2", "title": "Bueno2"},  # sin `order`: default 0
                ],
                "assignments": {"s1": "sp_ok"},
            }
        ),
        encoding="utf-8",
    )

    espacios = space_store.list_spaces()
    assert [s.id for s in espacios] == ["sp_ok", "sp_ok2"]
    assert espacios[1].order == 0, "el orden ausente cae a 0"
    assert space_store.assignments() == {"s1": "sp_ok"}


def test_espacios_escribir_sobre_un_json_roto_lo_deja_consistente(
    data_dir: Path,
) -> None:
    """La primera escritura recupera el archivo, igual que en la biblioteca."""
    space_store._STORE_PATH.write_bytes(b"[basura sin cerrar")

    creado = space_store.create_space("Nuevo")

    assert space_store.list_spaces() == [creado]
    assert json.loads(space_store._STORE_PATH.read_text(encoding="utf-8")) == {
        "spaces": [creado.to_dict()],
        "assignments": {},
    }


@pytest.mark.parametrize("contenido", JSON_QUE_NO_ES_UN_OBJETO, ids=_IDS_NO_OBJETO)
def test_regresion_s16_un_spaces_json_que_no_es_un_objeto_no_hace_lanzar_la_lectura(
    data_dir: Path, contenido: bytes
) -> None:
    """S16: `space_store._read()` llamaba a `raw.get("spaces")` sin mirar el tipo.

    `json.loads` acepta de buen grado una lista, un número, `null`, una cadena
    o un booleano, y con los cinco el `.get` lanzaba `AttributeError`: el panel
    devolvía 500 en cada carga. `library_store` (`isinstance(data, dict)`) y
    `upload_store` (`isinstance(data, list)`) ya comprobaban el tipo — era una
    asimetría, no una decisión.

    Es el mismo caso que cubre `test_biblioteca_un_json_que_no_es_un_objeto_...`
    sobre la biblioteca, y va con los mismos datos a propósito: los tres stores
    tienen que comportarse igual ante la misma basura.

    Quitar el `isinstance(raw, dict)` de `space_store._read()` vuelve a poner
    en rojo los cinco parámetros.
    """
    space_store._STORE_PATH.write_bytes(contenido)

    assert space_store.list_spaces() == []
    assert space_store.assignments() == {}


# ======================================================================
# upload_store · historial de subidas.
# ======================================================================


def _subir(nombre: str, directorio: str = "/destino") -> list[dict]:
    """Registra una subida cuyo `path` se deduce del nombre."""
    return upload_store.add(nombre, f"{directorio}/{nombre}", directorio)


def test_subidas_una_entrada_nueva_va_al_frente(data_dir: Path) -> None:
    """El historial es una pila: lo último subido es lo primero que se ve.

    `add` devuelve el historial resultante y tiene que coincidir con lo que
    devuelve `list_recent()` releyendo de disco.
    """
    devuelto = _subir("primero.txt")
    assert devuelto == [
        {"name": "primero.txt", "path": "/destino/primero.txt", "dir": "/destino"}
    ]

    devuelto = _subir("segundo.txt")

    assert [i["name"] for i in devuelto] == ["segundo.txt", "primero.txt"]
    assert upload_store.list_recent() == devuelto, "lo devuelto no es lo persistido"


def test_subidas_el_historial_se_recorta_al_maximo_conservando_las_recientes(
    data_dir: Path,
) -> None:
    """`KEEP` entradas y ni una más, y el recorte se lleva las más VIEJAS.

    El recorte es del registro, no de los archivos: los que salen de la lista
    siguen en el disco del usuario (eso lo cubre `test_upload.py` por HTTP).
    """
    assert upload_store.KEEP == KEEP_SUBIDAS, "cambió el máximo declarado"
    total = KEEP_SUBIDAS + 3

    for i in range(total):
        _subir(f"f{i}.txt")

    historial = upload_store.list_recent()
    assert [i["name"] for i in historial] == [
        f"f{i}.txt" for i in range(total - 1, total - 1 - KEEP_SUBIDAS, -1)
    ]
    # Y el recorte llegó al disco: no es solo que `list_recent` corte al leer.
    assert (
        len(json.loads(upload_store._STORE_PATH.read_text(encoding="utf-8")))
        == KEEP_SUBIDAS
    )


def test_subidas_repetir_una_ruta_la_sustituye_y_la_sube_al_frente(
    data_dir: Path,
) -> None:
    """Una ruta, una entrada: el historial se indexa por `path`.

    Es lo que pasa cuando el usuario borra un archivo y lo vuelve a subir al
    mismo sitio. Duplicarlo gastaría dos de las cinco plazas del historial en
    la misma ruta.
    """
    _subir("informe.txt")
    _subir("otro.txt")

    devuelto = upload_store.add("informe.txt", "/destino/informe.txt", "/otra/carpeta")

    assert [i["path"] for i in devuelto] == [
        "/destino/informe.txt",
        "/destino/otro.txt",
    ]
    assert devuelto[0]["dir"] == "/otra/carpeta", (
        "no se actualizó la entrada, se dejó la vieja"
    )
    assert len(upload_store.list_recent()) == 2


def test_subidas_dos_rutas_distintas_con_el_mismo_nombre_conviven(
    data_dir: Path,
) -> None:
    """El control negativo del anterior: la clave es la RUTA, no el nombre.

    Subir `informe.txt` a dos carpetas distintas son dos archivos distintos y
    el usuario tiene que poder copiar las dos rutas.
    """
    _subir("informe.txt", "/carpeta-a")
    devuelto = _subir("informe.txt", "/carpeta-b")

    assert [i["path"] for i in devuelto] == [
        "/carpeta-b/informe.txt",
        "/carpeta-a/informe.txt",
    ]


def test_subidas_quitar_una_entrada_la_borra_y_devuelve_el_resto(
    data_dir: Path,
) -> None:
    """`remove` es "olvídalo", y devuelve el historial ya sin ella."""
    _subir("uno.txt")
    _subir("dos.txt")

    devuelto = upload_store.remove("/destino/uno.txt")

    assert [i["name"] for i in devuelto] == ["dos.txt"]
    assert upload_store.list_recent() == devuelto


def test_subidas_quitar_una_ruta_desconocida_deja_el_historial_igual(
    data_dir: Path,
) -> None:
    """No lanza y no se lleva nada por delante: es idempotente.

    El botón de quitar puede pulsarse dos veces, o desde otra pestaña que tenía
    la lista vieja.
    """
    _subir("uno.txt")

    devuelto = upload_store.remove("/destino/no-existe.txt")

    assert [i["name"] for i in devuelto] == ["uno.txt"]
    assert upload_store.list_recent() == devuelto


def test_subidas_el_formato_en_disco_es_una_lista_de_name_path_dir(
    data_dir: Path,
) -> None:
    """Contabilidad por partida doble sobre el JSON persistido."""
    _subir("informe.txt")

    assert json.loads(upload_store._STORE_PATH.read_text(encoding="utf-8")) == [
        {"name": "informe.txt", "path": "/destino/informe.txt", "dir": "/destino"}
    ]


@pytest.mark.parametrize(
    "contenido",
    JSON_ILEGIBLE + JSON_QUE_NO_ES_UN_OBJETO,
    ids=_IDS_ILEGIBLE + _IDS_NO_OBJETO,
)
def test_subidas_un_json_roto_da_historial_vacio_sin_lanzar(
    data_dir: Path, contenido: bytes
) -> None:
    """Perder el historial es perder comodidad; lanzar es perder el panel."""
    upload_store._STORE_PATH.write_bytes(contenido)

    assert upload_store.list_recent() == []


def test_subidas_las_entradas_malformadas_se_descartan_y_las_buenas_se_conservan(
    data_dir: Path,
) -> None:
    """`name` y `path` tienen que ser cadenas; `dir` puede faltar.

    Que `dir` sea opcional es deliberado: es la carpeta que el panel preselecciona
    la próxima vez, no algo sin lo que la entrada no valga.
    """
    upload_store._STORE_PATH.write_text(
        json.dumps(
            [
                {"name": "ok.txt", "path": "/d/ok.txt", "dir": "/d"},
                {"name": "sin-dir.txt", "path": "/d/sin-dir.txt"},
                {"name": 42, "path": "/d/x.txt"},  # `name` no es cadena
                {"path": "/d/sin-nombre.txt"},
                {"name": "sin-path.txt"},
                "no es un dict",
                None,
                {"name": "ok2.txt", "path": "/d/ok2.txt", "dir": None},
            ]
        ),
        encoding="utf-8",
    )

    assert upload_store.list_recent() == [
        {"name": "ok.txt", "path": "/d/ok.txt", "dir": "/d"},
        {"name": "sin-dir.txt", "path": "/d/sin-dir.txt", "dir": ""},
        {"name": "ok2.txt", "path": "/d/ok2.txt", "dir": ""},
    ]


def test_subidas_escribir_sobre_un_json_roto_lo_deja_consistente(
    data_dir: Path,
) -> None:
    """La primera escritura recupera el archivo."""
    upload_store._STORE_PATH.write_bytes(b"{no es una lista")

    devuelto = _subir("nuevo.txt")

    assert json.loads(upload_store._STORE_PATH.read_text(encoding="utf-8")) == devuelto


# ======================================================================
# Atomicidad y permisos · los tres stores a la vez.
#
# Aquí es donde este archivo gana su sitio. Lo de arriba comprueba que los
# stores hacen lo que prometen cuando todo va bien; esto comprueba que un
# fallo a media escritura no se lleva los datos del usuario.
# ======================================================================


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_una_escritura_no_deja_ningun_temporal_suelto(
    store: Store, data_dir: Path, tmp_path: Path
) -> None:
    """Un `.tmp` superviviente es un `replace` que no llegó a ocurrir.

    O sea: datos escritos que no son los datos buenos, ocupando sitio en
    `data/` y con el contenido del usuario dentro. Se mira todo el tmp del
    test, no solo `data/`, por si algún día el temporal se creara en otro sitio.
    """
    store.escribir("uno")
    store.escribir("dos")

    assert store.ruta().is_file()
    assert _temporales(tmp_path) == []
    assert sorted(p.name for p in data_dir.iterdir()) == [store.ruta().name]


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_los_datos_quedan_a_0600_y_su_directorio_a_0700(
    store: Store, data_dir: Path
) -> None:
    """Lo que hay en `data/` es del usuario y de nadie más.

    En una máquina en la que el panel ya da una shell, un `library.json` a 0644
    es la lista de comandos del usuario legible por cualquier cuenta local.

    Se fuerza `umask(0)` a propósito: con el modo heredado del umask, un
    despliegue arrancado desde un shell permisivo sacaría los ficheros a 0666 y
    los directorios a 0777. El backend no controla el umask de quien lo lanza,
    así que el modo tiene que ir explícito.
    """
    with _umask(0):
        store.escribir("uno")

    assert _modo(store.ruta()) == MODO_FICHERO, (
        f"{store.nombre} dejó su JSON a {oct(_modo(store.ruta()))}"
    )
    assert _modo(data_dir) == MODO_DIRECTORIO, (
        f"el directorio de datos quedó a {oct(_modo(data_dir))}"
    )


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_un_umask_restrictivo_tampoco_decide_los_permisos(
    store: Store, data_dir: Path
) -> None:
    """El `chmod` explícito manda en las DOS direcciones, no solo hacia abajo.

    El test anterior cubre el umask permisivo; este el contrario. Con
    `umask(0o200)` —que quita el bit de escritura del dueño— el modo que se le
    pasa a `os.open` sale recortado a 0400 y el fichero quedaría de solo
    lectura: el panel no podría volver a escribirlo nunca y el usuario se
    quedaría con una biblioteca congelada. Solo el `os.chmod` posterior lo
    devuelve a 0600.

    Sin este caso, quitar ese `chmod` de `datafiles.write_private` no rompería
    ningún test: con un umask normal (0022) el `os.open` ya da 0600 solo.
    """
    with _umask(0o200):
        store.escribir("uno")

    assert _modo(store.ruta()) == MODO_FICHERO, (
        f"{store.nombre} dejó su JSON a {oct(_modo(store.ruta()))}: el umask del "
        "shell que arrancó el backend está decidiendo los permisos de los datos"
    )
    # Y sigue siendo escribible de verdad, no solo de nombre.
    store.escribir("dos")


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_si_falla_la_escritura_del_temporal_el_fichero_anterior_queda_intacto(
    store: Store, data_dir: Path, tmp_path: Path
) -> None:
    """EL test de este archivo: la propiedad que da el tmp + replace.

    Se escribe algo bueno, se sabotea la escritura para que reviente **después
    de haber escrito unos bytes** (disco lleno, kill a media faena) y se exigen
    las tres consecuencias:

      1. el error sale por la puerta, no se traga en silencio;
      2. el fichero anterior sigue byte a byte como estaba, y se puede leer por
         el contrato público;
      3. no queda un `.tmp` huérfano.

    Con la escritura en sitio que tenían `upload_store` y `space_store` antes,
    el punto 2 falla: el fichero queda cortado a los `BYTES_ANTES_DE_REVENTAR`
    y el store arranca vacío la próxima vez. Lo demuestra el auto-test
    `test_auto_con_la_escritura_en_sitio_de_antes_una_caida_corrompe_el_fichero`.
    """
    store.escribir("lo-bueno")
    contenido_bueno = store.ruta().read_bytes()
    leido_antes = store.leer()
    assert leido_antes == _con_marca(store, "lo-bueno"), "el escenario no arrancó bien"

    with _escritura_del_temporal_rota():
        with pytest.raises(store.error_al_fallar):
            store.escribir("lo-que-no-cabe")

    assert store.ruta().read_bytes() == contenido_bueno, (
        f"{store.nombre} corrompió su JSON al fallar la escritura: el fichero "
        "anterior del usuario ya no está. Esto es lo que pasaba antes del "
        "tmp + replace de datafiles.write_private."
    )
    assert store.leer() == leido_antes, "los datos anteriores ya no se leen"
    assert _temporales(tmp_path) == [], "quedó un temporal huérfano en data/"


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_si_falla_la_primera_escritura_no_queda_ni_fichero_ni_temporal(
    store: Store, data_dir: Path, tmp_path: Path
) -> None:
    """El caso de borde del anterior: no había nada que preservar.

    "Intacto" cuando el fichero no existía significa que sigue sin existir. Un
    `write_private` que dejara el fichero creado y vacío haría arrancar al store
    con un JSON que no parsea, y sería el propio panel quien lo hubiera escrito.
    """
    assert not store.ruta().exists()

    with _escritura_del_temporal_rota():
        with pytest.raises(store.error_al_fallar):
            store.escribir("lo-que-no-cabe")

    assert not store.ruta().exists(), f"{store.nombre} dejó un JSON a medio escribir"
    assert _temporales(tmp_path) == []
    assert store.leer() == store.vacio


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_tras_una_escritura_fallida_la_siguiente_vuelve_a_funcionar(
    store: Store, data_dir: Path, tmp_path: Path
) -> None:
    """El control positivo del bloque de atomicidad.

    Sin esto, un `write_private` que no escribiera NUNCA pasaría los dos tests
    anteriores con nota. Y además cubre lo que de verdad pasa en producción: el
    disco se llena, el usuario borra algo y la siguiente escritura tiene que
    cuajar sobre el fichero viejo, sin restos del intento fallido.
    """
    store.escribir("lo-bueno")

    with _escritura_del_temporal_rota():
        with pytest.raises(store.error_al_fallar):
            store.escribir("lo-que-no-cabe")

    store.escribir("lo-siguiente")

    leido = store.leer()
    valores = [v for v in leido.values() if isinstance(v, list)][0]
    # Ordenado: cada store coloca la entrada nueva donde le toca (la biblioteca
    # y los espacios al final, el historial de subidas al principio) y eso lo
    # fijan sus propios tests. Aquí lo único que se afirma es que están las dos.
    assert sorted(valores) == ["lo-bueno", "lo-siguiente"], (
        "tras el fallo, el store no volvió a escribir bien"
    )
    assert _temporales(tmp_path) == []


def test_write_private_escribe_en_un_temporal_y_lo_renombra(
    data_dir: Path, tmp_path: Path
) -> None:
    """La primitiva compartida, probada donde vive.

    Los tests de arriba comprueban que cada store USA `write_private`; este
    comprueba qué hace `write_private`, que es donde está la garantía. Es la
    única parte del archivo que baja del contrato público de los stores, porque
    "el fichero bueno nunca existe a medias" no se puede observar desde fuera.
    """
    destino = data_dir / "prueba.json"
    destino.write_bytes(b'{"anterior": true}')

    with _escritura_del_temporal_rota():
        with pytest.raises(OSError):
            datafiles.write_private(destino, b'{"nuevo": true}' * 10)

    assert destino.read_bytes() == b'{"anterior": true}'
    assert _temporales(tmp_path) == []

    # Y sin sabotaje escribe entero, con sus permisos, aceptando `str` y `bytes`.
    datafiles.write_private(destino, '{"nuevo": true}')
    assert destino.read_bytes() == b'{"nuevo": true}'
    assert _modo(destino) == MODO_FICHERO


def test_write_private_crea_el_directorio_que_falte_ya_cerrado(tmp_path: Path) -> None:
    """`data/` puede no existir: es una instalación nueva.

    Y no puede nacer a 0755 para cerrarse después — entre las dos cosas hay una
    ventana en la que el JSON ya está dentro y el directorio es legible por
    cualquiera. Se fuerza `umask(0)` para que el `mkdir` por sí solo daría 0777.
    """
    nuevo = tmp_path / "instalacion-nueva" / "data"

    with _umask(0):
        datafiles.write_private(nuevo / "library.json", b"{}")

    assert _modo(nuevo) == MODO_DIRECTORIO
    assert _modo(nuevo / "library.json") == MODO_FICHERO


# ======================================================================
# Los bordes de la regla "leer nunca lanza".
#
# Los dos (S15 y S16) están corregidos y sus tests son ya regresiones
# normales. Nacieron como `xfail(strict=True)` porque US-006 no tocaba
# producción: existían en la suite con su reproducción exacta, sin
# bloquearla, y el día del arreglo pasaron a verde, `strict` los puso en rojo
# y quien arregló vino a borrar el marcador. Que es exactamente lo que se
# quería.
# ======================================================================


# Los tres stores serializan con `ensure_ascii=False`, así que los acentos y la
# "…" que genera el propio `_default_label` van al disco como UTF-8 crudo (2 y
# 3 bytes por carácter). Truncar EN MEDIO de uno de ellos —exactamente lo que
# deja una escritura interrumpida— produce bytes que no son UTF-8 válido. Se
# construye quitando el último byte de una "ó", para que se vea que el corte es
# intencionado y dónde cae.
JSON_TRUNCADO_A_MEDIO_CARACTER = (
    '{"commands": [{"id": "c1", "label": "Compilació'.encode("utf-8")[:-1]
)


def test_auto_el_json_truncado_a_medio_caracter_no_es_utf8_valido() -> None:
    """El escenario del test de abajo es el que dice ser.

    Si algún día ese literal dejara de cortar un carácter multibyte por la
    mitad, la regresión de S15 pasaría a probar otra cosa (un JSON mal formado
    pero decodificable, que los stores toleran desde siempre) y seguiría verde
    aunque alguien revirtiera el arreglo.
    """
    assert JSON_TRUNCADO_A_MEDIO_CARACTER.endswith(b"\xc3")
    with pytest.raises(UnicodeDecodeError):
        JSON_TRUNCADO_A_MEDIO_CARACTER.decode("utf-8")
    # Y es un corte plausible: lo que va delante es JSON del store, no basura.
    assert JSON_TRUNCADO_A_MEDIO_CARACTER.startswith(b'{"commands"')


@pytest.mark.parametrize("store", STORES, ids=_IDS_STORES)
def test_regresion_s15_un_json_cortado_a_medio_caracter_no_hace_lanzar_la_lectura(
    store: Store, data_dir: Path
) -> None:
    """S15: los tres stores capturaban `json.JSONDecodeError`, no `ValueError`.

    Un JSON cortado en medio de un carácter multibyte —lo que deja una
    escritura interrumpida— hace que `read_text(encoding="utf-8")` lance
    `UnicodeDecodeError`, que es hermano de `JSONDecodeError` bajo `ValueError`
    y no subclase suya. Antes del arreglo esto dejaba el panel devolviendo 500
    en cada carga; el contrato del módulo es que leer nunca lanza.

    Revertir cualquiera de los tres `except (ValueError, OSError)` a
    `(json.JSONDecodeError, OSError)` vuelve a poner en rojo su parámetro.
    """
    store.ruta().write_bytes(JSON_TRUNCADO_A_MEDIO_CARACTER)

    assert store.leer() == store.vacio
