"""Dónde puede escribir el panel: raíces, `..` y symlinks en `dir_suggestions`.

Este módulo no dibuja nada: decide **qué directorios existen** para el
navegador de carpetas, para la creación de subcarpetas y para `/api/upload`.
Es el único filtro entre "el usuario teclea una ruta" y "el backend escribe
un fichero ahí", y el backend corre como un usuario con shell. Un fallo aquí
no se traduce en una sugerencia fea, sino en una escritura arbitraria en el
sistema de ficheros.

El símbolo que protegen estos tests es un **orden**, no una condición:

    resolver los enlaces  →  comprobar la contención

Al revés (`comprobar la contención → resolver`) el módulo seguiría
rechazando `../` y `/etc`, seguiría aceptando lo que hay dentro de la raíz, y
todos los tests "obvios" seguirían en verde; lo único que cambiaría es que un
symlink plantado dentro de la raíz y apuntando fuera pasaría el filtro, porque
*léxicamente* está dentro. Por eso el archivo se organiza alrededor de ese
caso, e incluye un auto-test (`test_auto_...`) que ejecuta una réplica del
módulo con el orden invertido y comprueba que se escapa: si esa réplica
dejara de escaparse, los tests negativos de aquí abajo habrían dejado de
significar algo.

Reglas del escenario, que también son reglas de seguridad del propio test:

- Todo se monta bajo `tmp_path`, incluido el "fuera de las raíces"
  (`tmp_path/fuera`). Plantar un symlink que apunta fuera de la raíz es
  seguro precisamente porque su destino sigue estando en el tmp del test.
- `/etc`, `/` y `~root` aparecen **solo como argumentos que deben ser
  rechazados**, nunca como destino de una escritura.
- Nada toca el home real del usuario ni `backend/data/` (de eso responde el
  `conftest.py`, y `test_aislamiento.py` lo vigila).

Dos casos del criterio de aceptación **no se cumplen hoy** y están marcados
con `xfail(strict=True)`: ver el bloque "Hallazgos" al final. No se arreglan
aquí — cambiar código de producción no entra en el PR de un test — y el
`strict=True` hace que salten en rojo el día que alguien los arregle, para
que el arreglo venga acompañado de su test de verdad.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

import pytest

import config
import dir_suggestions


# ----------------------------------------------------------------------
# Constantes del contrato, DECLARADAS aquí y no importadas del módulo bajo
# prueba. Es contabilidad por partida doble, como `RUTAS` en
# `test_aislamiento.py`: si estos valores se leyeran del propio código, un
# cambio de comportamiento actualizaría a la vez el hecho y su comprobación,
# y la suite seguiría en verde sin que nadie lo revisara.
# ----------------------------------------------------------------------

# Rutas absolutas que están fuera de cualquier raíz de test. Se usan SOLO en
# lectura (se pregunta si se aceptan; la respuesta debe ser "no"). Ninguna es
# destino de una escritura en ningún test de este archivo.
ABSOLUTAS_PROHIBIDAS = ["/etc", "/", "/usr", "/proc", "/var/log"]

# `~otro-usuario`. `root` existe en cualquier Linux; `nobody` también, y su
# home suele ser `/nonexistent`, así que entre los dos se cubre "el home del
# otro existe" y "no existe": el rechazo no puede depender de eso.
TILDES_DE_OTRO_USUARIO = ["~root", "~nobody"]

# El nombre de carpeta más hostil que puede teclear alguien: espacios, un
# separador de comandos, un encadenador, comillas y una sustitución de
# comandos. Si algo de esto llegara a una shell, `id` se ejecutaría. No lleva
# `$` a propósito: ver `test_una_variable_de_entorno_en_la_ruta_no_escapa`.
NOMBRE_HOSTIL = "mi carpeta; rm -rf * && echo 'ups' `id`"


class Escenario(NamedTuple):
    """Las piezas del terreno de juego, todas bajo el `tmp_path` del test."""

    raiz: Path  # la única raíz configurada
    fuera: Path  # hermana de la raíz: el "fuera" seguro
    secreto: Path  # un directorio dentro de `fuera`, el botín
    sub: Path  # subdirectorio legítimo de la raíz
    hondo: Path  # nieto de la raíz (para distinguir "inmediato" de "profundo")
    enlace_fuera: Path  # raiz/enlace_fuera -> fuera   (el ataque)
    enlace_dentro: Path  # raiz/enlace_dentro -> raiz/sub (el control positivo)
    oculta: Path  # raiz/.oculta
    fichero: Path  # raiz/notas.txt (no es un directorio)


@pytest.fixture
def escenario(allowed_root: Path, tmp_path: Path) -> Escenario:
    """Monta la raíz, el "fuera" y los dos symlinks (el que sale y el que no).

    Los DOS symlinks importan. El que sale de la raíz es el caso de ataque;
    el que se queda dentro es el control positivo, sin el cual un módulo que
    rechazara absolutamente todo pasaría todos los tests negativos.
    """
    raiz = allowed_root
    fuera = tmp_path / "fuera"
    secreto = fuera / "secreto"
    secreto.mkdir(parents=True, exist_ok=True)

    sub = raiz / "sub"
    hondo = sub / "hondo"
    hondo.mkdir(parents=True, exist_ok=True)
    oculta = raiz / ".oculta"
    oculta.mkdir(exist_ok=True)
    fichero = raiz / "notas.txt"
    fichero.write_text("no soy un directorio\n", encoding="utf-8")

    # `target_is_directory` es irrelevante en Linux, pero deja escrito en el
    # test qué clase de enlace se está plantando: uno de DIRECTORIO, que es
    # el que el navegador de carpetas seguiría.
    enlace_fuera = raiz / "enlace_fuera"
    enlace_fuera.symlink_to(fuera, target_is_directory=True)
    enlace_dentro = raiz / "enlace_dentro"
    enlace_dentro.symlink_to(sub, target_is_directory=True)

    return Escenario(
        raiz=raiz,
        fuera=fuera,
        secreto=secreto,
        sub=sub,
        hondo=hondo,
        enlace_fuera=enlace_fuera,
        enlace_dentro=enlace_dentro,
        oculta=oculta,
        fichero=fichero,
    )


def _fijar_raices(monkeypatch: pytest.MonkeyPatch, *raices: Path | str) -> None:
    """Reconfigura las raíces para un test concreto.

    `config.DIR_SUGGESTION_ROOTS` se lee en cada llamada (no se cachea), así
    que basta con parchear el atributo del módulo ya importado; recargar
    `config` dejaría a `main` sirviendo con los objetos viejos.
    """
    monkeypatch.setattr(config, "DIR_SUGGESTION_ROOTS", [str(r) for r in raices])


def _resolver_con_el_orden_invertido(q: str) -> Path | None:
    """Réplica de `resolve_within_roots` con la MUTACIÓN que se quiere cazar.

    Comprueba la contención sobre la ruta tal cual la escribió el usuario y
    solo después resuelve los enlaces. Se escribe entera aquí, sin reutilizar
    los helpers privados del módulo, para que siga siendo la mutación que
    describe aunque el módulo cambie por dentro.
    """
    raices = [Path(os.path.expanduser(r)).resolve() for r in config.DIR_SUGGESTION_ROOTS]
    objetivo = Path(os.path.expanduser(q.strip()))
    if not any(objetivo == r or objetivo.is_relative_to(r) for r in raices):
        return None
    objetivo = objetivo.resolve()  # ← demasiado tarde: ya ha dicho que sí
    return objetivo if objetivo.is_dir() else None


# ======================================================================
# Auto-tests: que el escenario distingue lo que dice distinguir.
# ======================================================================


def test_auto_el_enlace_de_ataque_parece_de_dentro_y_apunta_a_fuera(
    escenario: Escenario,
) -> None:
    """El escenario tiene la forma exacta que hace falta para discriminar.

    Si el enlace no fuera *léxicamente* hijo de la raíz, el orden invertido
    también lo rechazaría (por el camino equivocado) y el test de más abajo
    pasaría por casualidad. Y si su destino no estuviera realmente fuera,
    no habría nada que rechazar.
    """
    raiz = escenario.raiz.resolve()
    assert escenario.enlace_fuera.is_symlink()
    assert escenario.enlace_fuera.is_dir(), "el enlace debe seguir a un directorio"
    # Parece de dentro...
    assert escenario.enlace_fuera.parent.resolve() == raiz
    # ...y no lo es.
    assert not escenario.enlace_fuera.resolve().is_relative_to(raiz)
    assert escenario.enlace_fuera.resolve() == escenario.fuera.resolve()


def test_auto_con_el_orden_invertido_el_symlink_se_escapa(
    escenario: Escenario,
) -> None:
    """La prueba de que el detector detecta.

    Ejecuta la réplica mutada (contención antes de resolver) y comprueba que
    devuelve una ruta de FUERA de las raíces, mientras el módulo real
    devuelve `None`. Mientras estas dos aserciones convivan, el test
    `test_symlink_de_directorio_que_apunta_fuera_es_rechazado` no puede pasar
    por accidente: distingue de verdad entre los dos órdenes.
    """
    ruta = str(escenario.enlace_fuera)
    escapado = _resolver_con_el_orden_invertido(ruta)
    assert escapado == escenario.fuera.resolve(), (
        "la réplica mutada ya no se escapa; el escenario ha dejado de "
        "discriminar entre los dos órdenes y los tests de symlink de este "
        "archivo han perdido su valor"
    )
    assert dir_suggestions.resolve_within_roots(ruta) is None


def test_auto_todo_el_escenario_vive_bajo_el_tmp_del_test(
    escenario: Escenario, tmp_path: Path
) -> None:
    """Ni el "fuera" es de verdad fuera del sandbox.

    El escenario planta symlinks y crea carpetas. Que su destino esté bajo
    `tmp_path` es lo que hace que sea seguro hacerlo, y no algo que se pueda
    dejar a la vista de quien lea el fixture.
    """
    tmp = tmp_path.resolve()
    for nombre, ruta in escenario._asdict().items():
        assert ruta.resolve().is_relative_to(tmp), f"{nombre} -> {ruta} está fuera de tmp"


# ======================================================================
# El orden: resolver los enlaces ANTES de comprobar la contención.
# ======================================================================


def test_symlink_de_directorio_que_apunta_fuera_es_rechazado(
    escenario: Escenario,
) -> None:
    """EL test de esta historia.

    `raiz/enlace_fuera` empieza por la raíz carácter a carácter, así que
    cualquier comprobación de contención hecha sobre el texto lo da por
    bueno. Solo resolviendo el enlace primero se ve que el destino real está
    fuera. Es el único caso de todo el archivo que separa el orden correcto
    del incorrecto en `resolve_within_roots`.
    """
    assert dir_suggestions.resolve_within_roots(str(escenario.enlace_fuera)) is None


def test_symlink_como_componente_intermedio_tampoco_abre_la_puerta(
    escenario: Escenario,
) -> None:
    """El enlace no está al final de la ruta, sino en medio.

    `raiz/enlace_fuera/secreto` no es un enlace: es un directorio normal al
    que se llega *a través* de uno. Quien resolviera solo el último
    componente (o comprobara `is_symlink()` sobre el path completo) lo
    dejaría pasar.
    """
    ruta = escenario.raiz / "enlace_fuera" / "secreto"
    assert dir_suggestions.resolve_within_roots(str(ruta)) is None


def test_browse_no_entra_por_un_symlink_que_sale(escenario: Escenario) -> None:
    """El navegador de carpetas del modal de subida usa la misma puerta."""
    assert dir_suggestions.browse(str(escenario.enlace_fuera)) is None


def test_suggest_no_lista_a_traves_de_un_symlink_que_sale(
    escenario: Escenario,
) -> None:
    """Listar el contenido de fuera es la mitad barata del ataque.

    Con la barra final, `suggest` interpreta la ruta como "lista este
    directorio". Si el orden estuviera invertido, aquí saldría el inventario
    de `tmp_path/fuera` (`secreto`), que es información de fuera de las
    raíces aunque nadie llegue a escribir en ella.
    """
    assert dir_suggestions.suggest(str(escenario.enlace_fuera) + "/") == []


def test_create_dir_no_escribe_a_traves_de_un_symlink_que_sale(
    escenario: Escenario,
) -> None:
    """La mitad cara: crear carpetas fuera de las raíces.

    Dos vías, las dos rechazadas: el enlace como *padre* donde crear, y el
    enlace como *nombre* que crear (donde `mkdir(exist_ok=True)` no daría
    error y devolvería tan campante una ruta de fuera).
    """
    assert dir_suggestions.create_dir(str(escenario.enlace_fuera), "nueva") is None
    assert not (escenario.fuera / "nueva").exists()

    assert dir_suggestions.create_dir(str(escenario.raiz), "enlace_fuera") is None
    # Y el enlace sigue siendo un enlace: no se ha sustituido por una carpeta.
    assert escenario.enlace_fuera.is_symlink()


def test_un_symlink_que_apunta_dentro_de_la_raiz_sigue_funcionando(
    escenario: Escenario,
) -> None:
    """El control positivo, sin el cual los negativos no prueban nada.

    Un módulo que devolviera `None` a todo pasaría cada test de rechazo de
    este archivo. Lo que se exige no es "rechaza symlinks", es "resuelve el
    symlink y decide con el destino": si el destino está dentro, se acepta.
    """
    destino = dir_suggestions.resolve_within_roots(str(escenario.enlace_dentro))
    assert destino == escenario.sub.resolve()

    # Y también a través del enlace, no solo el enlace en sí.
    hondo = dir_suggestions.resolve_within_roots(
        str(escenario.raiz / "enlace_dentro" / "hondo")
    )
    assert hondo == escenario.hondo.resolve()

    # El navegador entra en él y lo hace por su ruta REAL, no por la del
    # enlace: subir un nivel desde ahí lleva a la raíz, no a "enlace_dentro".
    contenido = dir_suggestions.browse(str(escenario.enlace_dentro))
    assert contenido is not None
    assert contenido["path"] == str(escenario.sub.resolve())


# ======================================================================
# Traversal léxico: `..`
# ======================================================================

# Se enumeran las formas de escribir "sácame de aquí", no solo la canónica:
# el `..` suelto, el que atraviesa un subdirectorio, el encadenado que sube
# hasta la raíz del sistema y el que sube y vuelve a bajar a un hermano.
SALIDAS_CON_PUNTO_PUNTO = [
    "{raiz}/..",
    "{raiz}/../fuera",
    "{raiz}/sub/../../fuera",
    "{raiz}/../../..",
    "{raiz}/enlace_dentro/../../fuera",
    "{raiz}/./../fuera/secreto",
]
_IDS_PUNTO_PUNTO = [p.replace("{raiz}", "raiz") for p in SALIDAS_CON_PUNTO_PUNTO]


@pytest.mark.parametrize("plantilla", SALIDAS_CON_PUNTO_PUNTO, ids=_IDS_PUNTO_PUNTO)
def test_un_punto_punto_explicito_no_saca_de_la_raiz(
    escenario: Escenario, plantilla: str
) -> None:
    """`..` no se sanea quitándolo del texto: se normaliza y se comprueba."""
    ruta = plantilla.format(raiz=escenario.raiz)
    assert dir_suggestions.resolve_within_roots(ruta) is None
    assert dir_suggestions.browse(ruta) is None
    assert dir_suggestions.suggest(ruta + "/") == []


def test_una_ruta_que_sale_y_vuelve_a_entrar_se_acepta(escenario: Escenario) -> None:
    """El control positivo del `..`.

    `raiz/../home/sub` contiene un `..` y aun así termina dentro de la raíz.
    Rechazarla por contener la subcadena ".." sería el atajo equivocado: lo
    que decide es dónde acaba la ruta normalizada, no cómo se escribió.
    """
    ruta = f"{escenario.raiz}/../{escenario.raiz.name}/sub"
    assert dir_suggestions.resolve_within_roots(ruta) == escenario.sub.resolve()


# ======================================================================
# Rutas absolutas fuera de las raíces
# ======================================================================


@pytest.mark.parametrize("ruta", ABSOLUTAS_PROHIBIDAS, ids=ABSOLUTAS_PROHIBIDAS)
def test_una_ruta_absoluta_de_fuera_se_rechaza(ruta: str, allowed_root: Path) -> None:
    """Ninguna de estas es hija de la raíz de test, y todas existen.

    Que existan es el punto: un rechazo por "no existe" no probaría nada
    sobre las raíces. Se consultan en modo lectura; ningún test de este
    archivo escribe en ellas.
    """
    assert dir_suggestions.resolve_within_roots(ruta) is None
    assert dir_suggestions.browse(ruta) is None
    assert dir_suggestions.suggest(ruta + "/") == []


def test_el_hermano_de_la_raiz_se_rechaza_aunque_comparta_prefijo_textual(
    escenario: Escenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Empieza por" no es "está dentro de".

    Si la raíz es `.../roots/home`, entonces `.../roots/home-de-otro` empieza
    exactamente por ella como cadena de texto. Solo una comparación por
    componentes (`relative_to`) los distingue.
    """
    vecino = escenario.raiz.parent / (escenario.raiz.name + "-de-otro")
    vecino.mkdir()
    assert str(vecino).startswith(str(escenario.raiz)), "el escenario no discrimina"
    assert dir_suggestions.resolve_within_roots(str(vecino)) is None


