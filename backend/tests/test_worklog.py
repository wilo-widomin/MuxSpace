"""El registro de tiempo de trabajo por espacio.

## Qué se prueba y por qué así

Este registro existe para responder «cuántas horas MÍAS lleva este proyecto»,
y su forma de fallar no es reventar: es **dar un número creíble y falso**. Un
total inflado por dos pestañas, o una jornada partida por la zona horaria, no
levantan ningún error — se leen como un dato bueno y se decide con ellos.

Por eso los tests van contra las tres formas de mentir:

1. **Contar de más.** El invariante principal: la suma de todos los espacios
   en cualquier intervalo nunca supera el tiempo transcurrido. Aquí no se
   comprueba una suma, se comprueba que el esquema lo impide (la ranura es
   clave primaria), que es lo que hace el invariante estructural.
2. **Contar lo que no es.** Un latido es entrada del usuario. Lo que no puede
   pasar es que el tiempo aparezca solo.
3. **Contar en el día equivocado.** Agrupar en UTC parte la jornada de noche.

El reloj se inyecta (`ahora=`) en vez de esperar: un test que duerme 30
segundos para ver cambiar de ranura no se ejecuta nunca.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import worklog


@pytest.fixture(autouse=True)
def base_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Cada test con su base: nunca se toca el registro real del usuario."""
    destino = tmp_path / "worklog.db"
    monkeypatch.setattr(worklog, "_DB_PATH", destino)
    return destino


def epoch(texto: str) -> float:
    """'2026-08-15 09:00:00' (UTC) -> epoch."""
    return datetime.fromisoformat(texto).replace(tzinfo=timezone.utc).timestamp()


def test_dos_latidos_en_la_misma_ranura_cuentan_una_vez() -> None:
    """El caso de las dos pestañas: no se puede inflar el total latiendo más.

    Es el invariante principal, y aquí se ve como lo que es: una propiedad del
    esquema, no una suma que haya que vigilar.
    """
    base = epoch("2026-08-15 09:00:00")
    for desplazamiento in (0, 5, 10, 29):
        worklog.registrar("sp_a", ahora=base + desplazamiento)

    assert worklog.resumen()["total_seconds"] == worklog.SLOT_SECONDS


def test_dos_espacios_a_la_vez_no_superan_el_tiempo_transcurrido() -> None:
    """Dos pestañas en espacios distintos creyéndose ambas activas.

    Sin la ranura como clave, cada minuto de reloj podría apuntarse dos veces
    y el total del día superaría las 24 h sin que nada fallara.
    """
    base = epoch("2026-08-15 09:00:00")
    worklog.registrar("sp_a", ahora=base)
    worklog.registrar("sp_b", ahora=base + 1)  # otra pestaña, misma ranura

    datos = worklog.resumen()
    transcurrido = worklog.SLOT_SECONDS
    assert datos["total_seconds"] <= transcurrido
    assert sum(e["seconds"] for e in datos["by_space"]) <= transcurrido
    # Y se la queda quien llegó primero, de forma determinista.
    assert [e["space"] for e in datos["by_space"]] == ["sp_a"]


def test_sin_latidos_no_pasa_el_tiempo() -> None:
    """La salida del terminal no llega hasta aquí: sin entrada, cero.

    Es la traducción a este módulo de la regla que da sentido a todo el
    registro. Si algún día alguien engancha el tráfico del PTY, el total
    dejaría de ser cero con el usuario ausente.
    """
    assert worklog.resumen()["total_seconds"] == 0
    assert worklog.resumen()["by_space"] == []


def test_una_hora_de_trabajo_son_una_hora_de_ranuras() -> None:
    base = epoch("2026-08-15 09:00:00")
    for n in range(120):  # 120 ranuras de 30 s = 1 h
        worklog.registrar("sp_a", ahora=base + n * worklog.SLOT_SECONDS)

    assert worklog.resumen()["total_seconds"] == 3600


def test_el_rango_recorta_por_los_dos_lados() -> None:
    base = epoch("2026-08-15 09:00:00")
    for n in range(10):
        worklog.registrar("sp_a", ahora=base + n * worklog.SLOT_SECONDS)

    dentro = worklog.resumen(desde=base + 2 * 30, hasta=base + 5 * 30)

    # Ranuras 2, 3, 4 y 5: el `hasta` incluye la ranura en la que cae.
    assert dentro["total_seconds"] == 4 * worklog.SLOT_SECONDS


