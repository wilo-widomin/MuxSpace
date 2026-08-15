"""Lectura del transcript de Claude, que es lo que se busca en un panel suyo.

## Por qué hace falta esto

En un panel donde corre Claude Code, tmux no guarda **nada** (pantalla
alternativa, `history_size` 0): lo que se fue de pantalla no está en ningún
buffer del terminal. La única copia está en el `.jsonl` de la sesión, así que
si esta lectura falla o se deja bloques por el camino, la búsqueda del panel
dice "sin resultados" sobre algo que sí se dijo — el peor fallo posible aquí,
porque parece una respuesta y es una mentira.

Los transcripts de verdad del usuario NO se tocan: cada test escribe su
propio árbol y apunta `RAIZ_PROYECTOS` ahí.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import claude_transcript as ct


@pytest.fixture
def proyectos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raiz = tmp_path / "projects"
    raiz.mkdir()
    monkeypatch.setattr(ct, "RAIZ_PROYECTOS", raiz)
    return raiz


def escribir(destino: Path, entradas: list[dict]) -> None:
    destino.write_text("\n".join(json.dumps(e) for e in entradas) + "\n")


def mensaje(role: str, contenido, ts: str = "2026-08-15T09:00:00Z") -> dict:
    return {"type": role, "timestamp": ts, "message": {"content": contenido}}


def test_el_slug_es_el_directorio_que_usa_claude() -> None:
    """El nombre del directorio se deriva de la ruta, no se busca a ciegas."""
    assert (
        ct._slug("/home/willy/proyectos/muxspace") == "-home-willy-proyectos-muxspace"
    )


def test_lee_la_conversacion_con_texto_y_herramientas(proyectos: Path) -> None:
    """Se conservan las llamadas a herramientas y sus salidas.

    No es un adorno: muchas veces lo que el usuario busca es un comando que
    lanzó o el error que salió, y eso vive en esos bloques, no en la prosa.
    """
    dir_proyecto = proyectos / ct._slug("/tmp/proyecto")
    dir_proyecto.mkdir()
    escribir(dir_proyecto / "sesion.jsonl", [
        mensaje("user", "¿dónde está MiAguja?"),
        mensaje("assistant", [
            {"type": "text", "text": "La busco"},
            {"type": "tool_use", "name": "Bash", "input": {"command": "grep MiAguja"}},
        ]),
        mensaje("user", [
            {"type": "tool_result", "content": [{"text": "MiAguja encontrada"}]},
        ]),
        # Ruido interno del cliente: no es conversación y no debe aparecer.
        {"type": "file-history-snapshot", "message": {"content": "MiAguja"}},
    ])

    datos = ct.para_cwd("/tmp/proyecto")

    assert datos["available"] is True
    assert datos["session"] == "sesion"
    assert len(datos["messages"]) == 3, "se coló una entrada que no es conversación"
    tipos = [b["kind"] for m in datos["messages"] for b in m["blocks"]]
    assert tipos == ["text", "text", "tool_use", "tool_result"]
    todo = " ".join(b["text"] for m in datos["messages"] for b in m["blocks"])
    assert "grep MiAguja" in todo, "se perdió el comando de la herramienta"
    assert "MiAguja encontrada" in todo, "se perdió la salida de la herramienta"


def test_una_linea_a_medio_escribir_no_tumba_la_lectura(proyectos: Path) -> None:
    """La sesión está VIVA mientras se lee: la última línea puede ir a medias."""
    dir_proyecto = proyectos / ct._slug("/tmp/proyecto")
    dir_proyecto.mkdir()
    ruta = dir_proyecto / "sesion.jsonl"
    escribir(ruta, [mensaje("user", "entero")])
    with ruta.open("a") as f:
        f.write('{"type": "assistant", "mess')

    datos = ct.para_cwd("/tmp/proyecto")

    assert datos["available"] is True
    assert len(datos["messages"]) == 1


def test_coge_la_sesion_mas_reciente(proyectos: Path) -> None:
    """Con varias sesiones del mismo proyecto, la viva es la última tocada."""
    dir_proyecto = proyectos / ct._slug("/tmp/proyecto")
    dir_proyecto.mkdir()
    vieja = dir_proyecto / "vieja.jsonl"
    nueva = dir_proyecto / "nueva.jsonl"
    escribir(vieja, [mensaje("user", "lo de ayer")])
    escribir(nueva, [mensaje("user", "lo de ahora")])
    import os
    os.utime(vieja, (1_000_000, 1_000_000))

    assert ct.para_cwd("/tmp/proyecto")["session"] == "nueva"


def test_sin_proyecto_lo_dice_en_vez_de_reventar(proyectos: Path) -> None:
    """El panel necesita poder explicar POR QUÉ no hay nada que enseñar."""
    datos = ct.para_cwd("/tmp/un-sitio-sin-claude")
    assert datos == {"available": False, "reason": "no_project", "messages": []}


def test_no_se_puede_salir_de_la_raiz_de_proyectos(proyectos: Path) -> None:
    """El cwd viene de tmux, pero eso no lo convierte en una ruta de confianza.

    Un directorio con `..` en el nombre no debe poder apuntar a otro sitio del
    disco: lo que se sirve tiene que estar SIEMPRE bajo ~/.claude/projects.
    """
    fuera = proyectos.parent / "fuera"
    fuera.mkdir()
    escribir(fuera / "sesion.jsonl", [mensaje("user", "secreto")])
    (proyectos / "..-fuera").symlink_to(fuera, target_is_directory=True)

    datos = ct.para_cwd("/../fuera")

    assert datos["available"] is False, (
        "se ha servido un transcript de fuera de la raíz de proyectos"
    )


def test_los_bloques_enormes_se_recortan(proyectos: Path) -> None:
    """El modal lo pinta el navegador: una salida de 10 MB congela la pestaña."""
    dir_proyecto = proyectos / ct._slug("/tmp/proyecto")
    dir_proyecto.mkdir()
    escribir(dir_proyecto / "sesion.jsonl", [
        mensaje("user", [{"type": "tool_result", "content": "x" * 50_000}]),
    ])

    bloque = ct.para_cwd("/tmp/proyecto")["messages"][0]["blocks"][0]

    assert len(bloque["text"]) <= ct.MAX_CARACTERES_BLOQUE + 10
    assert bloque["text"].endswith("[…]"), "se recortó sin decirlo"
