# US-021 · `os.forkpty()` en lugar de `preexec_fn` (S11)

| Prioridad | Puntos | Fase | Sprint |
|---|---|---|---|
| P3 | 3 | fase-5-deuda | S3 |

## Historia

Como responsable del panel, quiero quitar el `preexec_fn` de `pty_bridge`,
porque los endpoints síncronos de FastAPI corren en un threadpool: el `fork`
ocurre en un proceso **multihilo**, y ese patrón está documentado como
inseguro. El hijo puede bloquearse entre `fork` y `exec` si toma un lock que
otro hilo tenía cogido.

Probabilidad baja, síntoma horrible de diagnosticar: **una terminal que no
abre**, sin error.

## Criterios de aceptación

- [ ] `backend/pty_bridge.py` ya no usa `preexec_fn`.
- [ ] La terminal sigue funcionando: abrir una sesión, escribir, ver el eco,
      redimensionar y cerrar.
- [ ] El redimensionado (`TIOCSWINSZ`) sigue llegando al PTY.
- [ ] Al cerrar el WebSocket no queda ningún proceso huérfano ni ningún fd
      sin cerrar. Compruébalo con `ls /proc/<pid>/fd` antes y después y pon
      el resultado en el PR.
- [ ] Matar la sesión de tmux cierra la terminal del navegador, como ahora.
- [ ] Hay un test que abre el puente, escribe y comprueba el eco. Si montarlo
      resulta inviable en CI, se marca `skip` con motivo **y** se documenta
      el procedimiento de prueba manual — no se da por bueno sin probar.

## Alcance técnico

- `backend/pty_bridge.py`, función `_spawn`/`bridge` (donde vive hoy el
  `subprocess.Popen(..., preexec_fn=lambda: os.login_tty(slave))`).
- `os.forkpty()` devuelve `(pid, fd)` y en el hijo hay que hacer `os.execvp`.
  El manejo de errores del hijo cambia: si `execvp` falla, el hijo tiene que
  salir con `os._exit`, **nunca** con una excepción que se propague.
- El `waitpid` del hijo y la limpieza del fd pasan a ser responsabilidad
  explícita del puente.

## Fuera de alcance

- Cambiar el protocolo del WebSocket o el formato de los mensajes.
- Tocar `XtermTerminal.jsx`.
- Reescribir el puente por encima de lo que exige el cambio de `fork`.

## Dependencias

US-001, US-007.

## Rigor

`exhaustivo`. **Es el cambio más delicado de todo el plan**: toca el camino
del terminal, que es la razón de ser del panel. Por eso va el último.

## Concurrencia

`exclusiva`.

## Notas para el agente

- El plan dice literalmente: dejarlo para el final y con las pruebas ya en
  marcha. Si llegas aquí y la fase 2 no está mergeada, **para y dilo**.
- El riesgo no es que no funcione: es que funcione el 99% de las veces. Un
  fallo entre `fork` y `exec` no da error, da una terminal en blanco.
  Prueba abriendo y cerrando terminales muchas veces seguidas, en paralelo,
  y déjalo escrito en el PR.
- El backend de producción del usuario sirve terminales abiertas. **No lo
  reinicies para probar**: levanta una copia en otro puerto.
