"""Subida de archivos: las dos regresiones de la auditoría (S3 y S4).

`/api/upload` es el único endpoint del panel que escribe un fichero **con el
nombre y en la carpeta que elige quien llama**. La auditoría de 2026-07 le
encontró dos agujeros y los dos ya están corregidos en `main.py`; este archivo
no arregla nada, existe para que el arreglo no se pierda en el siguiente
refactor.

**S3 · escritura fuera de las raíces vía symlink** (confirmado con PoC contra
el backend real). `_unique_target` decide si un nombre está libre con
`Path.exists()`, que **sigue los enlaces simbólicos**: ante un symlink
colgante devuelve `False`, o sea "hueco libre", y el `write_bytes` de entonces
escribía en el destino del enlace — fuera de las raíces permitidas. El
`resolve_within_roots` que valida la **carpeta** no ayuda aquí, porque el
problema no es la carpeta sino el **fichero final**. Hoy se abre con
`os.open(..., O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW, 0o600)` y el `ELOOP` se
traduce a 409.

**S4 · el cuerpo se bufferizaba entero antes de mirar el tamaño**. Se hacía
`data = await request.body()` y *después* se comprobaba el límite: un POST de
varios GB tumbaba el proceso aunque el tope fueran 100 MB. Hoy lo lee
`_read_capped`, que corta por `Content-Length` primero y por bytes leídos
después.

## La regla de este archivo

**Comprobar el código de estado NO BASTA.** Un test que solo mirase el 409
seguiría en verde con el bug puesto en cuanto alguien cambiara el código de
error, y el fichero de fuera se estaría escribiendo igual. Por eso todos los
casos de S3 comprueban el **efecto en el sistema de ficheros** —que el destino
del enlace no se crea, que su contenido no cambia— y lo comprueban **antes**
que el status: si esto se pone en rojo, el mensaje que sale tiene que ser "se
escribió fuera", no "esperaba 409 y llegó 200".

Igual que en `test_dir_roots.py`, el archivo se apoya en **auto-tests**: una
réplica del código anterior al arreglo que *sí* se escapa
(`_subida_como_antes_del_arreglo`) y que demuestra que el escenario discrimina
de verdad entre las dos versiones. Si esa réplica dejara de escaparse, los
tests de symlink de aquí abajo habrían dejado de significar algo.

## Cómo se prueban los topes sin generar 100 MB

- El tope se **baja con monkeypatch** en los tests de mecanismo. Lo que se
  prueba ahí es el mecanismo (¿corta?, ¿cuándo corta?), no el valor; el valor
  lo fija `test_los_topes_y_las_retenciones_son_los_declarados`.
- El tope **real** sí se ejercita, con un `Content-Length` mentiroso: se
  declaran 200 MB y se mandan 10 bytes. El rechazo por cabecera ocurre antes
  de leer nada, así que la constante de producción queda cubierta sin generar
  un solo megabyte.

## Cómo se prueba "sin Content-Length" (y por qué hacen falta dos técnicas)

`TestClient` **sí** produce peticiones chunked: basta pasar un generador como
`content=`, y sale con `Transfer-Encoding: chunked` y sin `Content-Length`
(lo verifica `test_auto_un_generador_produce_una_peticion_sin_content_length`,
que mira las cabeceras que llegan al otro lado). No hizo falta el socket crudo
contra un uvicorn.

Pero eso solo prueba el **veredicto** (413), no el **mecanismo**: el
`ASGITransport` de httpx bufferiza el cuerpo por su cuenta y se lo entrega a
la app de una tacada, así que un backend que leyera el cuerpo entero antes de
mirarlo devolvería exactamente el mismo 413. Para medir el mecanismo hay un
test que habla **ASGI directo** (`_post_por_asgi`): entrega el cuerpo trozo a
trozo con un `receive` propio que lleva la cuenta, y comprueba cuántos bytes
le llegó a pedir el endpoint antes de rendirse. Se eligió ASGI directo, y no
un uvicorn en un puerto libre, porque mide lo mismo de forma determinista y
sin puertos, hilos ni carreras entre "el cliente sigue enviando" y "el
servidor ya respondió" — ASGI es justo el contrato que uvicorn implementa.

## Sobre el objetivo de cobertura de la US

No es medible con `pytest --cov` en este repo, y no por culpa de estos tests:
**coverage.py deja de trazar el frame de una corrutina en cuanto el bucle de
eventos la suspende y la reanuda**. En `main.py` eso se ve a simple vista —
`upload_file` queda "cubierto" hasta la línea del
`await _read_capped(...)` y ni una más, y `_read_capped` hasta su `async for`
— mientras que las funciones **síncronas** que llaman desde ahí abajo
(`_unique_target`, `upload_store.add`, que se ejecutan *después* de ese punto)
sí salen cubiertas al 100%. O sea: el código se ejecuta, el contador no lo ve.
Afecta a todos los endpoints `async` del panel y ya pasaba antes de este
archivo (con la suite entera, `main.py` no pasa del 53%).

La garantía real de este archivo no es un porcentaje, es la **prueba de
mutación**: revertir el `O_NOFOLLOW`, revertir el `_read_capped` o vaciar el
`_unique_target` pone en rojo tests concretos de aquí. Un branch que sobrevive
a su mutación no está cubierto por mucho que lo diga un informe.

## Reglas del escenario (que también son reglas de seguridad del test)

- Todo vive bajo `tmp_path`, **incluido el "fuera de las raíces"**
  (`tmp_path/fuera`). Plantar un symlink que apunta fuera de la raíz es seguro
  precisamente porque su destino sigue estando en el tmp del test. Nunca el
  home real.
- `/etc` aparece **solo como argumento que debe ser rechazado**, jamás como
  destino de una escritura.
- `backend/data/` lo aísla el `conftest.py` y lo vigila su centinela de sesión.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Iterator, NamedTuple
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

import auth
import main
import upload_store

# ----------------------------------------------------------------------
# Constantes del contrato, DECLARADAS aquí y no importadas del módulo bajo
# prueba. Es contabilidad por partida doble, como en `test_dir_roots.py`: si
# se leyeran del propio código, bajar un tope actualizaría a la vez el hecho y
# su comprobación y la suite seguiría en verde sin que nadie lo revisara.
# ----------------------------------------------------------------------

# Tope por archivo subido y tope por captura pegada. Son distintos a
# propósito: una captura de pantalla no pesa 100 MB.
TOPE_UPLOAD = 100 * 1024 * 1024
TOPE_PASTE = 25 * 1024 * 1024

# Retención: cuántas capturas se conservan en disco y cuántas subidas se
# recuerdan en el historial.
CAPTURAS_CONSERVADAS = 5
SUBIDAS_RECORDADAS = 5

# Tope diminuto para los tests de MECANISMO. El número no significa nada: lo
# único que se prueba con él es *cómo* se aplica el límite.
TOPE_DE_PRUEBA = 4 * 1024

# Contenido del fichero de fuera de las raíces. Se comprueba byte a byte
# después de cada intento de escape: es el "no cambió" de S3.
BOTIN = b"contenido original que nadie de fuera puede tocar\n"

# El nombre de archivo más hostil que puede llegar del navegador y que aun así
# es *válido* (un único segmento, sin separadores ni NUL). Existe para que el
# rechazo de los nombres inválidos no se confunda con "rechaza lo que le
# parece raro", y para que nadie reimplemente la escritura pasando por shell.
NOMBRE_HOSTIL = "informe raro; rm -rf * && echo 'ups' `id`.txt"


class Escenario(NamedTuple):
    """Las piezas del terreno de juego, todas bajo el `tmp_path` del test."""

    raiz: Path  # la única raíz permitida: la carpeta destino de las subidas
    fuera: Path  # hermana de la raíz: el "fuera" seguro, también bajo tmp
    botin: Path  # fuera/botin.txt — EXISTE, con contenido conocido
    hueco: Path  # fuera/hueco.txt — NO existe: el destino del symlink colgante


@pytest.fixture
def escenario(allowed_root: Path, tmp_path: Path) -> Escenario:
    """Monta la raíz permitida y el "fuera" con sus dos destinos.

    Los dos destinos de fuera importan y son distintos: el que **existe**
    sirve para el symlink vivo (se comprueba que su contenido no cambia) y el
    que **no existe** para el colgante (se comprueba que no llega a crearse).
    """
    fuera = tmp_path / "fuera"
    fuera.mkdir(parents=True, exist_ok=True)
    botin = fuera / "botin.txt"
    botin.write_bytes(BOTIN)
    hueco = fuera / "hueco.txt"
    return Escenario(raiz=allowed_root, fuera=fuera, botin=botin, hueco=hueco)


# ----------------------------------------------------------------------
# Utilidades del archivo
# ----------------------------------------------------------------------


def _subir(
    client: TestClient,
    escenario: Escenario,
    name: str,
    content=b"datos",
    dir: str | None = None,
    **kwargs,
):
    """POST /api/upload con `dir` apuntando a la raíz permitida por defecto.

    `dir` y `name` van como query params (así lo declara el endpoint) y el
    cuerpo son los bytes crudos del archivo.
    """
    params = {"dir": escenario.raiz if dir is None else dir, "name": name}
    return client.post(
        "/api/upload",
        params={k: str(v) for k, v in params.items()},
        content=content,
        **kwargs,
    )


def _generador(trozo: bytes, veces: int) -> Iterator[bytes]:
    """Cuerpo perezoso. httpx lo manda como `Transfer-Encoding: chunked`."""
    for _ in range(veces):
        yield trozo


def _nombres(directorio: Path) -> list[str]:
    """Inventario ordenado de un directorio (sin recorrer, sin resolver)."""
    return sorted(p.name for p in directorio.iterdir())


class _CuerpoPorTrozos:
    """`receive` de ASGI que entrega el cuerpo a trozos y lleva la cuenta.

    Es la pieza que hace **medible** el símbolo de S4. Un `receive` normal (el
    de httpx, el de uvicorn con el cuerpo ya en el buffer) no distingue entre
    "leyó lo justo y cortó" y "leyó los 200 KB y luego miró el tamaño": las
    dos cosas acaban en 413. Contando cuántas veces se le pide un trozo, sí.
    """

    def __init__(self, trozo: bytes, veces: int) -> None:
        self._trozo = trozo
        self._pendientes = veces
        self.total = len(trozo) * veces
        self.entregados = 0

    async def __call__(self) -> dict:
        if self._pendientes:
            self._pendientes -= 1
            self.entregados += len(self._trozo)
            return {"type": "http.request", "body": self._trozo, "more_body": True}
        return {"type": "http.request", "body": b"", "more_body": False}


def _post_por_asgi(
    ruta: str,
    query: dict[str, str],
    cookie: str,
    cuerpo: _CuerpoPorTrozos,
    cabeceras: dict[str, str] | None = None,
) -> tuple[int, dict]:
    """Llama a `main.app` por el contrato ASGI, sin httpx de por medio.

    Se salta el cliente HTTP a propósito: es la única forma de controlar
    **cuándo** se le entrega cada trozo del cuerpo al endpoint. El scope es el
    que construye uvicorn para un POST; no se ejecuta el `lifespan`, que aquí
    no hace falta (el endpoint no depende de él y el `conftest` ya redirigió
    lo que se escribe en disco).
    """
    cabeceras_raw = [(b"host", b"testserver"), (b"cookie", cookie.encode())]
    for k, v in (cabeceras or {}).items():
        cabeceras_raw.append((k.encode(), v.encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": ruta,
        "raw_path": ruta.encode(),
        "query_string": urlencode(query).encode(),
        "root_path": "",
        "headers": cabeceras_raw,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }

    async def _correr() -> list[dict]:
        mensajes: list[dict] = []

        async def send(mensaje: dict) -> None:
            mensajes.append(mensaje)

        await main.app(scope, cuerpo, send)
        return mensajes

    mensajes = asyncio.run(_correr())
    inicio = next(m for m in mensajes if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in mensajes if m["type"] == "http.response.body"
    )
    return inicio["status"], (json.loads(payload) if payload else {})


def _cookie_de(client: TestClient) -> str:
    """La cookie de sesión del cliente, en formato cabecera `Cookie:`."""
    return f"{auth.SESSION_COOKIE}={client.cookies[auth.SESSION_COOKIE]}"


def _subida_como_antes_del_arreglo(directorio: Path, nombre: str, datos: bytes) -> Path:
    """Réplica de `upload_file` ANTES del arreglo de S3. **Se escapa.**

    Se escribe entera aquí, sin reutilizar `main._unique_target`, para que
    siga siendo la mutación que dice ser aunque `main.py` cambie por dentro.
    El defecto es de una sola línea: `Path.exists()` sigue los enlaces, así
    que un symlink **colgante** le parece un hueco libre y el `write_bytes`
    posterior escribe en el destino del enlace.
    """
    target = directorio / nombre
    if target.exists():  # ← sigue el enlace: False para un colgante
        stem, suffix, i = target.stem, target.suffix, 2
        while True:
            candidato = directorio / f"{stem} ({i}){suffix}"
            if not candidato.exists():
                target = candidato
                break
            i += 1
    target.write_bytes(datos)  # ← escribe DONDE APUNTE el enlace
    return target


# ======================================================================
# Auto-tests: que el escenario y las técnicas distinguen lo que dicen.
# ======================================================================


def test_auto_todo_el_escenario_vive_bajo_el_tmp_del_test(
    escenario: Escenario, tmp_path: Path
) -> None:
    """Ni el "fuera" es de verdad fuera del sandbox.

    Este archivo planta symlinks y provoca escrituras a través de ellos. Que
    sus destinos estén bajo `tmp_path` es lo que hace que sea seguro hacerlo,
    y no algo que se pueda dejar a la vista de quien lea el fixture.
    """
    tmp = tmp_path.resolve()
    for nombre, ruta in escenario._asdict().items():
        assert ruta.parent.resolve().is_relative_to(tmp), f"{nombre} -> {ruta}"
    assert escenario.botin.is_file()
    assert not escenario.hueco.exists(), "el destino del colgante debe NO existir"
    # Y el "fuera" es fuera de verdad: no cuelga de la raíz permitida.
    assert not escenario.fuera.resolve().is_relative_to(escenario.raiz.resolve())


def test_auto_con_el_write_bytes_de_antes_el_symlink_colgante_escribe_fuera(
    escenario: Escenario,
) -> None:
    """La prueba de que el detector detecta.

    Ejecuta la réplica del código anterior al arreglo sobre el mismo escenario
    que usan los tests de S3 y comprueba que **sí** se escapa. Mientras esta
    aserción siga en verde, `test_un_symlink_colgante_no_deja_escribir_fuera`
    no puede estar pasando por casualidad: el escenario distingue de verdad
    entre la versión con `write_bytes` y la versión con `O_NOFOLLOW`.
    """
    enlace = escenario.raiz / "colgante.txt"
    enlace.symlink_to(escenario.hueco)

    escrito = _subida_como_antes_del_arreglo(escenario.raiz, "colgante.txt", b"PoC")

    assert escenario.hueco.is_file(), (
        "la réplica del código de antes ya no se escapa; el escenario ha "
        "dejado de discriminar y los tests de symlink de este archivo han "
        "perdido su valor"
    )
    assert escenario.hueco.read_bytes() == b"PoC"
    # Y lo hizo creyendo que escribía dentro: la ruta que devolvió está en la
    # raíz, es el enlace el que la saca fuera.
    assert escrito == enlace


def test_auto_un_generador_produce_una_peticion_sin_content_length() -> None:
    """La técnica del "chunked" hace lo que este archivo dice que hace.

    Si httpx bufferizara el generador y calculara el `Content-Length`, el test
    de S4 "sin Content-Length" estaría probando la rama de la cabecera —la
    misma que ya cubre el test del `Content-Length` mentiroso— y la rama del
    conteo por trozos se quedaría sin cubrir sin que nadie se enterara. Aquí
    se miran las cabeceras que llegan REALMENTE al otro lado.
    """
    visto: dict = {}

    async def app(scope, receive, send) -> None:
        visto["headers"] = {k.decode(): v.decode() for k, v in scope["headers"]}
        visto["bytes"] = 0
        while True:
            mensaje = await receive()
            visto["bytes"] += len(mensaje.get("body", b""))
            if not mensaje.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    # Sin `with`: no se ejecuta el lifespan (esta app mínima no lo implementa).
    TestClient(app).post("http://testserver/x", content=_generador(b"A" * 1000, 4))

    assert "content-length" not in visto["headers"], (
        "httpx calculó el Content-Length del generador; la petición ya no es "
        "chunked y el test de 'sin Content-Length' ha dejado de serlo"
    )
    assert visto["headers"].get("transfer-encoding") == "chunked"
    assert visto["bytes"] == 4000, "el cuerpo llegó entero, solo que sin cabecera"


def test_auto_una_cabecera_content_length_falsa_llega_tal_cual() -> None:
    """La otra técnica: declarar 200 MB y mandar 10 bytes.

    Es lo que permite ejercitar el tope REAL sin generar 200 MB. Si httpx
    recalculara la cabecera a partir del cuerpo, el test del tope real estaría
    mandando `Content-Length: 10` y pasaría por ser pequeño, no por nada que
    hiciera el backend.
    """
    visto: dict = {}

    async def app(scope, receive, send) -> None:
        visto["headers"] = {k.decode(): v.decode() for k, v in scope["headers"]}
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    TestClient(app).post(
        "http://testserver/x",
        content=b"x" * 10,
        headers={"content-length": str(200 * 1024 * 1024)},
    )

    assert visto["headers"]["content-length"] == str(200 * 1024 * 1024)


# ======================================================================
# S3 · Symlinks: nunca se escribe a través de un enlace.
#
# En TODOS estos tests el aserto del sistema de ficheros va PRIMERO, antes
# que el del código de estado. Es deliberado: el fallo que hay que reportar
# es "se escribió fuera de las raíces", no "esperaba 409 y llegó 200".
# ======================================================================


def test_un_symlink_colgante_no_deja_escribir_fuera_de_las_raices(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """EL test de esta historia: la PoC de la auditoría, traducida a pytest.

    Un symlink colgante en la carpeta destino cuyo nombre coincide con el que
    se sube. `_unique_target` lo ve como un hueco libre (`exists()` sigue el
    enlace y el destino no existe), así que el destino de la escritura ES el
    enlace; solo `O_NOFOLLOW` evita que los bytes acaben en `tmp_path/fuera`.
    """
    enlace = escenario.raiz / "colgante.txt"
    enlace.symlink_to(escenario.hueco)

    respuesta = _subir(client_auth, escenario, "colgante.txt", b"PRUEBA-AUDITORIA")

    assert not escenario.hueco.exists(), (
        "S3 ha vuelto: la subida siguió el symlink y escribió en "
        f"{escenario.hueco}, fuera de las raíces permitidas"
    )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_exists"
    # El enlace sigue siendo un enlace: tampoco se ha sustituido por el
    # fichero subido (que sería otra forma de "no escribir fuera" pero un
    # cambio de comportamiento silencioso).
    assert enlace.is_symlink()
    assert _nombres(escenario.raiz) == ["colgante.txt"]
    # Una subida rechazada no deja rastro en el historial.
    assert client_auth.get("/api/uploads").json() == []


def test_un_symlink_colgante_en_el_hueco_de_la_colision_tampoco_escribe_fuera(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """La misma fuga, por la segunda puerta: el bucle de " (2)", " (3)"…

    `_unique_target` usa `exists()` **dos veces**: para el nombre pedido y
    para cada candidato con sufijo. Un arreglo que solo mirase el primero
    dejaría abierta esta variante: `informe.txt` existe de verdad, así que la
    subida se desvía a `informe (2).txt` — que es el colgante.
    """
    (escenario.raiz / "informe.txt").write_bytes(b"el fichero legitimo")
    enlace = escenario.raiz / "informe (2).txt"
    enlace.symlink_to(escenario.hueco)

    respuesta = _subir(client_auth, escenario, "informe.txt", b"PRUEBA-AUDITORIA")

    assert not escenario.hueco.exists(), (
        "la subida se escapó por el candidato con sufijo de `_unique_target`"
    )
    assert respuesta.status_code == 409, respuesta.text
    # Y el fichero legítimo que provocó la colisión sigue intacto.
    assert (escenario.raiz / "informe.txt").read_bytes() == b"el fichero legitimo"
    assert enlace.is_symlink()


def test_un_symlink_vivo_que_apunta_fuera_no_cambia_el_fichero_de_destino(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El enlace apunta a un fichero que SÍ existe fuera de las raíces.

    Aquí `exists()` dice `True`, así que la subida se desvía sola al hueco
    siguiente y el resultado es un 200 legítimo. Lo que se exige no es un
    rechazo: es que el fichero de fuera **no cambie** y que lo que se escriba
    acabe **dentro** de la raíz.
    """
    enlace = escenario.raiz / "notas.txt"
    enlace.symlink_to(escenario.botin)

    respuesta = _subir(client_auth, escenario, "notas.txt", b"ATAQUE")

    assert escenario.botin.read_bytes() == BOTIN, (
        f"el contenido de {escenario.botin}, que está fuera de las raíces, "
        "ha cambiado"
    )
    assert respuesta.status_code == 200, respuesta.text
    destino = Path(respuesta.json()["path"])
    assert destino.resolve().is_relative_to(escenario.raiz.resolve())
    assert destino.name == "notas (2).txt"
    assert destino.read_bytes() == b"ATAQUE"
    assert enlace.is_symlink(), "el enlace se ha sustituido por el archivo subido"