def test_el_directorio_de_fuera_del_escenario_se_rechaza(
    escenario: Escenario,
) -> None:
    """El "fuera" seguro también es fuera: se pide por su ruta directa."""
    assert dir_suggestions.resolve_within_roots(str(escenario.fuera)) is None
    assert dir_suggestions.resolve_within_roots(str(escenario.secreto)) is None


# ======================================================================
# `~`: el del backend sí, el de otro usuario no
# ======================================================================


@pytest.mark.parametrize("tilde", TILDES_DE_OTRO_USUARIO, ids=TILDES_DE_OTRO_USUARIO)
def test_el_home_de_otro_usuario_se_rechaza(tilde: str) -> None:
    """`~root` es una ruta absoluta con disfraz: se expande y se filtra igual."""
    assert dir_suggestions.resolve_within_roots(tilde) is None
    assert dir_suggestions.browse(tilde) is None
    assert dir_suggestions.suggest(tilde + "/") == []


def test_la_tilde_a_secas_se_expande_al_home_del_backend_y_no_a_una_raiz(
    allowed_root: Path,
) -> None:
    """`~` significa "el home de quien ejecuta el backend", no "la raíz".

    Con las raíces apuntando a tmp (donde el home real no está), `~` tiene
    que quedar FUERA. Un módulo que tratara `~` como un alias de la primera
    raíz configurada devolvería aquí una ruta y el filtro dejaría de existir
    para el único token que todo el mundo teclea.
    """
    assert dir_suggestions.resolve_within_roots("~") is None
    assert dir_suggestions.resolve_within_roots(str(Path.home())) is None
    # Comprobación positiva de que la configuración del test es la que se cree.
    assert dir_suggestions.resolve_within_roots("") == allowed_root.resolve()


