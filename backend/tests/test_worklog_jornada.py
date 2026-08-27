"""El modo 'workday': la jornada entera menos las pausas marcadas.

## Por qué existe este modo

El modo 'measured' pregunta «¿tocaste algo hace menos de tres minutos?», y con
la forma real de trabajar —lanzar un agente y mirar otra cosa mientras
construye— la respuesta es que no casi todo el rato. Medido sobre un día real
del usuario: 3 h 25 apuntadas de una jornada de 8 h 30.

El modo 'workday' invierte la carga de la prueba. La jornada cuenta entera
entre la primera y la última señal del día, y lo que hay que declarar es la
**ausencia**, no el trabajo. Las señales —latidos y transcripts— dejan de
decidir *si* trabajaste y pasan a decidir solo *en qué proyecto*.

## Cómo puede mentir este modo

Al revés que el otro: **contando de más**. Sus tres formas de fallar son
dejarse una pausa sin restar, estirar la jornada más allá del día (la noche
entre dos jornadas), y no parar nunca si se olvida marcar el final. Contra
esas tres van los tests.

Y sigue vigente el invariante de siempre, que ningún modo puede romper: una
ranura tiene un único dueño, así que la suma de los espacios jamás supera el
tiempo transcurrido.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import claude_transcript
import library_store
import worklog

MINUTO = 60
HORA = 3600


@pytest.fixture(autouse=True)
def base_temporal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    destino = tmp_path / "worklog.db"
    monkeypatch.setattr(worklog, "_DB_PATH", destino)
    return destino


def epoch(texto: str) -> float:
    """'2026-08-15 09:00:00' (UTC) -> epoch."""
    return datetime.fromisoformat(texto).replace(tzinfo=timezone.utc).timestamp()


def total(**kwargs) -> int:
    return worklog.resumen(modo="workday", **kwargs)["total_seconds"]


# --- La jornada ---------------------------------------------------------


def test_la_jornada_cuenta_entera_entre_la_primera_y_la_ultima_senal():
    """Dos latidos separados por una hora son una hora, no un minuto.

    Es el cambio de fondo respecto a 'measured': el rato de en medio no dejó
    rastro porque el agente estaba construyendo, y ese rato es trabajo.
    """
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 10:00:00"))

    assert total() == HORA + worklog.SLOT_SECONDS


def test_en_modo_medido_ese_mismo_dia_cuenta_solo_lo_que_dejo_rastro():
    """El contraste que justifica todo el modo: los mismos datos, un minuto."""
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 10:00:00"))

    assert worklog.resumen(modo="measured")["total_seconds"] == 2 * worklog.SLOT_SECONDS


def test_la_jornada_no_salta_de_un_dia_al_siguiente():
    """Sin esto, la noche entre dos jornadas contaría como trabajo.

    Es el fallo más caro del modo: no da un número raro, da uno grande y
    creíble.
    """
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 18:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-16 09:00:00"))

    assert total() == 2 * worklog.SLOT_SECONDS


# --- Las pausas ---------------------------------------------------------


def test_una_pausa_marcada_se_resta_de_la_jornada():
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 12:00:00"))
    worklog.marcar_pausa(epoch("2026-08-15 10:00:00"), epoch("2026-08-15 10:59:30"))

    # Tres horas de jornada menos una de pausa.
    assert total() == 2 * HORA + worklog.SLOT_SECONDS


def test_pausar_y_reanudar_dejan_la_pausa_cerrada():
    inicio = worklog.pausar(ahora=epoch("2026-08-15 10:00:00"))
    cerrada = worklog.reanudar(ahora=epoch("2026-08-15 10:30:00"))

    assert cerrada == {"start": inicio, "end": epoch("2026-08-15 10:30:30")}
    assert worklog.pausas()[0]["open"] is False


def test_pausar_dos_veces_no_pierde_el_inicio_real():
    """Pulsar «me voy» otra vez no puede recortar la ausencia ya empezada."""
    primero = worklog.pausar(ahora=epoch("2026-08-15 10:00:00"))
    segundo = worklog.pausar(ahora=epoch("2026-08-15 10:20:00"))

    assert primero == segundo
    assert len(worklog.pausas()) == 1


def test_una_pausa_abierta_no_se_cierra_sola():
    """Cerrarla a ojo apuntaría trabajo que quizá no existió."""
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.pausar(ahora=epoch("2026-08-15 10:00:00"))

    abiertas = [p for p in worklog.pausas() if p["open"]]
    assert len(abiertas) == 1
    assert abiertas[0]["end"] is None


def test_borrar_una_pausa_la_devuelve_a_la_jornada():
    """Marcar de más tiene que poder deshacerse."""
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 11:00:00"))
    pausa = worklog.marcar_pausa(
        epoch("2026-08-15 10:00:00"), epoch("2026-08-15 10:59:30")
    )
    con_pausa = total()

    assert worklog.borrar_pausa(pausa["start"]) is True
    assert total() == con_pausa + HORA


# --- El tope ------------------------------------------------------------


def test_el_tope_de_jornada_acota_el_olvido(monkeypatch: pytest.MonkeyPatch):
    """Irse dejando el panel abierto no puede apuntar el día entero."""
    monkeypatch.setattr(worklog, "JORNADA_MAX_HORAS", 4)
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 08:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 20:00:00"))

    assert total() == 4 * HORA


def test_el_tope_se_mide_sobre_lo_contado_no_sobre_el_horario(
    monkeypatch: pytest.MonkeyPatch,
):
    """Aplicado al horario, el tope castigaría a quien marca sus pausas.

    Una jornada de 6 h con 2 h de pausa son 4 h de trabajo y caben enteras
    bajo un tope de 4 h. Si el tope recortara el horario, se quedarían en 2.
    """
    monkeypatch.setattr(worklog, "JORNADA_MAX_HORAS", 4)
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 08:00:00"))
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 14:00:00"))
    worklog.marcar_pausa(epoch("2026-08-15 10:00:00"), epoch("2026-08-15 11:59:30"))

    assert total() == 4 * HORA


# --- El reparto por proyecto --------------------------------------------


def test_la_ranura_se_la_lleva_el_proyecto_mas_cercano_en_el_tiempo():
    """El hueco entre dos proyectos se parte por dónde estabas más cerca."""
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_b", ahora=epoch("2026-08-15 10:00:00"))

    por_espacio = {
        e["space"]: e["seconds"]
        for e in worklog.resumen(modo="workday")["by_space"]
    }
    # La primera media hora es de A y la segunda de B: nada se pierde y nada
    # se cuenta dos veces.
    assert por_espacio["sp_a"] + por_espacio["sp_b"] == HORA + worklog.SLOT_SECONDS
    assert abs(por_espacio["sp_a"] - por_espacio["sp_b"]) <= worklog.SLOT_SECONDS


def test_la_suma_de_los_espacios_nunca_supera_la_jornada():
    """El invariante de siempre, que ningún modo puede romper."""
    for minuto in range(0, 120, 7):
        espacio = "sp_a" if minuto % 2 else "sp_b"
        worklog.registrar(espacio, ahora=epoch("2026-08-15 09:00:00") + minuto * MINUTO)

    datos = worklog.resumen(modo="workday")
    assert sum(e["seconds"] for e in datos["by_space"]) == datos["total_seconds"]
    assert datos["total_seconds"] <= 2 * HORA + worklog.SLOT_SECONDS


# --- Las señales del transcript -----------------------------------------


def _transcript(raiz: Path, cwd: str, instantes: list[str]) -> None:
    """Escribe un transcript de Claude con esos mensajes."""
    directorio = raiz / claude_transcript._slug(cwd)
    directorio.mkdir(parents=True, exist_ok=True)
    lineas = [
        json.dumps(
            {
                "type": "user",
                "cwd": cwd,
                "sessionId": "s1",
                "timestamp": datetime.fromisoformat(t)
                .replace(tzinfo=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "message": {"content": "hola"},
            }
        )
        for t in instantes
    ]
    (directorio / "s1.jsonl").write_text("\n".join(lineas) + "\n")


def test_el_transcript_atribuye_el_rato_sin_latidos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """El caso que motivó todo esto.

    Le hablas a un agente y te vas a mirar otra ventana: el panel no late, pero
    el proyecto estaba trabajando y el transcript lo prueba.
    """
    raiz = tmp_path / "claude-projects"
    monkeypatch.setattr(claude_transcript, "RAIZ_PROYECTOS", raiz)
    monkeypatch.setattr(
        library_store,
        "list_projects",
        lambda: [
            type("P", (), {"cwd": str(tmp_path / "proy"), "space": "sp_trans"})()
        ],
    )
    _transcript(
        raiz,
        str(tmp_path / "proy"),
        ["2026-08-15 09:00:00", "2026-08-15 09:30:00"],
    )
    # Un latido de OTRO espacio, para que el día exista sin tocar sp_trans.
    worklog.registrar("sp_otro", ahora=epoch("2026-08-15 09:45:00"))

    por_espacio = {
        e["space"]: e["seconds"]
        for e in worklog.resumen(modo="workday")["by_space"]
    }
    assert por_espacio.get("sp_trans", 0) > 0
