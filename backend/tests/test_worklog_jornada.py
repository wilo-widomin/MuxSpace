"""El modo 'workday': la jornada entera menos las pausas marcadas.

## Por qué existe este modo

El modo 'measured' pregunta «¿tocaste algo hace menos de tres minutos?», y con
la forma real de trabajar —lanzar un agente y mirar otra cosa mientras
construye— la respuesta es que no casi todo el rato. Medido sobre un día real
del usuario: 3 h 25 apuntadas de una jornada de 8 h 30.

El modo 'workday' invierte la carga de la prueba. La jornada cuenta entera
entre la primera y la última señal del día. Las señales —latidos y
transcripts— dejan de decidir *si* trabajaste y pasan a decidir sobre todo *en
qué proyecto*.

## Cómo puede mentir este modo

Al revés que el otro: **contando de más**. Sus formas de fallar son dejarse
una pausa sin restar, apuntar el rato en que no había nadie delante, estirar
la jornada más allá del día (la noche entre dos jornadas), y no parar nunca si
se olvida marcar el final. Contra esas van los tests.

Contra la segunda va la **ausencia deducida**: un hueco sin ninguna señal —ni
una tecla ni una línea de agente, en ningún proyecto— más largo que el umbral
no se cuenta. Y como ningún umbral acierta siempre, lo excepcional se reclama:
un hueco reclamado vuelve a contar.

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


def jornada(espacio: str, desde: str, hasta: str, cada: int = 10 * MINUTO) -> None:
    """Late en ese espacio cada `cada` segundos, extremos incluidos.

    Una jornada de verdad deja señales repartidas por el día; los tests que
    solo ponen dos latidos separados por horas describen precisamente lo que
    ya NO cuenta (ver los tests de ausencia).
    """
    principio, final = epoch(desde), epoch(hasta)
    instante = principio
    while instante <= final:
        worklog.registrar(espacio, ahora=instante)
        instante += cada


# --- La jornada ---------------------------------------------------------


def test_la_jornada_cuenta_entera_entre_la_primera_y_la_ultima_senal():
    """Los ratos entre latidos cuentan: el agente construía y tú esperabas.

    Es el cambio de fondo respecto a 'measured'. Los latidos van cada 10 min,
    que es lo que deja una jornada real: por debajo del umbral de ausencia, el
    hueco entre dos es trabajo.
    """
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")

    assert total() == HORA + worklog.SLOT_SECONDS


def test_en_modo_medido_ese_mismo_dia_cuenta_solo_lo_que_dejo_rastro():
    """El contraste que justifica todo el modo: los mismos datos, 3 minutos."""
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")

    assert worklog.resumen(modo="measured")["total_seconds"] == 7 * worklog.SLOT_SECONDS


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
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 12:00:00")
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
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 11:00:00")
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
    jornada("sp_a", "2026-08-15 08:00:00", "2026-08-15 20:00:00")

    assert total() == 4 * HORA


def test_el_tope_se_mide_sobre_lo_contado_no_sobre_el_horario(
    monkeypatch: pytest.MonkeyPatch,
):
    """Aplicado al horario, el tope castigaría a quien marca sus pausas.

    Una jornada de 6 h con 2 h de pausa son 4 h de trabajo y caben enteras
    bajo un tope de 4 h. Si el tope recortara el horario, se quedarían en 2.
    """
    monkeypatch.setattr(worklog, "JORNADA_MAX_HORAS", 4)
    jornada("sp_a", "2026-08-15 08:00:00", "2026-08-15 14:00:00")
    worklog.marcar_pausa(epoch("2026-08-15 10:00:00"), epoch("2026-08-15 11:59:30"))

    assert total() == 4 * HORA


# --- Las ausencias deducidas --------------------------------------------


def test_un_hueco_largo_sin_ninguna_senal_no_cuenta():
    """La comida no se apunta, y no hay que declararla.

    Media hora sin una tecla ni una línea de agente en NINGÚN proyecto no es
    trabajo esperando a un agente: no había nadie delante.
    """
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")

    # Las dos horas de verdad, sin las dos de la ausencia de en medio.
    assert total() == 2 * HORA + 2 * worklog.SLOT_SECONDS


def test_el_hueco_reclamado_vuelve_a_contar():
    """Una tarde de pizarra no deja señales y sigue siendo trabajo.

    Ningún umbral distingue una reunión de una siesta, así que la excepción la
    marca el usuario. Y solo la excepción: reclamar es un clic al revisar los
    tiempos, no una pregunta cada vez que uno se levanta.
    """
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")
    sin_reclamar = total()

    hueco = worklog.huecos()[0]
    worklog.reclamar_hueco(hueco["start"], hueco["end"])

    assert total() == sin_reclamar + hueco["seconds"]


def test_quitar_el_reclamo_devuelve_el_hueco_a_la_ausencia():
    """Reclamar de más se deshace igual que marcar una pausa de más."""
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")
    sin_reclamar = total()
    hueco = worklog.huecos()[0]
    worklog.reclamar_hueco(hueco["start"], hueco["end"])

    assert worklog.borrar_reclamo(hueco["start"]) is True
    assert total() == sin_reclamar


def test_responder_que_estabas_fuera_no_cambia_el_total_pero_queda_guardado():
    """La respuesta vive en el servidor, no en la pestaña.

    Es lo que permite que pregunte UNA sola ventana: se contesta en la que
    estás mirando y las demás lo saben. Guardar solo el «sí trabajaba» dejaría
    el «estaba fuera» indistinguible de «nadie ha contestado todavía», y la
    pregunta volvería a saltar en la ventana siguiente.
    """
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")
    antes = total()
    hueco = worklog.huecos()[0]
    assert hueco["answered"] is False

    worklog.reclamar_hueco(hueco["start"], hueco["end"], trabajado=False)

    assert total() == antes
    respondido = worklog.huecos()[0]
    assert respondido["answered"] is True
    assert respondido["claimed"] is False


def test_borrar_la_respuesta_vuelve_a_dejar_el_hueco_por_preguntar():
    """Deshacer una respuesta la borra entera, no la cambia de signo."""
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")
    hueco = worklog.huecos()[0]
    worklog.reclamar_hueco(hueco["start"], hueco["end"], trabajado=False)

    assert worklog.borrar_reclamo(hueco["start"]) is True
    assert worklog.huecos()[0]["answered"] is False


def test_el_hueco_se_lista_con_su_duracion_y_si_esta_reclamado():
    """El panel enseña lo descontado: un descuento invisible no se corrige."""
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")

    [hueco] = worklog.huecos()
    assert hueco["start"] == epoch("2026-08-15 10:00:30")
    assert hueco["end"] == epoch("2026-08-15 12:00:00")
    assert hueco["claimed"] is False

    worklog.reclamar_hueco(hueco["start"], hueco["end"])
    assert worklog.huecos()[0]["claimed"] is True


def test_una_ausencia_nunca_borra_tiempo_medido():
    """El descuento solo puede tapar ranuras que nadie latió.

    Es lo que hace que el cambio sea seguro: por definición, dentro de un hueco
    «sin ninguna señal» no hay ninguna señal que borrar.
    """
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 13:00:00", cada=45 * MINUTO)

    medido = worklog.resumen(modo="measured")["total_seconds"]
    assert total() >= medido


def test_la_noche_no_es_un_hueco_que_descontar():
    """Entre dos días no hay ausencia: la jornada se acabó y ya está."""
    jornada("sp_a", "2026-08-15 17:00:00", "2026-08-15 18:00:00")
    jornada("sp_a", "2026-08-16 09:00:00", "2026-08-16 10:00:00")

    assert worklog.huecos() == []


def test_el_umbral_a_cero_apaga_el_descuento():
    """Volver al modelo anterior es una variable, no un despliegue."""
    jornada("sp_a", "2026-08-15 09:00:00", "2026-08-15 10:00:00")
    jornada("sp_a", "2026-08-15 12:00:00", "2026-08-15 13:00:00")

    assert worklog.huecos(umbral_min=0) == []
    ranuras = worklog._ranuras_jornada(None, None, 0, umbral_min=0)
    assert len(ranuras) * worklog.SLOT_SECONDS == 4 * HORA + worklog.SLOT_SECONDS


# --- El reparto por proyecto --------------------------------------------


def test_la_ranura_se_la_lleva_el_proyecto_mas_cercano_en_el_tiempo():
    """El hueco entre dos proyectos se parte por dónde estabas más cerca."""
    worklog.registrar("sp_a", ahora=epoch("2026-08-15 09:00:00"))
    worklog.registrar("sp_b", ahora=epoch("2026-08-15 09:20:00"))

    por_espacio = {
        e["space"]: e["seconds"]
        for e in worklog.resumen(modo="workday")["by_space"]
    }
    # Los primeros diez minutos son de A y los otros diez de B: nada se pierde
    # y nada se cuenta dos veces.
    contado = por_espacio["sp_a"] + por_espacio["sp_b"]
    assert contado == 20 * MINUTO + worklog.SLOT_SECONDS
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