def test_un_symlink_vivo_que_apunta_dentro_tampoco_pisa_su_destino(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """La variante de dentro: escribir por el enlace pisaría un fichero real.

    Estar dentro de las raíces no lo hace inocuo — el usuario no pidió
    sobrescribir `importante.txt`, pidió subir `alias.txt`.
    """
    importante = escenario.raiz / "importante.txt"
    importante.write_bytes(b"no me pises")
    (escenario.raiz / "alias.txt").symlink_to(importante)

    respuesta = _subir(client_auth, escenario, "alias.txt", b"ATAQUE")

    assert importante.read_bytes() == b"no me pises"
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["name"] == "alias (2).txt"


def test_un_bucle_de_symlinks_se_rechaza_sin_reventar(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """Un enlace que apunta a sí mismo: ELOOP también en `os.open`.

    `Path.exists()` se come el `OSError` y devuelve `False` (hueco libre),
    así que el destino de la escritura vuelve a ser el enlace. Debe salir un
    409, no un 500: la diferencia entre "el nombre está ocupado" y "el backend
    se ha caído" es la que ve el usuario.
    """
    bucle = escenario.raiz / "bucle.txt"
    bucle.symlink_to(bucle)

    respuesta = _subir(client_auth, escenario, "bucle.txt", b"datos")

    assert _nombres(escenario.raiz) == ["bucle.txt"]
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_exists"


def test_una_subida_normal_no_se_ve_afectada_por_los_enlaces_de_al_lado(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El control positivo de S3.

    Un backend que rechazara toda subida pasaría cada test de rechazo de este
    bloque. Con los dos symlinks plantados, un nombre que no colisiona con
    ninguno tiene que guardarse igual que siempre.
    """
    (escenario.raiz / "colgante.txt").symlink_to(escenario.hueco)
    (escenario.raiz / "notas.txt").symlink_to(escenario.botin)

    respuesta = _subir(client_auth, escenario, "otro.txt", b"contenido")

    assert respuesta.status_code == 200, respuesta.text
    destino = escenario.raiz / "otro.txt"
    assert destino.read_bytes() == b"contenido"
    assert not escenario.hueco.exists()
    assert escenario.botin.read_bytes() == BOTIN


# ======================================================================
# S4 · El tamaño se aplica ANTES de tener el cuerpo en memoria.
# ======================================================================


def test_un_content_length_por_encima_del_tope_real_se_rechaza_sin_leer_el_cuerpo(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El tope de producción (100 MB), ejercitado sin generar 100 MB.

    Se declaran 200 MB en la cabecera y se mandan 10 bytes. Que salga 413
    demuestra que el rechazo viene de `Content-Length` y no del tamaño real,
    porque el tamaño real está muy por debajo del tope. El `mb` del error es
    la comprobación de que el tope aplicado es el de verdad, el de `main.py`.
    """
    respuesta = _subir(
        client_auth,
        escenario,
        "enorme.bin",
        content=b"x" * 10,
        headers={"content-length": str(2 * TOPE_UPLOAD)},
    )

    assert respuesta.status_code == 413, respuesta.text
    assert respuesta.json()["detail"] == {
        "code": "err.upload_too_large",
        "params": {"mb": TOPE_UPLOAD // (1024 * 1024)},
    }
    assert _nombres(escenario.raiz) == [], "se creó el archivo pese al 413"


def test_un_content_length_por_encima_del_tope_no_crea_el_archivo(
    client_auth: TestClient, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mismo caso con el tope bajado: lo que se prueba es el mecanismo.

    Con el tope en `TOPE_DE_PRUEBA` el cuerpo declarado *y* enviado supera el
    límite, así que las dos ramas de `_read_capped` lo rechazarían. Sirve de
    caso "honesto" (la cabecera dice la verdad) frente al anterior.
    """
    monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", TOPE_DE_PRUEBA)

    respuesta = _subir(
        client_auth, escenario, "grande.bin", content=b"x" * (TOPE_DE_PRUEBA + 1)
    )

    assert respuesta.status_code == 413, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_too_large"
    assert _nombres(escenario.raiz) == []


def test_un_cuerpo_chunked_sin_content_length_por_encima_del_tope_se_rechaza(
    client_auth: TestClient, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin `Content-Length` no hay cabecera en la que confiar: se cuenta.

    El generador hace que httpx mande la petición como `Transfer-Encoding:
    chunked` (lo verifica el auto-test correspondiente). Es el caso que un
    atacante usaría: la cabecera es opcional y mentir por omisión es gratis.
    """
    monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", TOPE_DE_PRUEBA)

    respuesta = _subir(
        client_auth,
        escenario,
        "chunked.bin",
        content=_generador(b"y" * 1024, (TOPE_DE_PRUEBA // 1024) + 2),
    )

    assert respuesta.status_code == 413, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_too_large"
    assert _nombres(escenario.raiz) == []


def test_el_cuerpo_deja_de_leerse_en_cuanto_pasa_del_tope(
    client_auth: TestClient, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EL test de S4: no basta con responder 413, hay que dejar de leer.

    Se entregan 200 KB en trozos de 1 KB, con el tope en 4 KB y sin
    `Content-Length` (el ataque real: un POST de varios GB en chunked). Se
    mide cuántos bytes le llegó a PEDIR el endpoint al transporte. Con
    `_read_capped` son poco más que el tope; con el `await request.body()` de
    antes serían los 200 KB — y con un atacante de verdad, los varios GB que
    tumbaban el proceso.

    Se habla ASGI directo porque ni httpx ni un uvicorn en un puerto libre
    permiten observar esto sin carreras: el `ASGITransport` de httpx entrega
    el cuerpo de una tacada, y con un socket habría que adivinar cuánto se
    envió antes de que llegara la respuesta.
    """
    monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", TOPE_DE_PRUEBA)
    cuerpo = _CuerpoPorTrozos(b"Z" * 1024, 200)

    status, detalle = _post_por_asgi(
        "/api/upload",
        {"dir": str(escenario.raiz), "name": "streaming.bin"},
        _cookie_de(client_auth),
        cuerpo,
    )

    assert cuerpo.entregados <= TOPE_DE_PRUEBA + 1024, (
        f"S4 ha vuelto: el endpoint pidió {cuerpo.entregados} bytes con el "
        f"tope en {TOPE_DE_PRUEBA}. El límite se está aplicando DESPUÉS de "
        f"bufferizar el cuerpo entero ({cuerpo.total} bytes aquí, varios GB "
        f"en el ataque real)."
    )
    assert cuerpo.entregados < cuerpo.total, "se leyó el cuerpo entero"
    assert status == 413
    assert detalle["detail"]["code"] == "err.upload_too_large"
    assert _nombres(escenario.raiz) == []


def test_un_cuerpo_justo_en_el_tope_se_acepta_y_uno_mas_no(
    client_auth: TestClient, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El control positivo del tope, y su frontera exacta.

    Un backend que rechazara todo pasaría los tres tests anteriores. El
    límite es "mayor que", no "mayor o igual": exactamente el tope entra.
    """
    monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", TOPE_DE_PRUEBA)

    justo = _subir(client_auth, escenario, "justo.bin", content=b"x" * TOPE_DE_PRUEBA)
    assert justo.status_code == 200, justo.text
    assert (escenario.raiz / "justo.bin").stat().st_size == TOPE_DE_PRUEBA

    pasado = _subir(
        client_auth, escenario, "pasado.bin", content=b"x" * (TOPE_DE_PRUEBA + 1)
    )
    assert pasado.status_code == 413, pasado.text
    assert not (escenario.raiz / "pasado.bin").exists()


def test_un_cuerpo_vacio_se_rechaza_con_400_y_no_crea_nada(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """"Sin cuerpo" no es "archivo de 0 bytes": es una petición incompleta."""
    respuesta = _subir(client_auth, escenario, "vacio.txt", content=b"")

    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_missing"
    assert _nombres(escenario.raiz) == []


# ----------------------------------------------------------------------
# El mismo mecanismo en /api/paste-image, con su propio tope.
# ----------------------------------------------------------------------

CABECERA_PNG = {"content-type": "image/png"}


def test_pegar_una_imagen_por_encima_del_tope_real_se_rechaza_por_content_length(
    client_auth: TestClient, data_dir: Path
) -> None:
    """El tope de producción de las capturas (25 MB), sin generar 25 MB."""
    respuesta = client_auth.post(
        "/api/paste-image",
        content=b"x" * 10,
        headers={**CABECERA_PNG, "content-length": str(2 * TOPE_PASTE)},
    )

    assert respuesta.status_code == 413, respuesta.text
    assert respuesta.json()["detail"] == {
        "code": "err.image_too_large",
        "params": {"mb": TOPE_PASTE // (1024 * 1024)},
    }
    assert not (data_dir / "pastes").exists(), "se creó la captura pese al 413"


def test_pegar_una_imagen_chunked_por_encima_del_tope_se_rechaza(
    client_auth: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/api/paste-image` comparte `_read_capped`, pero con su propio tope.

    Se prueba aparte y no "por herencia": el día que alguien duplique la
    lectura del cuerpo en uno de los dos endpoints, el otro tiene que seguir
    cubierto por su propio test.
    """
    monkeypatch.setattr(main, "_PASTE_MAX_BYTES", TOPE_DE_PRUEBA)

    respuesta = client_auth.post(
        "/api/paste-image",
        content=_generador(b"y" * 1024, (TOPE_DE_PRUEBA // 1024) + 2),
        headers=CABECERA_PNG,
    )

    assert respuesta.status_code == 413, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.image_too_large"
    assert not (data_dir / "pastes").exists()


def test_al_pegar_una_imagen_el_cuerpo_deja_de_leerse_en_cuanto_pasa_del_tope(
    client_auth: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mismo conteo por ASGI directo, en el endpoint de las capturas."""
    monkeypatch.setattr(main, "_PASTE_MAX_BYTES", TOPE_DE_PRUEBA)
    cuerpo = _CuerpoPorTrozos(b"Z" * 1024, 200)

    status, detalle = _post_por_asgi(
        "/api/paste-image", {}, _cookie_de(client_auth), cuerpo, CABECERA_PNG
    )

    assert cuerpo.entregados <= TOPE_DE_PRUEBA + 1024, (
        f"el endpoint pidió {cuerpo.entregados} de {cuerpo.total} bytes con "
        f"el tope en {TOPE_DE_PRUEBA}"
    )
    assert status == 413
    assert detalle["detail"]["code"] == "err.image_too_large"
    assert not (data_dir / "pastes").exists()


def test_una_imagen_por_debajo_del_tope_se_guarda(
    client_auth: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El control positivo de `/api/paste-image`."""
    monkeypatch.setattr(main, "_PASTE_MAX_BYTES", TOPE_DE_PRUEBA)

    respuesta = client_auth.post(
        "/api/paste-image", content=b"z" * 100, headers=CABECERA_PNG
    )

    assert respuesta.status_code == 200, respuesta.text
    guardada = Path(respuesta.json()["path"])
    assert guardada.read_bytes() == b"z" * 100
    assert guardada.parent == data_dir / "pastes"


def test_cada_endpoint_aplica_su_propio_tope_y_no_uno_compartido(
    client_auth: TestClient, escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los dos topes son variables distintas, y se nota.

    Con los topes cruzados (el de las capturas muy por debajo del de las
    subidas), un mismo cuerpo tiene que ser rechazado por uno y aceptado por
    el otro. Si alguien unificara los dos en una sola constante "por limpiar",
    este test lo caza; los demás seguirían en verde.
    """
    monkeypatch.setattr(main, "_UPLOAD_MAX_BYTES", 8 * 1024)
    monkeypatch.setattr(main, "_PASTE_MAX_BYTES", 1 * 1024)
    cuerpo = b"c" * 4096

    pegada = client_auth.post(
        "/api/paste-image", content=cuerpo, headers=CABECERA_PNG
    )
    assert pegada.status_code == 413, pegada.text

    subida = _subir(client_auth, escenario, "mediano.bin", content=cuerpo)
    assert subida.status_code == 200, subida.text


# ======================================================================
# Validación del nombre y del destino.
# ======================================================================

# Cada uno rompe una regla distinta: subir un nivel, colarse en un
# subdirectorio, los dos componentes especiales de POSIX, el nombre vacío (y
# el que se queda vacío al hacer `strip`), la barra invertida de Windows y el
# NUL —que en C termina la cadena, así que "a\0.txt.exe" es "a" para el
# kernel y otra cosa para cualquier validación hecha sobre el texto completo.
NOMBRES_INVALIDOS = [
    "../x",
    "a/b",
    "sub/../../fuera",
    ".",
    "..",
    "",
    "   ",
    "a\\b",
    "a\x00b",
    "\x00",
]
_IDS_NOMBRES = [
    "punto-punto-barra-x",
    "a-barra-b",
    "traversal-largo",
    "punto",
    "punto-punto",
    "vacio",
    "espacios",
    "barra-invertida",
    "nul-en-medio",
    "solo-nul",
]


@pytest.mark.parametrize("nombre", NOMBRES_INVALIDOS, ids=_IDS_NOMBRES)
def test_un_nombre_invalido_se_rechaza_con_400_y_no_escribe_nada(
    client_auth: TestClient, escenario: Escenario, tmp_path: Path, nombre: str
) -> None:
    """El nombre es un único segmento o no es nada.

    Se comprueba también que no quedó nada escrito en NINGUNA parte del tmp
    del test: un rechazo que llegara después de crear el fichero sería igual
    de grave que no rechazar.
    """
    antes = sorted(str(p) for p in tmp_path.rglob("*"))

    respuesta = _subir(client_auth, escenario, nombre, b"datos")

    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_name_invalid"
    assert sorted(str(p) for p in tmp_path.rglob("*")) == antes


def test_un_nombre_hostil_pero_valido_se_guarda_literalmente(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El control positivo de la validación de nombres.

    Espacios, `;`, `&&`, comillas y backticks son solo caracteres: aquí no hay
    shell (es `os.open`) y este test existe para que siga sin haberla. Si
    alguien reimplementara la escritura con `subprocess(shell=True)`, el
    `rm -rf *` borraría la raíz y el `id` se ejecutaría.
    """
    respuesta = _subir(client_auth, escenario, NOMBRE_HOSTIL, b"contenido")

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["name"] == NOMBRE_HOSTIL
    # Exactamente una entrada nueva: ni se ejecutó nada, ni se borró nada.
    assert _nombres(escenario.raiz) == [NOMBRE_HOSTIL]
    assert (escenario.raiz / NOMBRE_HOSTIL).read_bytes() == b"contenido"


def test_un_dir_fuera_de_las_raices_se_rechaza_con_400(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """La carpeta destino pasa por `resolve_within_roots` antes de nada.

    `/etc` aparece aquí SOLO como argumento a rechazar: si el filtro fallara,
    lo que este test tiene que hacer es ponerse en rojo, no escribir en
    `/etc`. Por eso la segunda mitad usa el "fuera" de `tmp_path`, donde sí
    se puede comprobar que no quedó nada escrito.
    """
    respuesta = _subir(client_auth, escenario, "z.txt", b"datos", dir="/etc")
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_dir_invalid"

    respuesta = _subir(client_auth, escenario, "z.txt", b"datos", dir=escenario.fuera)
    assert respuesta.status_code == 400, respuesta.text
    assert _nombres(escenario.fuera) == ["botin.txt"]


def test_un_dir_que_es_un_symlink_a_fuera_se_rechaza_con_400(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """La carpeta también se puede disfrazar de enlace.

    `raiz/salida` empieza por la raíz carácter a carácter; solo resolviendo el
    enlace se ve que el destino está fuera. El módulo que decide esto
    (`dir_suggestions`) lo cubre US-003; aquí se comprueba que `/api/upload`
    pasa de verdad por esa puerta y no por una comprobación propia.
    """
    (escenario.raiz / "salida").symlink_to(escenario.fuera, target_is_directory=True)

    respuesta = _subir(
        client_auth, escenario, "z.txt", b"datos", dir=escenario.raiz / "salida"
    )

    assert _nombres(escenario.fuera) == ["botin.txt"]
    assert respuesta.status_code == 400, respuesta.text
    assert respuesta.json()["detail"]["code"] == "err.upload_dir_invalid"


# ======================================================================
# Colisiones de nombre.
# ======================================================================


def test_una_colision_de_nombre_no_pisa_el_original(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """Subir dos veces el mismo nombre guarda `nombre (2).ext`.

    El archivo original es un fichero REAL del usuario: sobrescribirlo sin
    avisar es pérdida de datos, no una comodidad.
    """
    primera = _subir(client_auth, escenario, "informe.txt", b"primero")
    assert primera.status_code == 200, primera.text
    assert primera.json()["name"] == "informe.txt"

    segunda = _subir(client_auth, escenario, "informe.txt", b"segundo")

    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["name"] == "informe (2).txt"
    assert (escenario.raiz / "informe.txt").read_bytes() == b"primero"
    assert (escenario.raiz / "informe (2).txt").read_bytes() == b"segundo"
    assert Path(segunda.json()["path"]) == escenario.raiz / "informe (2).txt"


def test_la_segunda_colision_usa_el_sufijo_3(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El sufijo avanza; no se queda atascado en " (2)" ni se acumula.

    "informe (2) (2).txt" sería lo que saldría de aplicar el sufijo al nombre
    ya sufijado, y es justo lo que no queremos.
    """
    for _ in range(3):
        _subir(client_auth, escenario, "informe.txt", b"x")

    assert _nombres(escenario.raiz) == [
        "informe (2).txt",
        "informe (3).txt",
        "informe.txt",
    ]


def test_la_colision_de_un_nombre_sin_extension_tambien_lleva_sufijo(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """`LEEME` y `LEEME (2)`: el sufijo va al final cuando no hay extensión."""
    _subir(client_auth, escenario, "LEEME", b"uno")
    segunda = _subir(client_auth, escenario, "LEEME", b"dos")

    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["name"] == "LEEME (2)"
    assert (escenario.raiz / "LEEME").read_bytes() == b"uno"


def test_la_colision_respeta_los_puntos_del_nombre(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """Solo la ÚLTIMA extensión se conserva detrás del sufijo.

    Es el comportamiento de `Path.stem`/`Path.suffix` y se fija aquí para que
    un cambio de criterio (p. ej. tratar `.tar.gz` como una extensión doble)
    sea consciente y no un efecto colateral.
    """
    _subir(client_auth, escenario, "copia.tar.gz", b"uno")
    segunda = _subir(client_auth, escenario, "copia.tar.gz", b"dos")

    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["name"] == "copia.tar (2).gz"


# ======================================================================
# Historial de subidas y permisos en disco.
# ======================================================================


def test_el_historial_se_recorta_a_las_ultimas_subidas(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """`upload_store.KEEP` entradas, las más recientes primero.

    Y —esto es lo importante— recortar el HISTORIAL no borra ARCHIVOS: los
    que salen de la lista siguen en disco, porque son ficheros del usuario.
    """
    total = SUBIDAS_RECORDADAS + 2
    for i in range(total):
        respuesta = _subir(client_auth, escenario, f"f{i}.txt", b"x")
        assert respuesta.status_code == 200, respuesta.text

    historial = client_auth.get("/api/uploads").json()

    assert len(historial) == SUBIDAS_RECORDADAS
    assert [i["name"] for i in historial] == [
        f"f{i}.txt" for i in range(total - 1, total - 1 - SUBIDAS_RECORDADAS, -1)
    ]
    assert _nombres(escenario.raiz) == sorted(f"f{i}.txt" for i in range(total))


def test_subir_dos_veces_a_la_misma_ruta_no_duplica_la_entrada(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """Una ruta, una entrada: el historial se indexa por `path`.

    Para que la segunda subida caiga en la MISMA ruta hay que dejar el hueco
    libre (si no, la colisión la desviaría a " (2)"), que es exactamente lo
    que pasa cuando el usuario borra el archivo y lo vuelve a subir.
    """
    primera = _subir(client_auth, escenario, "informe.txt", b"uno")
    ruta = primera.json()["path"]
    Path(ruta).unlink()

    segunda = _subir(client_auth, escenario, "informe.txt", b"dos")
    assert segunda.json()["path"] == ruta

    historial = client_auth.get("/api/uploads").json()
    assert len(historial) == 1
    assert historial[0]["path"] == ruta


def test_borrar_del_historial_quita_la_entrada_y_no_borra_el_archivo(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """`DELETE /api/uploads` es "olvídalo", no "bórralo".

    El archivo está en una carpeta del usuario, elegida por él, y puede llevar
    ahí meses. Borrarlo desde un botón de "quitar de la lista" sería una
    pérdida de datos silenciosa.
    """
    respuesta = _subir(client_auth, escenario, "informe.txt", b"contenido")
    ruta = respuesta.json()["path"]
    _subir(client_auth, escenario, "otro.txt", b"otro")

    borrado = client_auth.request("DELETE", "/api/uploads", params={"path": ruta})

    assert borrado.status_code == 200, borrado.text
    assert [i["path"] for i in borrado.json()] == [str(escenario.raiz / "otro.txt")]
    assert client_auth.get("/api/uploads").json() == borrado.json()
    assert Path(ruta).is_file(), "el archivo del usuario se ha borrado del disco"
    assert Path(ruta).read_bytes() == b"contenido"


def test_el_archivo_subido_queda_a_0600_aunque_el_umask_sea_permisivo(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """Solo el dueño lee lo que se sube.

    El modo va explícito en el `os.open`, así que un umask laxo (el del shell
    desde el que se arrancó el backend, que no controlamos) no puede
    ensancharlo. Se fuerza `umask(0)` para probar justo eso: con el modo
    heredado del umask, el archivo saldría a 0666 y este test lo cazaría.
    """
    previo = os.umask(0)
    try:
        respuesta = _subir(client_auth, escenario, "privado.txt", b"secreto")
    finally:
        os.umask(previo)

    assert respuesta.status_code == 200, respuesta.text
    modo = stat.S_IMODE((escenario.raiz / "privado.txt").stat().st_mode)
    assert modo == 0o600, f"el archivo salió a {oct(modo)}"


def test_una_subida_no_deja_ningun_temporal_suelto(
    client_auth: TestClient, escenario: Escenario, tmp_path: Path
) -> None:
    """Ni en la carpeta destino ni en `data/`.

    La subida escribe directa sobre el destino (no hay tmp + replace: el
    fichero es del usuario y su ruta la eligió él), pero el historial sí pasa
    por `write_private`. Un `.tmp` superviviente sería un `replace` que no se
    completó, o sea un historial escrito a medias.
    """
    _subir(client_auth, escenario, "informe.txt", b"contenido")
    client_auth.post("/api/paste-image", content=b"z" * 50, headers=CABECERA_PNG)

    assert _nombres(escenario.raiz) == ["informe.txt"]
    assert list(tmp_path.rglob("*.tmp")) == []


def test_la_ruta_devuelta_es_absoluta_y_apunta_al_archivo_real(
    client_auth: TestClient, escenario: Escenario
) -> None:
    """El contrato con el frontend: la ruta se copia y se pega en un comando.

    Una ruta relativa, o una que no exista, convertiría el botón "copiar
    ruta" en una fuente de errores silenciosos.
    """
    respuesta = _subir(client_auth, escenario, "informe.txt", b"contenido")

    cuerpo = respuesta.json()
    destino = Path(cuerpo["path"])
    assert destino.is_absolute()
    assert destino.is_file()
    assert destino.read_bytes() == b"contenido"
    assert cuerpo["dir"] == str(escenario.raiz)
    assert cuerpo["name"] == destino.name
    # Y el historial guarda exactamente lo mismo que se devolvió.
    assert client_auth.get("/api/uploads").json() == [cuerpo]


# ======================================================================
# Los valores: cambiarlos tiene que ser un acto consciente.
# ======================================================================


def test_los_topes_y_las_retenciones_son_los_declarados() -> None:
    """Contabilidad por partida doble sobre las cuatro constantes.

    Los tests de mecanismo bajan los topes con `monkeypatch`, así que ninguno
    de ellos se entera si mañana el tope de subida pasa a 4 GB o el historial
    a una sola entrada. Este es el único sitio donde los VALORES están
    escritos, y está duplicado a mano para que tocarlos aparezca en el diff.
    """
    assert main._UPLOAD_MAX_BYTES == TOPE_UPLOAD == 100 * 1024 * 1024
    assert main._PASTE_MAX_BYTES == TOPE_PASTE == 25 * 1024 * 1024
    assert main._PASTE_KEEP == CAPTURAS_CONSERVADAS == 5
    assert upload_store.KEEP == SUBIDAS_RECORDADAS == 5
    # El tope de las capturas es MENOR que el de los archivos: una captura de
    # pantalla no pesa 100 MB, y el directorio de capturas vive en `data/`.
    assert main._PASTE_MAX_BYTES < main._UPLOAD_MAX_BYTES
