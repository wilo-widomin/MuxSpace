"""Lectura del transcript de una sesión de Claude Code para poder buscarlo.

## Por qué existe

Un panel donde corre Claude Code ocupa la **pantalla alternativa** del
terminal: tmux no guarda ni una línea de lo que pinta (medido: `history_size`
0), así que la búsqueda del copy-mode —la que usa el panel en una shell— no
tiene ahí nada que mirar. Lo que ya se fue por arriba solo se puede volver a
ver haciendo scroll dentro del propio Claude, a ojo.

Pero ese contenido sí existe en disco: Claude Code escribe la conversación en
`~/.claude/projects/<proyecto>/<sesión>.jsonl`, y con MÁS detalle del que se
vio en pantalla (las salidas de herramientas se recortan al pintarlas, no al
guardarlas). Este módulo lo lee y lo normaliza para que el panel pueda
mostrarlo en un modal y buscar dentro.

## Lo que NO hace

No mueve la vista de Claude ni habla con él: solo lee un archivo. Claude
manda en su pantalla y eso no cambia.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import logs

_log = logs.obtener(__name__)

RAIZ_PROYECTOS = Path.home() / ".claude" / "projects"

# Cuánto se devuelve. Un transcript puede pasar de 5 MB y el modal lo pinta
# entero en el navegador: sin tope, abrir la búsqueda congelaría la pestaña.
MAX_MENSAJES = 1000
MAX_CARACTERES_BLOQUE = 4000

# Entradas del .jsonl que NO son conversación (estado interno del cliente).
# Se filtran por lista blanca: lo que no se sepa interpretar, fuera.
_TIPOS_UTILES = {"user", "assistant"}


def _slug(ruta: str) -> str:
    """Nombre del directorio que Claude Code usa para un proyecto.

    Es la ruta con todo lo que no sea alfanumérico convertido en guion:
    `/home/willy/proyectos/muxspace` -> `-home-willy-proyectos-muxspace`.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", ruta)


def directorio_de(cwd: str) -> Path | None:
    """Directorio de transcripts del proyecto que hay en `cwd`, si existe."""
    candidato = RAIZ_PROYECTOS / _slug(cwd)
    # `resolve` + comprobación de ancestro: `cwd` viene de tmux, no del
    # usuario, pero un directorio con `..` en el nombre no debe poder sacarnos
    # de ~/.claude/projects.
    try:
        real = candidato.resolve()
        real.relative_to(RAIZ_PROYECTOS.resolve())
    except (OSError, ValueError):
        return None
    return real if real.is_dir() else None


def sesion_mas_reciente(directorio: Path) -> Path | None:
    """El `.jsonl` tocado más recientemente: el de la sesión que está viva."""
    transcripts = [p for p in directorio.glob("*.jsonl") if p.is_file()]
    if not transcripts:
        return None
    return max(transcripts, key=lambda p: p.stat().st_mtime)


def _recortar(texto: str) -> str:
    if len(texto) <= MAX_CARACTERES_BLOQUE:
        return texto
    return texto[:MAX_CARACTERES_BLOQUE] + "\n[…]"


def _bloques(contenido: Any) -> list[dict[str, str]]:
    """Aplana el `content` de un mensaje en bloques de texto etiquetados.

    Las llamadas a herramientas y sus salidas se incluyen a propósito: muchas
    veces lo que el usuario busca (un comando, un error, una ruta) está ahí y
    no en la prosa.
    """
    if isinstance(contenido, str):
        return [{"kind": "text", "text": contenido}]
    if not isinstance(contenido, list):
        return []

    bloques: list[dict[str, str]] = []
    for parte in contenido:
        if not isinstance(parte, dict):
            continue
        tipo = parte.get("type")
        if tipo == "text" and parte.get("text"):
            bloques.append({"kind": "text", "text": parte["text"]})
        elif tipo == "thinking" and parte.get("thinking"):
            bloques.append({"kind": "thinking", "text": parte["thinking"]})
        elif tipo == "tool_use":
            entrada = parte.get("input")
            # El comando de un Bash o la ruta de un Read son lo interesante;
            # el JSON crudo es lo único que sirve para todas las herramientas.
            texto = entrada if isinstance(entrada, str) else json.dumps(
                entrada, ensure_ascii=False, indent=2
            )
            bloques.append({
                "kind": "tool_use",
                "name": str(parte.get("name", "")),
                "text": _recortar(texto or ""),
            })
        elif tipo == "tool_result":
            interior = parte.get("content")
            if isinstance(interior, list):
                texto = "\n".join(
                    x.get("text", "") for x in interior if isinstance(x, dict)
                )
            else:
                texto = interior if isinstance(interior, str) else ""
            if texto:
                bloques.append({"kind": "tool_result", "text": _recortar(texto)})
    return bloques


def leer(transcript: Path) -> list[dict[str, Any]]:
    """Convierte el `.jsonl` en una lista de mensajes lista para pintar.

    Se lee entero y se devuelven los **últimos** `MAX_MENSAJES`: lo reciente
    es lo que se busca casi siempre, y es donde el usuario se queda al abrir.
    """
    mensajes: list[dict[str, Any]] = []
    with transcript.open(errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                dato = json.loads(linea)
            except ValueError:
                # Una línea a medio escribir (la sesión está viva) no puede
                # tumbar la lectura del resto.
                continue
            if dato.get("type") not in _TIPOS_UTILES:
                continue
            mensaje = dato.get("message")
            if not isinstance(mensaje, dict):
                continue
            bloques = _bloques(mensaje.get("content"))
            if not bloques:
                continue
            mensajes.append({
                "role": dato.get("type"),
                "timestamp": dato.get("timestamp", ""),
                "blocks": bloques,
            })
    return mensajes[-MAX_MENSAJES:]


def para_cwd(cwd: str) -> dict[str, Any]:
    """Transcript de la sesión de Claude que corre en `cwd`.

    Devuelve siempre la misma forma; `available` en falso con un motivo
    cuando no hay nada que enseñar, para que el panel pueda decir POR QUÉ en
    vez de abrir un modal vacío.
    """
    directorio = directorio_de(cwd)
    if directorio is None:
        return {"available": False, "reason": "no_project", "messages": []}
    transcript = sesion_mas_reciente(directorio)
    if transcript is None:
        return {"available": False, "reason": "no_session", "messages": []}
    try:
        mensajes = leer(transcript)
    except OSError:
        _log.info("no se pudo leer el transcript %s", transcript, exc_info=True)
        return {"available": False, "reason": "unreadable", "messages": []}
    return {
        "available": True,
        "reason": "",
        "session": transcript.stem,
        "messages": mensajes,
    }