def test_agrupa_por_dia_local_y_no_por_utc() -> None:
    """A las 23:30 en Madrid (UTC+2) es el mismo día, no el siguiente.

    Sin el desfase, la última hora y media de cada jornada se contabilizaría
    en el día siguiente y los totales por día quedarían corridos.
    """
    # 2026-08-15 21:30 UTC = 2026-08-15 23:30 en UTC+2.
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 21:30:00"))

    en_utc = worklog.resumen(tz_offset_min=0)["by_day"]
    en_madrid = worklog.resumen(tz_offset_min=120)["by_day"]

    assert [d["day"] for d in en_utc] == ["2026-08-15"]
    assert [d["day"] for d in en_madrid] == ["2026-08-15"]

    # Y a las 22:30 UTC ya es el 16 en Madrid: ahí es donde se ve la diferencia.
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 22:30:00"))
    dias_madrid = [d["day"] for d in worklog.resumen(tz_offset_min=120)["by_day"]]
    assert dias_madrid == ["2026-08-15", "2026-08-16"]


def test_separa_las_horas_con_un_agente_delante() -> None:
    """`claude` frente a cualquier otra cosa, dentro del mismo espacio."""
    base = epoch("2026-08-15 09:00:00")
    worklog.registrar("sp_a", "MUXSPACE", "claude", ahora=base)
    worklog.registrar("sp_a", "TERM", "zsh", ahora=base + 30)

    espacio = worklog.resumen()["by_space"][0]

    assert espacio["seconds"] == 60
    assert espacio["claude_seconds"] == 30


def test_suspender_el_equipo_no_genera_un_bloque_gigante() -> None:
    """Ocho horas sin latidos son ocho horas sin registrar, no un tramo.

    Con eventos de inicio/fin, dormir el portátil con la pestaña abierta
    dejaría un tramo de ocho horas. Con ranuras, el hueco es un hueco.
    """
    base = epoch("2026-08-15 09:00:00")
    worklog.registrar("sp_a", ahora=base)
    worklog.registrar("sp_a", ahora=base + 8 * 3600)  # al despertar

    assert worklog.resumen()["total_seconds"] == 2 * worklog.SLOT_SECONDS


def test_la_hora_la_pone_el_servidor() -> None:
    """Sin `ahora`, la ranura sale del reloj del servidor, no del cliente."""
    inicio = worklog.registrar("sp_a")
    assert abs(inicio - worklog.slot_de(time.time())) <= worklog.SLOT_SECONDS


def test_dice_desde_cuando_hay_datos() -> None:
    """Un total pequeño no debe confundirse con "el registro es de ayer"."""
    assert worklog.resumen()["since"] is None
    base = epoch("2026-08-15 09:00:00")
    worklog.registrar("sp_a", ahora=base)
    assert worklog.resumen()["since"] == worklog.slot_de(base)


# ----------------------------------------------------------------------
# Por HTTP
# ----------------------------------------------------------------------


def test_el_latido_registra_y_el_resumen_lo_devuelve(client_auth) -> None:
    """El camino completo, que es donde se ven las costuras del contrato."""
    resp = client_auth.post("/api/worklog/beat", json={"space": "sp_a"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["slot_seconds"] == worklog.SLOT_SECONDS

    resumen = client_auth.get("/api/worklog/summary").json()
    assert resumen["total_seconds"] == worklog.SLOT_SECONDS
    assert resumen["by_space"][0]["space"] == "sp_a"


def test_un_espacio_vacio_se_registra_como_sin_asignar(client_auth) -> None:
    """Si no se guardara, la suma de espacios dejaría de ser comparable.

    El invariante se enuncia contra el tiempo transcurrido: un tramo que no
    pertenece a ningún espacio tiene que estar en algún sitio, o la resta no
    cuadra y no se sabe si falta o sobra.
    """
    client_auth.post("/api/worklog/beat", json={"space": ""})
    resumen = client_auth.get("/api/worklog/summary").json()
    assert resumen["by_space"][0]["space"] == "unassigned"


def test_el_resumen_acepta_rango_y_zona(client_auth) -> None:
    resp = client_auth.get("/api/worklog/summary?desde=0&hasta=1&tz=120")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_seconds"] == 0


def test_una_zona_horaria_imposible_no_rompe_el_resumen(client_auth) -> None:
    """El desfase viene del navegador; recortarlo evita agrupar por fechas
    absurdas si algún día llega basura."""
    assert client_auth.get("/api/worklog/summary?tz=99999").status_code == 200
