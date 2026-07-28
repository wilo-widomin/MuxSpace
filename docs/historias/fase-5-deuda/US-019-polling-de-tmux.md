# US-019 · `_ensure_tmux_server` una sola vez por proceso

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P2 | 2 | fase-5-deuda | S1 |

## Historia

Como usuario del panel, quiero que **listar sesiones cueste un proceso, no
dos**, porque hoy `list_sessions()` lanza `tmux start-server` **y**
`tmux list-sessions` en cada llamada: con el refresco a 8 segundos son 2
procesos cada 8 s **por pestaña abierta**, todo el día.

`start-server` solo hace falta una vez por proceso del backend.

## Criterios de aceptación

- [ ] `_ensure_tmux_server` (o equivalente) se ejecuta **una sola vez por
      proceso**, con un flag protegido por lock (los endpoints corren en un
      threadpool: dos peticiones simultáneas no pueden lanzarlo dos veces).
- [ ] Si el arranque del servidor **falla**, el flag **no** se marca: el
      siguiente intento lo vuelve a probar. Un fallo transitorio no puede
      dejar el panel muerto hasta el próximo reinicio.
- [ ] Si el servidor de tmux muere estando el backend vivo, el panel se
      recupera: `list_sessions` vuelve a arrancarlo. Hay un test para esto.
- [ ] Test que cuenta las invocaciones: N llamadas a `list_sessions()`
      producen **1** `start-server` y **N** `list-sessions`.
- [ ] `bun run build` no aplica aquí, pero `pytest` y `ruff` sí.
- [ ] Medición antes/después en el PR: número de procesos lanzados en 10
      llamadas.

## Alcance técnico

- `backend/tmux_service.py`.
- Tests en `backend/tests/test_tmux_service.py` (creado por US-007) o en uno
  nuevo si crece demasiado.

## Fuera de alcance

- Cambiar el intervalo de refresco del frontend (8 s) o pasar a push por
  WebSocket. Es otra conversación y no está en el plan.
- Cachear el resultado de `list-sessions`: el listado tiene que seguir
  siendo fresco.

## Dependencias

US-007.

## Rigor

`estándar`. El riesgo real es el criterio del flag: marcarlo antes de saber
si funcionó deja el panel roto hasta reiniciar.

## Concurrencia

`exclusiva` respecto a US-007 y US-021 (tocan tmux y el PTY).

## Notas para el agente

- Es una optimización, así que el listón es: **si no puedes medir la mejora,
  no la has hecho**. Cuenta procesos, no supongas.
- No conviertas esto en una caché. El objetivo es no relanzar el servidor,
  no dejar de preguntar por las sesiones.

## Registro de ejecución

> Generado por `servidor-pipeline`. Tiempos de la última ejecución.

- Inicio: 2026-07-28 15:05:37 UTC
- Fin:    2026-07-28 15:29:32 UTC
- Tiempo transcurrido: 00:23:55 (HH:mm:ss)
- PR:     (sin PR)
- Estado: in-review