def test_la_tilde_a_secas_apunta_al_home_configurado_del_proceso(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La otra mitad: cuando el home SÍ es una raíz, `~` la alcanza.

    Se mueve `HOME` a la raíz de tmp (que es lo que define "el home del
    usuario que ejecuta el backend" en un proceso POSIX) en vez de apuntar
    las raíces al home real: así se prueba la expansión sin que ningún test
    liste ni escriba en el home de verdad.
    """
    monkeypatch.setenv("HOME", str(escenario.raiz))

    assert dir_suggestions.resolve_within_roots("~") == escenario.raiz.resolve()
    assert dir_suggestions.resolve_within_roots("~/sub") == escenario.sub.resolve()
    # Y la abreviatura que ve el frontend usa el `~`, que es su razón de ser.
    assert dir_suggestions.suggest("~/s") == ["~/sub"]
    assert dir_suggestions.browse("~")["path"] == "~"
    # Con el home movido, el de otro usuario sigue rechazado.
    assert dir_suggestions.resolve_within_roots("~root") is None


def test_una_variable_de_entorno_en_la_ruta_no_escapa_de_las_raices(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`$VAR` se expande antes de filtrar, así que no es una puerta trasera.

    El módulo pasa lo tecleado por `expandvars`. Eso es cómodo (`$HOME/x`
    funciona) y sería un agujero si la expansión ocurriera *después* del
    filtro: bastaría con una variable que apuntara fuera. Aquí se comprueba
    que el filtro ve el valor ya expandido.

    Efecto colateral conocido: una carpeta cuyo nombre contenga un `$`
    literal se vuelve inalcanzable, porque `expandvars` se come el nombre de
    la variable. Por eso `NOMBRE_HOSTIL` no lleva `$`.
    """
    monkeypatch.setenv("MUXSPACE_TEST_DESTINO", str(escenario.fuera))
    assert dir_suggestions.resolve_within_roots("$MUXSPACE_TEST_DESTINO") is None
    assert dir_suggestions.suggest("$MUXSPACE_TEST_DESTINO/") == []

    # Control positivo: la expansión funciona de verdad, no es que la
    # variable se quedara sin expandir y la ruta fallara por inexistente.
    monkeypatch.setenv("MUXSPACE_TEST_DESTINO", str(escenario.sub))
    assert (
        dir_suggestions.resolve_within_roots("$MUXSPACE_TEST_DESTINO")
        == escenario.sub.resolve()
    )


# ======================================================================
# Las raíces configuradas
# ======================================================================


def test_una_raiz_configurada_que_no_existe_se_ignora_y_las_demas_siguen(
    escenario: Escenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `MUXSPACE_DIR_SUGGESTION_ROOTS` con una ruta muerta no tumba el panel.

    Es el caso real de un despliegue donde alguien configuró una raíz que
    todavía no está montada. El modo de fallo aceptable es "esa raíz no
    aparece"; el inaceptable es una excepción que deja sin navegador de
    carpetas ni subida de archivos a quien sí tiene las otras raíces bien.
    """
    inexistente = tmp_path / "raiz-que-no-existe"
    assert not inexistente.exists()
    _fijar_raices(monkeypatch, inexistente, escenario.raiz)

    assert dir_suggestions.suggest("") == [str(escenario.raiz.resolve())]
    assert dir_suggestions.resolve_within_roots("") == escenario.raiz.resolve()
    assert dir_suggestions.resolve_within_roots(str(escenario.sub)) == (
        escenario.sub.resolve()
    )
    # La raíz muerta no se convierte en una puerta: pedirla sigue dando None.
    assert dir_suggestions.resolve_within_roots(str(inexistente)) is None


def test_resolve_within_roots_vacio_devuelve_la_primera_raiz(
    escenario: Escenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sin ruta, el navegador arranca en la primera raíz configurada.

    Se prueba con DOS raíces y luego con el orden invertido. Con una sola
    raíz, "la primera" y "la única" son lo mismo y el test pasaría aunque el
    módulo devolviera cualquiera de ellas.
    """
    segunda = tmp_path / "roots" / "segunda"
    segunda.mkdir(parents=True)

    _fijar_raices(monkeypatch, escenario.raiz, segunda)
    assert dir_suggestions.resolve_within_roots("") == escenario.raiz.resolve()

    _fijar_raices(monkeypatch, segunda, escenario.raiz)
    assert dir_suggestions.resolve_within_roots("") == segunda.resolve()


@pytest.mark.parametrize("vacio", ["", "   ", None], ids=["cadena-vacia", "espacios", "None"])
def test_lo_que_cuenta_como_ruta_vacia(
    escenario: Escenario, vacio: str | None
) -> None:
    """`""`, espacios y `None` son la misma cosa: "empieza por el principio".

    El `None` no es teórico: llega desde un query param opcional de FastAPI.
    """
    assert dir_suggestions.resolve_within_roots(vacio) == escenario.raiz.resolve()


def test_con_varias_raices_las_dos_son_navegables_y_nada_mas(
    escenario: Escenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Varias raíces no es "varias oportunidades de colarse".

    Cada raíz abre exactamente su propio subárbol: una ruta de la segunda se
    acepta, pero su hermano (que no es de ninguna de las dos) sigue fuera.
    """
    segunda = tmp_path / "roots" / "segunda"
    (segunda / "proyectos").mkdir(parents=True)
    _fijar_raices(monkeypatch, escenario.raiz, segunda)

    assert dir_suggestions.resolve_within_roots(str(segunda / "proyectos")) == (
        segunda / "proyectos"
    ).resolve()
    assert dir_suggestions.resolve_within_roots(str(escenario.sub)) == (
        escenario.sub.resolve()
    )
    assert dir_suggestions.resolve_within_roots(str(escenario.fuera)) is None
    assert sorted(dir_suggestions.suggest("")) == sorted(
        [str(escenario.raiz.resolve()), str(segunda.resolve())]
    )


def test_un_symlink_que_sale_de_una_raiz_pero_cae_en_otra_se_acepta(
    escenario: Escenario, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lo que decide es el conjunto de raíces, no la raíz por la que entraste.

    Es el complemento del test del symlink de ataque: el enlace se resuelve
    y el destino se compara contra TODAS las raíces. Si alguien "arreglara"
    el módulo comparando solo contra la raíz de la que cuelga la ruta
    tecleada, este caso pasaría a rechazarse sin motivo.
    """
    segunda = tmp_path / "roots" / "segunda"
    segunda.mkdir(parents=True)
    _fijar_raices(monkeypatch, escenario.raiz, segunda)

    puente = escenario.raiz / "a_la_segunda"
    puente.symlink_to(segunda, target_is_directory=True)
    assert dir_suggestions.resolve_within_roots(str(puente)) == segunda.resolve()


def test_las_raices_repetidas_no_se_sugieren_dos_veces(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Escribir la misma raíz de dos formas no la duplica en el desplegable."""
    _fijar_raices(
        monkeypatch, escenario.raiz, escenario.raiz, str(escenario.raiz) + "/"
    )
    assert dir_suggestions.suggest("") == [str(escenario.raiz.resolve())]


def test_sin_ninguna_raiz_configurada_no_hay_nada_que_navegar(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El modo de fallo seguro: cero raíces es cero acceso, no acceso total."""
    _fijar_raices(monkeypatch)
    assert dir_suggestions.suggest("") == []
    assert dir_suggestions.resolve_within_roots("") is None
    assert dir_suggestions.resolve_within_roots(str(escenario.sub)) is None
    assert dir_suggestions.browse(str(escenario.raiz)) is None
    assert dir_suggestions.create_dir(str(escenario.raiz), "nueva") is None


# ======================================================================
# `create_dir`
# ======================================================================

# Nombres que, concatenados al padre, apuntan fuera. El último es el más
# sucio: `Path("/a/b") / "/x"` es `/x` — pathlib DESCARTA el padre cuando el
# segundo operando es absoluto. Un `parent / name` sin comprobar después
# escribiría en la ruta absoluta que le pasen.
NOMBRES_QUE_SE_SALEN = ["..", "../fuera", "sub/../..", "../../..", "{fuera}/creada"]
_IDS_NOMBRES = ["..", "../fuera", "sub/../..", "../../..", "absoluta-fuera"]


@pytest.mark.parametrize("plantilla", NOMBRES_QUE_SE_SALEN, ids=_IDS_NOMBRES)
def test_create_dir_rechaza_un_nombre_que_apunta_fuera(
    escenario: Escenario, plantilla: str, tmp_path: Path
) -> None:
    """El nombre se une al padre y el resultado se vuelve a filtrar.

    Que el padre esté dentro de una raíz no basta: `create_dir` compone la
    ruta final y la comprueba otra vez. Se verifica también que no quedó
    nada creado, porque un `mkdir` que fallara *después* de escribir sería
    igual de grave que uno que devolviera la ruta.
    """
    antes = sorted(p.name for p in tmp_path.rglob("*"))
    nombre = plantilla.format(fuera=escenario.fuera)

    assert dir_suggestions.create_dir(str(escenario.raiz), nombre) is None

    assert sorted(p.name for p in tmp_path.rglob("*")) == antes, (
        "create_dir rechazó el nombre pero dejó algo escrito en disco"
    )


def test_create_dir_con_un_nombre_valido_crea_dentro_de_la_raiz(
    escenario: Escenario,
) -> None:
    """El control positivo de `create_dir`: crea, y donde debe."""
    devuelto = dir_suggestions.create_dir(str(escenario.raiz), "nueva")

    creada = escenario.raiz / "nueva"
    assert creada.is_dir()
    assert creada.resolve().is_relative_to(escenario.raiz.resolve())
    # La ruta abreviada es la que el frontend enseña y vuelve a mandar: tiene
    # que ser una ruta que el propio módulo acepte después.
    assert devuelto == str(creada.resolve())
    assert dir_suggestions.resolve_within_roots(devuelto) == creada.resolve()


def test_create_dir_devuelve_la_ruta_abreviada_con_tilde(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cuando la carpeta cae bajo el home del backend, se devuelve con `~`."""
    monkeypatch.setenv("HOME", str(escenario.raiz))
    assert dir_suggestions.create_dir(str(escenario.raiz), "nueva") == "~/nueva"
    assert dir_suggestions.create_dir("~/sub", "otra") == "~/sub/otra"
    assert (escenario.sub / "otra").is_dir()


def test_create_dir_no_interpreta_el_nombre_como_una_orden_de_shell(
    escenario: Escenario,
) -> None:
    """Espacios, `;`, `&&`, comillas y backticks son solo caracteres.

    Aquí no hay shell (es `Path.mkdir`), y este test existe para que siga sin
    haberla: si alguien reimplementara la creación con `subprocess` y
    `shell=True`, el `rm -rf *` borraría la raíz y el `id` se ejecutaría.
    """
    hermanos_antes = {p.name for p in escenario.raiz.iterdir()}

    devuelto = dir_suggestions.create_dir(str(escenario.raiz), NOMBRE_HOSTIL)

    creada = escenario.raiz / NOMBRE_HOSTIL
    assert creada.is_dir(), "el nombre no se creó literalmente"
    assert devuelto == str(creada.resolve())
    # Exactamente una entrada nueva: ni se ejecutó nada, ni se borró nada.
    assert {p.name for p in escenario.raiz.iterdir()} == hermanos_antes | {
        NOMBRE_HOSTIL
    }
    # Y sigue siendo navegable con su nombre literal.
    assert dir_suggestions.resolve_within_roots(str(creada)) == creada.resolve()


def test_create_dir_con_el_padre_fuera_de_las_raices_no_escribe(
    escenario: Escenario,
) -> None:
    """El padre pasa por la misma puerta que todo lo demás.

    Los padres que se prueban están todos bajo `tmp_path` a propósito: si
    alguien rompiera el filtro, este test tiene que ponerse en rojo, no
    crear una carpeta en el home real de quien corre la suite. Que `~` esté
    fuera de las raíces se comprueba en modo lectura, en
    `test_la_tilde_a_secas_se_expande_al_home_del_backend_y_no_a_una_raiz`.
    """
    assert dir_suggestions.create_dir(str(escenario.fuera), "nueva") is None
    assert not (escenario.fuera / "nueva").exists()
    assert dir_suggestions.create_dir(str(escenario.secreto), "nueva") is None
    assert not (escenario.secreto / "nueva").exists()
    assert dir_suggestions.create_dir(str(escenario.raiz / "no-existe"), "x") is None


def test_create_dir_no_crea_arboles_intermedios(escenario: Escenario) -> None:
    """`mkdir(parents=False)`: un nombre con separador no fabrica el camino.

    Que devuelva `None` es secundario; lo que importa es que no se haya
    creado `raiz/a`. Crear jerarquías enteras desde un campo de texto es
    otra funcionalidad, y no una que se deba obtener por accidente.
    """
    assert dir_suggestions.create_dir(str(escenario.raiz), "a/b") is None
    assert not (escenario.raiz / "a").exists()


def test_create_dir_sobre_una_carpeta_que_ya_existe_es_idempotente(
    escenario: Escenario,
) -> None:
    """Repetir la creación no falla ni borra lo que hay dentro."""
    assert dir_suggestions.create_dir(str(escenario.raiz), "sub") == (
        str(escenario.sub.resolve())
    )
    assert escenario.hondo.is_dir(), "el contenido previo sigue ahí"


# ======================================================================
# `browse`
# ======================================================================


def test_browse_de_una_carpeta_inexistente_devuelve_none_sin_excepcion(
    escenario: Escenario,
) -> None:
    """El endpoint lo traduce a 404; una excepción sería un 500.

    Un 500 en `/api/dir-browse` no es solo feo: distingue "no existe" de
    "existe pero no puedo", que es exactamente lo que no se le quiere contar
    a quien está sondeando rutas.
    """
    assert dir_suggestions.browse(str(escenario.raiz / "no-existe")) is None
    assert dir_suggestions.browse(str(escenario.fuera / "tampoco")) is None


def test_browse_de_un_fichero_no_lo_confunde_con_una_carpeta(
    escenario: Escenario,
) -> None:
    """`notas.txt` está dentro de la raíz y aun así no es navegable."""
    assert dir_suggestions.browse(str(escenario.fichero)) is None
    assert dir_suggestions.resolve_within_roots(str(escenario.fichero)) is None


def test_browse_en_la_raiz_no_deja_subir_de_nivel(escenario: Escenario) -> None:
    """`parent` a `None` es el tope del navegador.

    Sin esto, la flecha "subir" del modal de subida sería un traversal con
    interfaz gráfica: un clic de más y estarías en `tmp_path`, fuera de la
    raíz.
    """
    contenido = dir_suggestions.browse(str(escenario.raiz))
    assert contenido is not None
    assert contenido["parent"] is None
    assert contenido["path"] == str(escenario.raiz.resolve())


def test_browse_dentro_de_la_raiz_si_deja_subir_hasta_la_raiz(
    escenario: Escenario,
) -> None:
    """El control positivo de `parent`: se sube hasta la raíz y ahí se para."""
    contenido = dir_suggestions.browse(str(escenario.sub))
    assert contenido is not None
    assert contenido["parent"] == str(escenario.raiz.resolve())

    # Y ese `parent` es una ruta que el módulo vuelve a aceptar (el frontend
    # la manda tal cual en la petición siguiente).
    arriba = dir_suggestions.browse(contenido["parent"])
    assert arriba is not None
    assert arriba["parent"] is None


def test_browse_sin_ruta_arranca_en_la_primera_raiz(escenario: Escenario) -> None:
    """La pantalla inicial del modal de subida."""
    contenido = dir_suggestions.browse("")
    assert contenido is not None
    assert contenido["path"] == str(escenario.raiz.resolve())
    assert contenido["parent"] is None


def test_browse_lista_solo_directorios_y_esconde_los_ocultos(
    escenario: Escenario,
) -> None:
    """Ni ficheros ni `.loquesea` en el navegador de carpetas."""
    contenido = dir_suggestions.browse(str(escenario.raiz))
    assert contenido is not None
    assert str(escenario.sub.resolve()) in contenido["dirs"]
    assert not any("notas.txt" in d for d in contenido["dirs"])
    assert not any(".oculta" in d for d in contenido["dirs"])


def test_browse_de_una_carpeta_sin_permisos_devuelve_vacio_sin_excepcion(
    escenario: Escenario,
) -> None:
    """Un directorio ilegible es un caso normal en el home de cualquiera."""
    cerrada = escenario.raiz / "cerrada"
    cerrada.mkdir()
    (cerrada / "dentro").mkdir()
    os.chmod(cerrada, 0o000)
    try:
        contenido = dir_suggestions.browse(str(cerrada))
        assert contenido is not None
        assert contenido["dirs"] == []
        assert dir_suggestions.suggest(str(cerrada) + "/") == []
    finally:
        # Sin esto, la limpieza de `tmp_path` que hace pytest no puede entrar.
        os.chmod(cerrada, 0o755)


# ======================================================================
# `suggest`
# ======================================================================


def test_suggest_con_prefijo_devuelve_solo_los_hijos_inmediatos_que_casan(
    escenario: Escenario,
) -> None:
    """Autocompletado: hermanos que empiezan por lo tecleado, y nada más.

    Ni el nieto (`sub/hondo`, que no es inmediato), ni el fichero
    (`notas.txt`), ni los hermanos que no casan.
    """
    assert dir_suggestions.suggest(f"{escenario.raiz}/s") == [
        str(escenario.sub.resolve())
    ]
    assert dir_suggestions.suggest(f"{escenario.raiz}/no-casa-con-nada") == []


def test_suggest_sin_nada_escrito_ofrece_las_raices(escenario: Escenario) -> None:
    """El punto de partida del desplegable son las raíces, no el sistema."""
    assert dir_suggestions.suggest("") == [str(escenario.raiz.resolve())]


def test_suggest_de_un_directorio_de_fuera_no_lo_lista(
    escenario: Escenario,
) -> None:
    """El caso directo: teclear una ruta de fuera no devuelve su inventario."""
    assert dir_suggestions.suggest(str(escenario.fuera) + "/") == []
    assert dir_suggestions.suggest(str(escenario.fuera) + "/sec") == []
    # Y su padre tampoco, que es por donde se llegaría a él.
    assert dir_suggestions.suggest(str(escenario.fuera.parent) + "/") == []


def test_suggest_esconde_los_ocultos_salvo_que_se_esten_tecleando(
    escenario: Escenario,
) -> None:
    """`.config` no aparece por sorpresa, pero se puede pedir por su nombre."""
    assert str(escenario.oculta.resolve()) not in dir_suggestions.suggest(
        f"{escenario.raiz}/"
    )
    assert dir_suggestions.suggest(f"{escenario.raiz}/.o") == [
        str(escenario.oculta.resolve())
    ]


def test_suggest_respeta_el_limite(escenario: Escenario) -> None:
    """El desplegable no se convierte en un volcado del directorio."""
    for i in range(5):
        (escenario.raiz / f"muchas-{i}").mkdir()
    assert len(dir_suggestions.suggest(f"{escenario.raiz}/muchas-", limit=2)) == 2


def test_la_barra_final_decide_si_se_lista_la_carpeta_o_sus_hermanas(
    escenario: Escenario,
) -> None:
    """Las dos ramas de `suggest`, y que ninguna se sale de las raíces.

    Sin barra, lo escrito es "un nombre a medio teclear": se lista el PADRE
    filtrando por ese prefijo. Con barra, es "entra aquí": se lista la
    carpeta. La distinción importa para el filtro, porque cada rama comprueba
    la contención de un directorio distinto — y con `fuera`, que existe y
    está escrito entero, las dos devuelven vacío.
    """
    assert dir_suggestions.suggest(str(escenario.sub)) == [
        str(escenario.sub.resolve())
    ]
    assert dir_suggestions.suggest(str(escenario.sub) + "/") == [
        str(escenario.hondo.resolve())
    ]
    assert dir_suggestions.suggest(str(escenario.fuera)) == []
    assert dir_suggestions.suggest(str(escenario.fuera) + "/") == []


def test_suggest_lista_la_raiz_aunque_se_escriba_de_forma_retorcida(
    escenario: Escenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una raíz escrita con un `..` por medio sigue siendo la raíz.

    Con la raíz puesta en `sub`, la ruta `sub/../sub` no coincide con
    ninguna raíz *como texto* y su padre (`sub/..`, o sea la carpeta de
    arriba) está fuera. El módulo tiene una segunda oportunidad para estos
    casos: si lo tecleado resuelve a un directorio que cae bajo una raíz, se
    lista. Es cómodo, y es seguro por el motivo de siempre: se resuelve
    antes de comprobar. La otra mitad del test es esa: la misma vuelta
    acabando un nivel más arriba (fuera de la raíz) no lista nada.
    """
    _fijar_raices(monkeypatch, escenario.sub)
    retorcida = f"{escenario.sub}/../{escenario.sub.name}"

    assert dir_suggestions.suggest(retorcida) == [str(escenario.hondo.resolve())]
    assert dir_suggestions.suggest(f"{escenario.sub}/../") == []


# ======================================================================
# Hallazgos: casos del criterio de aceptación que HOY no se cumplen.
#
# Van con `xfail(strict=True)` a propósito. No se arreglan aquí (cambiar
# `dir_suggestions.py` no entra en el PR de un test) y no se borran (el
# criterio de aceptación los pide). `strict=True` es la parte importante: el
# día que alguien arregle el módulo, estos tests pasarán, el XPASS se
# reportará como FALLO y quien arregle tendrá que venir a quitar la marca.
# Ninguno de los dos permite escribir fuera de las raíces: el primero filtra
# información y el segundo tumba la petición.
# ======================================================================


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HALLAZGO: `suggest` y `browse` no filtran los HIJOS. Un symlink "
        "plantado dentro de una raíz y apuntando fuera se lista, y como la "
        "abreviatura resuelve el enlace, lo que se muestra es la ruta real "
        "de fuera de las raíces. No permite entrar (resolve_within_roots lo "
        "sigue rechazando), pero revela rutas del sistema de ficheros a "
        "quien pueda crear un enlace en la raíz. Falta un _is_within sobre "
        "cada hijo antes de listarlo."
    ),
)
def test_suggest_nunca_ofrece_algo_de_fuera_de_las_raices(
    escenario: Escenario,
) -> None:
    """Ninguna sugerencia puede caer fuera de las raíces configuradas."""
    raiz = escenario.raiz.resolve()
    sugerencias = dir_suggestions.suggest(f"{escenario.raiz}/e")
    for s in sugerencias:
        assert Path(s).resolve().is_relative_to(raiz), f"{s} está fuera de la raíz"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HALLAZGO: un bucle de symlinks dentro de una raíz hace que "
        "`Path.resolve()` lance RuntimeError (Python <=3.12 convierte el "
        "ELOOP), y `resolve_within_roots` solo captura OSError. La "
        "excepción sube hasta el endpoint: 500 en vez del rechazo limpio "
        "que promete el contrato (`None`). Lo puede provocar cualquiera que "
        "pueda crear un enlace dentro de la raíz, incluido el propio usuario "
        "sin querer."
    ),
)
def test_un_bucle_de_symlinks_se_rechaza_sin_excepcion(
    escenario: Escenario,
) -> None:
    """Un enlace que apunta a sí mismo no es navegable, pero tampoco revienta."""
    bucle = escenario.raiz / "bucle"
    bucle.symlink_to(bucle)
    assert dir_suggestions.resolve_within_roots(str(bucle)) is None
    assert dir_suggestions.browse(str(bucle)) is None
    assert dir_suggestions.suggest(str(bucle) + "/") == []
